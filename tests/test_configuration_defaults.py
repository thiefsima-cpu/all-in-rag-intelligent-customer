from __future__ import annotations

import importlib
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from rag_modules.configuration import ConfigurationError
from rag_modules.configuration.env import EnvConfigSource
from rag_modules.configuration.environment_schema import ENV_FIELD_SPECS, EnvFieldSpec
from rag_modules.configuration.loader import load_config
from rag_modules.configuration.models import (
    ApiSettings,
    GenerationSettings,
    GraphRAGConfig,
    GraphSettings,
    ModelSettings,
    ObservabilitySettings,
    QueryUnderstandingSettings,
    RetrievalSettings,
    StorageSettings,
)
from rag_modules.configuration.testing import (
    build_test_config,
    planner_runtime_settings,
    semantic_runtime_settings,
)


def test_configuration_declarations_have_canonical_owners() -> None:
    section_types = (
        ApiSettings,
        GenerationSettings,
        GraphSettings,
        ModelSettings,
        ObservabilitySettings,
        QueryUnderstandingSettings,
        RetrievalSettings,
        StorageSettings,
    )
    assert {section_type.__module__ for section_type in section_types} == {
        "rag_modules.configuration.models"
    }
    assert EnvFieldSpec.__module__ == "rag_modules.configuration.environment_schema"
    top_k_spec = next(spec for spec in ENV_FIELD_SPECS if "TOP_K" in spec.names)
    assert top_k_spec.path == ("retrieval", "top_k")


class ConfigurationDefaultTests(unittest.TestCase):
    def test_configuration_module_loads_default_config_lazily(self) -> None:
        import rag_modules.configuration as configuration_module
        import rag_modules.configuration.loader as loader_module

        sentinel = SimpleNamespace(value="lazy-config")
        calls: list[str] = []

        def fake_load_config():
            calls.append("load")
            return sentinel

        with patch.object(loader_module, "load_config", side_effect=fake_load_config):
            reloaded_module = importlib.reload(configuration_module)
            self.assertEqual(calls, [])

            resolved = reloaded_module.get_default_config()
            self.assertIs(resolved, sentinel)
            self.assertEqual(calls, ["load"])

        importlib.reload(configuration_module)

    def test_default_config_proxy_is_retired(self) -> None:
        import rag_modules.configuration as configuration_module

        reloaded_module = importlib.reload(configuration_module)

        self.assertFalse(hasattr(reloaded_module, "DEFAULT_CONFIG"))
        importlib.reload(configuration_module)

    def test_explicit_config_source_skips_dotenv_loading(self) -> None:
        with patch("rag_modules.configuration.loader.load_dotenv") as load_dotenv_mock:
            load_config(source=EnvConfigSource(environ={}))

        load_dotenv_mock.assert_not_called()

    def test_graph_rag_config_from_dict_ignores_ambient_environment(self) -> None:
        with patch.dict(
            "os.environ",
            {
                "LLM_MODEL": "ambient-model",
                "INDEX_CACHE_DIR": "storage/ambient-indexes",
            },
            clear=False,
        ):
            config = GraphRAGConfig.from_dict(
                {
                    "models": {"llm_model": "explicit-model"},
                    "storage": {"index_cache_dir": "storage/explicit-indexes"},
                }
            )

        self.assertEqual(config.models.llm_model, "explicit-model")
        self.assertEqual(config.storage.index_cache_dir, "storage/explicit-indexes")
        self.assertEqual(
            config.storage.artifact_manifest_path,
            os.path.join("storage/explicit-indexes", "artifact_manifest.json"),
        )

    def test_with_overrides_recomputes_derived_storage_paths(self) -> None:
        config = load_config(source=EnvConfigSource(environ={}))

        updated = config.with_overrides(
            {"storage": {"index_cache_dir": "storage/override-indexes"}}
        )

        self.assertEqual(updated.storage.index_cache_dir, "storage/override-indexes")
        self.assertEqual(
            updated.storage.artifact_manifest_path,
            os.path.join("storage/override-indexes", "artifact_manifest.json"),
        )
        self.assertEqual(
            updated.storage.build_job_store_path,
            os.path.join("storage/override-indexes", "build_jobs.json"),
        )

    def test_test_config_defaults_build_job_store_to_unique_temp_path(self) -> None:
        first = build_test_config()
        second = build_test_config()

        temp_root = Path(tempfile.gettempdir()).resolve()
        first_store = Path(first.storage.build_job_store_path).resolve()
        second_store = Path(second.storage.build_job_store_path).resolve()

        self.assertIn(temp_root, first_store.parents)
        self.assertIn(temp_root, second_store.parents)
        self.assertNotEqual(first_store, second_store)
        self.assertNotEqual(
            os.path.normpath(first.storage.build_job_store_path),
            os.path.normpath(os.path.join("storage", "indexes", "build_jobs.json")),
        )

    def test_default_management_surfaces_are_production_safe(self) -> None:
        config = load_config(source=EnvConfigSource(environ={}))

        self.assertFalse(config.api.docs_enabled)
        self.assertFalse(config.api.openapi_enabled)
        self.assertFalse(config.api.docs_public)
        self.assertFalse(config.api.openapi_public)
        self.assertFalse(config.observability.prometheus_public)

    def test_default_retrieval_models_use_requested_qwen_versions(self) -> None:
        config = load_config(source=EnvConfigSource(environ={}))

        self.assertEqual(config.models.embedding_model, "qwen3-vl-embedding")
        self.assertEqual(config.models.embedding_dimension, 1024)
        self.assertEqual(config.models.rerank_model, "qwen3-vl-rerank")
        self.assertEqual(
            config.models.rerank_base_url,
            "https://dashscope.aliyuncs.com/api/v1/services/rerank/text-rerank/text-rerank",
        )

    def test_default_build_job_history_limits_are_bounded(self) -> None:
        config = load_config(source=EnvConfigSource(environ={}))

        self.assertEqual(config.api.build_job_runner_backend, "in_process")
        self.assertEqual(config.api.build_job_runner_max_workers, 1)
        self.assertEqual(config.api.build_job_worker_poll_interval_seconds, 1.0)
        self.assertEqual(config.api.build_job_retention_limit, 100)
        self.assertEqual(config.api.build_job_list_default_limit, 50)
        self.assertEqual(config.api.build_job_list_max_limit, 100)
        self.assertEqual(config.api.build_job_lease_seconds, 30.0)
        self.assertEqual(config.api.build_job_heartbeat_seconds, 10.0)

    def test_dimension_mismatch_reports_both_field_paths(self) -> None:
        with self.assertRaises(ConfigurationError) as context:
            GraphRAGConfig.from_dict(
                {
                    "storage": {"milvus_dimension": 512},
                    "models": {"embedding_dimension": 1024},
                }
            )

        message = str(context.exception)
        self.assertIn("storage.milvus_dimension", message)
        self.assertIn("models.embedding_dimension", message)
        self.assertIn("overrides", message)
        self.assertIn("GraphRAGConfig.from_dict", message)
        self.assertIn("must match", message)

    def test_runtime_settings_are_derived_from_resolved_config(self) -> None:
        config = build_test_config(
            {
                "models": {
                    "llm_model": "resolved-planner-model",
                    "llm_timeout_seconds": 37,
                },
                "query_understanding": {
                    "planner": {"cache_size": 23},
                    "semantics": {
                        "scoring": {"reasoning_complexity_threshold": 0.83},
                        "extraction": {"source_entity_limit": 7},
                    },
                },
            }
        )

        planner = planner_runtime_settings(config)
        semantics = semantic_runtime_settings(config)

        self.assertEqual(planner.model_name, config.models.llm_model)
        self.assertEqual(planner.timeout_seconds, config.models.llm_timeout_seconds)
        self.assertEqual(planner.cache_size, config.query_understanding.planner.cache_size)
        self.assertEqual(
            semantics.reasoning_complexity_threshold,
            config.query_understanding.semantics.scoring.reasoning_complexity_threshold,
        )
        self.assertEqual(
            semantics.source_entity_limit,
            config.query_understanding.semantics.extraction.source_entity_limit,
        )


if __name__ == "__main__":
    unittest.main()
