from __future__ import annotations

import os
import unittest

from rag_modules.configuration.env import EnvConfigSource
from rag_modules.configuration.loader import load_config


class ConfigurationSectionLoaderTests(unittest.TestCase):
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
                    "ENABLE_PARENT_DOC_RETRIEVAL": "false",
                }
            )
        )

        self.assertEqual(config.retrieval.top_k, 9)
        self.assertEqual(config.retrieval.hybrid_default_candidate_multiplier, 4)
        self.assertFalse(config.retrieval.enable_parent_doc_retrieval)

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

    def test_api_settings_respect_environment_overrides(self) -> None:
        config = load_config(
            source=EnvConfigSource(
                environ={
                    "API_AUTH_ENABLED": "false",
                    "API_ACCESS_TOKEN": "test-access-token",
                    "API_MAX_REQUEST_BODY_BYTES": "32768",
                    "API_MAX_CONCURRENT_ANSWERS": "3",
                    "API_ANSWER_ACQUIRE_TIMEOUT_SECONDS": "0.5",
                    "API_STREAM_EXECUTOR_MAX_WORKERS": "8",
                    "API_STREAM_QUEUE_MAX_SIZE": "128",
                }
            )
        )

        self.assertFalse(config.api.auth_enabled)
        self.assertEqual(config.api.access_token, "test-access-token")
        self.assertEqual(config.api.max_request_body_bytes, 32768)
        self.assertEqual(config.api.max_concurrent_answers, 3)
        self.assertEqual(config.api.answer_acquire_timeout_seconds, 0.5)
        self.assertEqual(config.api.stream_executor_max_workers, 8)
        self.assertEqual(config.api.stream_queue_max_size, 128)

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


if __name__ == "__main__":
    unittest.main()
