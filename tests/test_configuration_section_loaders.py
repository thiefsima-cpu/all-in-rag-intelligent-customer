from __future__ import annotations

import os
import unittest

from rag_modules.configuration import ConfigurationError
from rag_modules.configuration.env import EnvConfigSource
from rag_modules.configuration.loader import load_config
from rag_modules.configuration.sections import load_api_settings


class ConfigurationSectionLoaderTests(unittest.TestCase):
    def assertConfigErrorMentions(
        self,
        error: ConfigurationError,
        *expected_fragments: str,
    ) -> None:
        message = str(error)
        for fragment in expected_fragments:
            self.assertIn(fragment, message)

    def test_storage_settings_respect_environment_overrides(self) -> None:
        config = load_config(
            source=EnvConfigSource(
                environ={
                    "INDEX_CACHE_DIR": "storage/custom-indexes",
                    "NEO4J_URI": "bolt://graph.example:7687",
                    "MILVUS_PORT": "20000",
                    "MILVUS_BLUE_GREEN_ENABLED": "false",
                    "MILVUS_COLLECTION_ALIAS_SUFFIX": "__serving",
                }
            )
        )

        self.assertEqual(config.storage.index_cache_dir, "storage/custom-indexes")
        self.assertEqual(
            config.storage.artifact_manifest_path,
            os.path.join("storage/custom-indexes", "artifact_manifest.json"),
        )
        self.assertEqual(config.storage.neo4j_uri, "bolt://graph.example:7687")
        self.assertEqual(config.storage.milvus_port, 20000)
        self.assertFalse(config.storage.milvus_blue_green_enabled)
        self.assertEqual(config.storage.milvus_collection_alias_suffix, "__serving")

    def test_model_settings_respect_environment_overrides(self) -> None:
        config = load_config(
            source=EnvConfigSource(
                environ={
                    "OPENAI_API_KEY": "test-key",
                    "LLM_MODEL": "qwen-test",
                    "EMBEDDING_BATCH_SIZE": "24",
                }
            )
        )

        self.assertEqual(config.models.api_key, "test-key")
        self.assertEqual(config.models.llm_model, "qwen-test")
        self.assertEqual(config.models.embedding_batch_size, 24)

    def test_retrieval_settings_respect_environment_overrides(self) -> None:
        config = load_config(
            source=EnvConfigSource(
                environ={
                    "TOP_K": "9",
                    "HYBRID_DEFAULT_CANDIDATE_MULTIPLIER": "4",
                    "RETRIEVAL_CANDIDATE_SOURCE_FAILURE_THRESHOLD": "3",
                    "RETRIEVAL_CANDIDATE_SOURCE_RECOVERY_SECONDS": "12.5",
                    "RETRIEVAL_CANDIDATE_SOURCE_DEGRADATION_STRATEGY": "fail_fast",
                    "ENABLE_PARENT_DOC_RETRIEVAL": "false",
                }
            )
        )

        self.assertEqual(config.retrieval.top_k, 9)
        self.assertEqual(config.retrieval.hybrid_default_candidate_multiplier, 4)
        self.assertEqual(config.retrieval.candidate_source_failure_threshold, 3)
        self.assertEqual(config.retrieval.candidate_source_recovery_seconds, 12.5)
        self.assertEqual(config.retrieval.candidate_source_degradation_strategy, "fail_fast")
        self.assertFalse(config.retrieval.enable_parent_doc_retrieval)

    def test_retrieval_settings_reject_invalid_candidate_source_degradation_strategy(self) -> None:
        with self.assertRaises(ConfigurationError) as context:
            load_config(
                source=EnvConfigSource(
                    environ={
                        "RETRIEVAL_CANDIDATE_SOURCE_DEGRADATION_STRATEGY": "keep_going",
                    }
                )
            )

        self.assertConfigErrorMentions(
            context.exception,
            "candidate_source_degradation_strategy",
            "continue",
            "fail_fast",
        )

    def test_generation_settings_respect_environment_overrides(self) -> None:
        config = load_config(
            source=EnvConfigSource(
                environ={
                    "TEMPERATURE": "0.35",
                    "GENERATION_ENABLE_TWO_STAGE": "false",
                    "GENERATION_DIRECT_MAX_TOKENS": "777",
                    "GENERATION_LATENCY_BUDGET_SECONDS": "19",
                }
            )
        )

        self.assertEqual(config.generation.temperature, 0.35)
        self.assertFalse(config.generation.generation_enable_two_stage)
        self.assertEqual(config.generation.generation_direct_max_tokens, 777)
        self.assertEqual(config.generation.generation_latency_budget_seconds, 19)

    def test_graph_settings_respect_environment_overrides(self) -> None:
        config = load_config(
            source=EnvConfigSource(
                environ={
                    "ENABLE_SEMANTIC_GRAPH_SCHEMA": "false",
                    "CHUNK_SIZE": "640",
                    "ENTITY_LINKER_MIN_CONFIDENCE": "0.61",
                }
            )
        )

        self.assertFalse(config.graph.enable_semantic_graph_schema)
        self.assertEqual(config.graph.chunk_size, 640)
        self.assertEqual(config.graph.entity_linker_min_confidence, 0.61)

    def test_observability_settings_respect_environment_overrides(self) -> None:
        config = load_config(
            source=EnvConfigSource(
                environ={
                    "ENABLE_QUERY_TRACING": "false",
                    "QUERY_TRACE_PATH": "storage/test-traces/query_trace.jsonl",
                    "QUERY_TRACE_MAX_QUEUE_SIZE": "32",
                    "QUERY_TRACE_FINGERPRINT_SALT": "test-trace-salt",
                    "PROMETHEUS_METRICS_PUBLIC": "true",
                }
            )
        )

        self.assertFalse(config.observability.enable_query_tracing)
        self.assertEqual(
            config.observability.query_trace_path,
            "storage/test-traces/query_trace.jsonl",
        )
        self.assertEqual(config.observability.query_trace_max_queue_size, 32)
        self.assertEqual(
            config.observability.query_trace_fingerprint_salt,
            "test-trace-salt",
        )
        self.assertTrue(config.observability.prometheus_public)

    def test_api_settings_respect_environment_overrides(self) -> None:
        config = load_config(
            source=EnvConfigSource(
                environ={
                    "API_AUTH_ENABLED": "false",
                    "API_ACCESS_TOKEN": "test-access-token",
                    "API_DOCS_ENABLED": "true",
                    "API_OPENAPI_ENABLED": "true",
                    "API_DOCS_PUBLIC": "true",
                    "API_OPENAPI_PUBLIC": "true",
                    "API_MAX_REQUEST_BODY_BYTES": "32768",
                    "API_MAX_CONCURRENT_ANSWERS": "3",
                    "API_ANSWER_ACQUIRE_TIMEOUT_SECONDS": "0.5",
                    "API_STREAM_EXECUTOR_MAX_WORKERS": "8",
                    "API_STREAM_QUEUE_MAX_SIZE": "128",
                    "API_BUILD_JOB_RETENTION_LIMIT": "12",
                    "API_BUILD_JOB_LIST_DEFAULT_LIMIT": "4",
                    "API_BUILD_JOB_LIST_MAX_LIMIT": "8",
                }
            )
        )

        self.assertFalse(config.api.auth_enabled)
        self.assertEqual(config.api.access_token, "test-access-token")
        self.assertTrue(config.api.docs_enabled)
        self.assertTrue(config.api.openapi_enabled)
        self.assertTrue(config.api.docs_public)
        self.assertTrue(config.api.openapi_public)
        self.assertEqual(config.api.max_request_body_bytes, 32768)
        self.assertEqual(config.api.max_concurrent_answers, 3)
        self.assertEqual(config.api.answer_acquire_timeout_seconds, 0.5)
        self.assertEqual(config.api.stream_executor_max_workers, 8)
        self.assertEqual(config.api.stream_queue_max_size, 128)
        self.assertEqual(config.api.build_job_retention_limit, 12)
        self.assertEqual(config.api.build_job_list_default_limit, 4)
        self.assertEqual(config.api.build_job_list_max_limit, 8)

    def test_api_settings_default_answer_concurrency_limit_is_nonzero(self) -> None:
        config = load_config(source=EnvConfigSource(environ={}))

        self.assertGreaterEqual(config.api.max_concurrent_answers, 1)

    def test_api_settings_reject_zero_answer_concurrency_limit(self) -> None:
        with self.assertRaises(ConfigurationError):
            load_config(
                source=EnvConfigSource(
                    environ={
                        "API_MAX_CONCURRENT_ANSWERS": "0",
                    }
                )
            )

    def test_api_settings_reject_build_job_default_limit_above_max_limit(self) -> None:
        with self.assertRaises(ConfigurationError):
            load_config(
                source=EnvConfigSource(
                    environ={
                        "API_BUILD_JOB_LIST_DEFAULT_LIMIT": "9",
                        "API_BUILD_JOB_LIST_MAX_LIMIT": "8",
                    }
                )
            )

    def test_nested_config_serialization_masks_all_credentials(self) -> None:
        config = load_config(
            source=EnvConfigSource(
                environ={
                    "DASHSCOPE_API_KEY": "model-secret",
                    "NEO4J_PASSWORD": "graph-secret",
                    "API_ACCESS_TOKEN": "api-secret-value",
                    "QUERY_TRACE_FINGERPRINT_SALT": "trace-secret",
                }
            )
        )

        payload = config.to_dict()

        self.assertEqual(payload["models"]["api_key"], "***")
        self.assertEqual(payload["storage"]["neo4j_password"], "***")
        self.assertEqual(payload["api"]["access_token"], "***")
        self.assertEqual(payload["observability"]["query_trace_fingerprint_salt"], "***")

    def test_invalid_environment_int_reports_variable_and_field_path(self) -> None:
        with self.assertRaises(ConfigurationError) as context:
            load_config(source=EnvConfigSource(environ={"TOP_K": "many"}))

        self.assertConfigErrorMentions(
            context.exception,
            "environment",
            "TOP_K",
            "retrieval.top_k",
            "integer",
        )

    def test_invalid_environment_bool_reports_variable_and_field_path(self) -> None:
        with self.assertRaises(ConfigurationError) as context:
            load_config(source=EnvConfigSource(environ={"API_AUTH_ENABLED": "sometimes"}))

        self.assertConfigErrorMentions(
            context.exception,
            "environment",
            "API_AUTH_ENABLED",
            "api.auth_enabled",
            "boolean",
        )

    def test_invalid_environment_json_reports_variable_and_field_path(self) -> None:
        with self.assertRaises(ConfigurationError) as context:
            load_config(
                source=EnvConfigSource(
                    environ={"ENTITY_LINKER_QUERY_TYPE_LABEL_PRIORITIES": "not-json"}
                )
            )

        self.assertConfigErrorMentions(
            context.exception,
            "environment",
            "ENTITY_LINKER_QUERY_TYPE_LABEL_PRIORITIES",
            "graph.entity_linker_query_type_label_priorities",
            "JSON object",
        )

    def test_section_loader_ignores_invalid_environment_values_for_other_sections(self) -> None:
        api_settings = load_api_settings(
            EnvConfigSource(
                environ={
                    "API_AUTH_ENABLED": "false",
                    "TOP_K": "many",
                }
            )
        )

        self.assertFalse(api_settings.auth_enabled)


if __name__ == "__main__":
    unittest.main()
