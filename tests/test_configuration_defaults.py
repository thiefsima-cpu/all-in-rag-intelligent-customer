from __future__ import annotations

import importlib
import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from rag_modules.configuration.env import EnvConfigSource
from rag_modules.configuration.loader import load_config
from rag_modules.configuration.models import GraphRAGConfig


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

            self.assertEqual(reloaded_module.DEFAULT_CONFIG.value, "lazy-config")
            self.assertEqual(calls, ["load"])

        importlib.reload(configuration_module)

    def test_default_config_proxy_preserves_common_config_methods(self) -> None:
        import rag_modules.configuration as configuration_module
        import rag_modules.configuration.loader as loader_module

        sentinel = SimpleNamespace(
            value="lazy-config",
            to_dict=lambda: {"value": "lazy-config"},
            to_domain_dict=lambda: {"models": {"llm_model": "stub"}},
        )

        with patch.object(loader_module, "load_config", return_value=sentinel):
            reloaded_module = importlib.reload(configuration_module)
            self.assertEqual(reloaded_module.DEFAULT_CONFIG.to_dict(), {"value": "lazy-config"})
            self.assertEqual(
                reloaded_module.DEFAULT_CONFIG.to_domain_dict(),
                {"models": {"llm_model": "stub"}},
            )

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


if __name__ == "__main__":
    unittest.main()
