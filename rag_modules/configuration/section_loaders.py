"""Focused loaders for non-query configuration sections."""

from __future__ import annotations

import os
from typing import Any, Mapping

from ..query_understanding.registry import (
    default_entity_linker_query_type_priorities,
    default_entity_linker_relation_priorities,
)
from .env import EnvConfigSource
from .models import (
    ApiSettings,
    GenerationSettings,
    GraphSettings,
    ModelSettings,
    ObservabilitySettings,
    RetrievalSettings,
    StorageSettings,
)


def _mapping_defaults(defaults: Mapping[str, Any] | None) -> dict[str, Any]:
    return dict(defaults or {})


def load_storage_settings(
    source: EnvConfigSource,
    defaults: Mapping[str, Any] | None = None,
) -> StorageSettings:
    storage_defaults = _mapping_defaults(defaults)
    default_index_cache_dir = str(storage_defaults.get("index_cache_dir", "storage/indexes"))
    index_cache_dir = source.get_str(
        "INDEX_CACHE_DIR",
        default_index_cache_dir,
    )
    default_artifact_manifest_path = str(
        storage_defaults.get(
            "artifact_manifest_path",
            os.path.join(default_index_cache_dir, "artifact_manifest.json"),
        )
    )
    if default_artifact_manifest_path == os.path.join(
        default_index_cache_dir,
        "artifact_manifest.json",
    ):
        default_artifact_manifest_path = os.path.join(index_cache_dir, "artifact_manifest.json")
    artifact_manifest_path = source.get_str(
        "ARTIFACT_MANIFEST_PATH",
        default_artifact_manifest_path,
    )
    default_build_job_store_path = str(
        storage_defaults.get(
            "build_job_store_path",
            os.path.join(os.path.dirname(default_artifact_manifest_path), "build_jobs.json"),
        )
    )
    if default_build_job_store_path == os.path.join(
        os.path.dirname(default_artifact_manifest_path),
        "build_jobs.json",
    ):
        default_build_job_store_path = os.path.join(
            os.path.dirname(artifact_manifest_path),
            "build_jobs.json",
        )
    return StorageSettings(
        neo4j_uri=source.get_str(
            "NEO4J_URI", str(storage_defaults.get("neo4j_uri", "bolt://localhost:7687"))
        ),
        neo4j_user=source.get_str("NEO4J_USER", str(storage_defaults.get("neo4j_user", "neo4j"))),
        neo4j_password=source.get_str(
            "NEO4J_PASSWORD", str(storage_defaults.get("neo4j_password", "password"))
        ),
        neo4j_database=source.get_str(
            "NEO4J_DATABASE", str(storage_defaults.get("neo4j_database", "neo4j"))
        ),
        milvus_host=source.get_str(
            "MILVUS_HOST", str(storage_defaults.get("milvus_host", "localhost"))
        ),
        milvus_port=source.get_int("MILVUS_PORT", int(storage_defaults.get("milvus_port", 19530))),
        milvus_collection_name=source.get_str(
            "MILVUS_COLLECTION_NAME",
            str(storage_defaults.get("milvus_collection_name", "cooking_knowledge")),
        ),
        milvus_dimension=source.get_int(
            "MILVUS_DIMENSION", int(storage_defaults.get("milvus_dimension", 1024))
        ),
        enable_index_cache=source.get_bool(
            "ENABLE_INDEX_CACHE",
            bool(storage_defaults.get("enable_index_cache", True)),
        ),
        index_cache_dir=index_cache_dir,
        artifact_manifest_path=artifact_manifest_path,
        milvus_blue_green_enabled=source.get_bool(
            "MILVUS_BLUE_GREEN_ENABLED",
            bool(storage_defaults.get("milvus_blue_green_enabled", True)),
        ),
        milvus_collection_alias_suffix=source.get_str(
            "MILVUS_COLLECTION_ALIAS_SUFFIX",
            str(storage_defaults.get("milvus_collection_alias_suffix", "__active")),
        ),
        build_job_store_path=source.get_str(
            "BUILD_JOB_STORE_PATH",
            default_build_job_store_path,
        ),
        neo4j_max_connection_pool_size=max(
            1,
            source.get_int(
                "NEO4J_MAX_CONNECTION_POOL_SIZE",
                int(storage_defaults.get("neo4j_max_connection_pool_size", 50)),
            ),
        ),
        neo4j_connection_acquisition_timeout_seconds=source.get_float(
            "NEO4J_CONNECTION_ACQUISITION_TIMEOUT_SECONDS",
            float(
                storage_defaults.get(
                    "neo4j_connection_acquisition_timeout_seconds",
                    30.0,
                )
            ),
        ),
        neo4j_max_connection_lifetime_seconds=source.get_float(
            "NEO4J_MAX_CONNECTION_LIFETIME_SECONDS",
            float(storage_defaults.get("neo4j_max_connection_lifetime_seconds", 3600.0)),
        ),
        neo4j_connection_timeout_seconds=source.get_float(
            "NEO4J_CONNECTION_TIMEOUT_SECONDS",
            float(storage_defaults.get("neo4j_connection_timeout_seconds", 15.0)),
        ),
    )


def load_model_settings(
    source: EnvConfigSource,
    defaults: Mapping[str, Any] | None = None,
) -> ModelSettings:
    model_defaults = _mapping_defaults(defaults)
    api_key = source.get_first("DASHSCOPE_API_KEY", "OPENAI_API_KEY", "MOONSHOT_API_KEY") or str(
        model_defaults.get("api_key", "")
    )
    return ModelSettings(
        api_key=api_key,
        llm_base_url=source.get_str(
            "LLM_BASE_URL",
            str(
                model_defaults.get(
                    "llm_base_url",
                    "https://dashscope.aliyuncs.com/compatible-mode/v1",
                )
            ),
        ),
        embedding_base_url=source.get_str(
            "EMBEDDING_BASE_URL",
            str(
                model_defaults.get(
                    "embedding_base_url",
                    "https://dashscope.aliyuncs.com/api/v1/services/embeddings/multimodal-embedding/multimodal-embedding",
                )
            ),
        ),
        rerank_base_url=source.get_str(
            "RERANK_BASE_URL",
            str(
                model_defaults.get(
                    "rerank_base_url",
                    "https://dashscope.aliyuncs.com/api/v1/services/rerank/text-rerank/text-rerank",
                )
            ),
        ),
        embedding_model=source.get_str(
            "EMBEDDING_MODEL",
            str(model_defaults.get("embedding_model", "qwen3-vl-embedding")),
        ),
        llm_model=source.get_str("LLM_MODEL", str(model_defaults.get("llm_model", "qwen3.7-plus"))),
        rerank_model=source.get_str(
            "RERANK_MODEL",
            str(model_defaults.get("rerank_model", "qwen3-vl-rerank")),
        ),
        embedding_dimension=source.get_int(
            "EMBEDDING_DIMENSION",
            int(model_defaults.get("embedding_dimension", 1024)),
        ),
        embedding_batch_size=source.get_int(
            "EMBEDDING_BATCH_SIZE",
            int(model_defaults.get("embedding_batch_size", 10)),
        ),
        enable_rerank=source.get_bool(
            "ENABLE_RERANK",
            bool(model_defaults.get("enable_rerank", True)),
        ),
        llm_timeout_seconds=source.get_int(
            "LLM_TIMEOUT_SECONDS",
            int(model_defaults.get("llm_timeout_seconds", 20)),
        ),
        embedding_timeout_seconds=source.get_int(
            "EMBEDDING_TIMEOUT_SECONDS",
            int(model_defaults.get("embedding_timeout_seconds", 60)),
        ),
        rerank_timeout_seconds=source.get_int(
            "RERANK_TIMEOUT_SECONDS",
            int(model_defaults.get("rerank_timeout_seconds", 20)),
        ),
        http_pool_connections=max(
            1,
            source.get_int(
                "HTTP_POOL_CONNECTIONS",
                int(model_defaults.get("http_pool_connections", 10)),
            ),
        ),
        http_pool_maxsize=max(
            1,
            source.get_int(
                "HTTP_POOL_MAXSIZE",
                int(model_defaults.get("http_pool_maxsize", 20)),
            ),
        ),
        circuit_breaker_failure_threshold=max(
            1,
            source.get_int(
                "CIRCUIT_BREAKER_FAILURE_THRESHOLD",
                int(model_defaults.get("circuit_breaker_failure_threshold", 5)),
            ),
        ),
        circuit_breaker_recovery_seconds=source.get_float(
            "CIRCUIT_BREAKER_RECOVERY_SECONDS",
            float(model_defaults.get("circuit_breaker_recovery_seconds", 30.0)),
        ),
        llm_input_cost_per_million_tokens=max(
            0.0,
            source.get_float(
                "LLM_INPUT_COST_PER_MILLION_TOKENS",
                float(
                    model_defaults.get(
                        "llm_input_cost_per_million_tokens",
                        0.0,
                    )
                ),
            ),
        ),
        llm_output_cost_per_million_tokens=max(
            0.0,
            source.get_float(
                "LLM_OUTPUT_COST_PER_MILLION_TOKENS",
                float(
                    model_defaults.get(
                        "llm_output_cost_per_million_tokens",
                        0.0,
                    )
                ),
            ),
        ),
    )


def load_retrieval_settings(
    source: EnvConfigSource,
    defaults: Mapping[str, Any] | None = None,
) -> RetrievalSettings:
    retrieval_defaults = _mapping_defaults(defaults)
    candidate_source_degradation_strategy = source.get_str(
        "RETRIEVAL_CANDIDATE_SOURCE_DEGRADATION_STRATEGY",
        str(retrieval_defaults.get("candidate_source_degradation_strategy", "continue")),
    ).strip().lower()
    return RetrievalSettings(
        top_k=source.get_int("TOP_K", int(retrieval_defaults.get("top_k", 5))),
        vector_search_ef=source.get_int(
            "VECTOR_SEARCH_EF",
            int(retrieval_defaults.get("vector_search_ef", 128)),
        ),
        vector_search_max_k=source.get_int(
            "VECTOR_SEARCH_MAX_K",
            int(retrieval_defaults.get("vector_search_max_k", 50)),
        ),
        rrf_k=source.get_int("RRF_K", int(retrieval_defaults.get("rrf_k", 60))),
        hybrid_default_candidate_multiplier=source.get_int(
            "HYBRID_DEFAULT_CANDIDATE_MULTIPLIER",
            int(retrieval_defaults.get("hybrid_default_candidate_multiplier", 2)),
        ),
        hybrid_default_candidate_min_candidates=source.get_int(
            "HYBRID_DEFAULT_CANDIDATE_MIN_CANDIDATES",
            int(retrieval_defaults.get("hybrid_default_candidate_min_candidates", 10)),
        ),
        hybrid_constraint_candidate_multiplier=source.get_int(
            "HYBRID_CONSTRAINT_CANDIDATE_MULTIPLIER",
            int(retrieval_defaults.get("hybrid_constraint_candidate_multiplier", 6)),
        ),
        hybrid_constraint_candidate_min_candidates=source.get_int(
            "HYBRID_CONSTRAINT_CANDIDATE_MIN_CANDIDATES",
            int(retrieval_defaults.get("hybrid_constraint_candidate_min_candidates", 30)),
        ),
        router_combined_candidate_multiplier=source.get_int(
            "ROUTER_COMBINED_CANDIDATE_MULTIPLIER",
            int(retrieval_defaults.get("router_combined_candidate_multiplier", 6)),
        ),
        router_combined_candidate_min_candidates=source.get_int(
            "ROUTER_COMBINED_CANDIDATE_MIN_CANDIDATES",
            int(retrieval_defaults.get("router_combined_candidate_min_candidates", 30)),
        ),
        router_graph_supplement_candidate_multiplier=source.get_int(
            "ROUTER_GRAPH_SUPPLEMENT_CANDIDATE_MULTIPLIER",
            int(retrieval_defaults.get("router_graph_supplement_candidate_multiplier", 2)),
        ),
        router_graph_supplement_candidate_min_candidates=source.get_int(
            "ROUTER_GRAPH_SUPPLEMENT_CANDIDATE_MIN_CANDIDATES",
            int(retrieval_defaults.get("router_graph_supplement_candidate_min_candidates", 10)),
        ),
        retrieval_preserve_graph_evidence=source.get_bool(
            "RETRIEVAL_PRESERVE_GRAPH_EVIDENCE",
            bool(retrieval_defaults.get("retrieval_preserve_graph_evidence", True)),
        ),
        enable_parent_doc_retrieval=source.get_bool(
            "ENABLE_PARENT_DOC_RETRIEVAL",
            bool(retrieval_defaults.get("enable_parent_doc_retrieval", True)),
        ),
        parent_doc_top_n=source.get_int(
            "PARENT_DOC_TOP_N",
            int(retrieval_defaults.get("parent_doc_top_n", 3)),
        ),
        parent_doc_max_chars=source.get_int(
            "PARENT_DOC_MAX_CHARS",
            int(retrieval_defaults.get("parent_doc_max_chars", 4000)),
        ),
        candidate_source_failure_threshold=max(
            1,
            source.get_int(
                "RETRIEVAL_CANDIDATE_SOURCE_FAILURE_THRESHOLD",
                int(retrieval_defaults.get("candidate_source_failure_threshold", 1)),
            ),
        ),
        candidate_source_recovery_seconds=max(
            0.1,
            source.get_float(
                "RETRIEVAL_CANDIDATE_SOURCE_RECOVERY_SECONDS",
                float(retrieval_defaults.get("candidate_source_recovery_seconds", 30.0)),
            ),
        ),
        candidate_source_degradation_strategy=(
            candidate_source_degradation_strategy or "continue"
        ),
    )


def load_generation_settings(
    source: EnvConfigSource,
    defaults: Mapping[str, Any] | None = None,
) -> GenerationSettings:
    generation_defaults = _mapping_defaults(defaults)
    return GenerationSettings(
        temperature=source.get_float(
            "TEMPERATURE", float(generation_defaults.get("temperature", 0.1))
        ),
        max_tokens=source.get_int("MAX_TOKENS", int(generation_defaults.get("max_tokens", 2048))),
        generation_timeout_seconds=source.get_int(
            "GENERATION_TIMEOUT_SECONDS",
            int(generation_defaults.get("generation_timeout_seconds", 25)),
        ),
        generation_stream_timeout_seconds=source.get_int(
            "GENERATION_STREAM_TIMEOUT_SECONDS",
            int(generation_defaults.get("generation_stream_timeout_seconds", 25)),
        ),
        generation_latency_budget_seconds=source.get_int(
            "GENERATION_LATENCY_BUDGET_SECONDS",
            int(generation_defaults.get("generation_latency_budget_seconds", 24)),
        ),
        generation_plan_max_tokens=source.get_int(
            "GENERATION_PLAN_MAX_TOKENS",
            int(generation_defaults.get("generation_plan_max_tokens", 600)),
        ),
        generation_compose_max_tokens=source.get_int(
            "GENERATION_COMPOSE_MAX_TOKENS",
            int(generation_defaults.get("generation_compose_max_tokens", 1100)),
        ),
        generation_direct_max_tokens=source.get_int(
            "GENERATION_DIRECT_MAX_TOKENS",
            int(generation_defaults.get("generation_direct_max_tokens", 700)),
        ),
        generation_plan_temperature=source.get_float(
            "GENERATION_PLAN_TEMPERATURE",
            float(generation_defaults.get("generation_plan_temperature", 0.0)),
        ),
        generation_planner_mode=source.get_str(
            "GENERATION_PLANNER_MODE",
            str(generation_defaults.get("generation_planner_mode", "rule")),
        ),
        generation_max_retries=source.get_int(
            "GENERATION_MAX_RETRIES",
            int(generation_defaults.get("generation_max_retries", 1)),
        ),
        generation_request_retries=source.get_int(
            "GENERATION_REQUEST_RETRIES",
            int(generation_defaults.get("generation_request_retries", 1)),
        ),
        generation_stream_retries=source.get_int(
            "GENERATION_STREAM_RETRIES",
            int(generation_defaults.get("generation_stream_retries", 1)),
        ),
        generation_evidence_max_chars=source.get_int(
            "GENERATION_EVIDENCE_MAX_CHARS",
            int(generation_defaults.get("generation_evidence_max_chars", 700)),
        ),
        generation_enable_two_stage=source.get_bool(
            "GENERATION_ENABLE_TWO_STAGE",
            bool(generation_defaults.get("generation_enable_two_stage", True)),
        ),
        generation_two_stage_complexity_threshold=source.get_float(
            "GENERATION_TWO_STAGE_COMPLEXITY_THRESHOLD",
            float(generation_defaults.get("generation_two_stage_complexity_threshold", 0.68)),
        ),
        generation_two_stage_relationship_threshold=source.get_float(
            "GENERATION_TWO_STAGE_RELATIONSHIP_THRESHOLD",
            float(generation_defaults.get("generation_two_stage_relationship_threshold", 0.58)),
        ),
        generation_direct_max_evidence_items=source.get_int(
            "GENERATION_DIRECT_MAX_EVIDENCE_ITEMS",
            int(generation_defaults.get("generation_direct_max_evidence_items", 2)),
        ),
        generation_two_stage_max_evidence_items=source.get_int(
            "GENERATION_TWO_STAGE_MAX_EVIDENCE_ITEMS",
            int(generation_defaults.get("generation_two_stage_max_evidence_items", 3)),
        ),
        generation_plan_max_evidence_items=source.get_int(
            "GENERATION_PLAN_MAX_EVIDENCE_ITEMS",
            int(generation_defaults.get("generation_plan_max_evidence_items", 2)),
        ),
        generation_max_graph_paths_per_item=source.get_int(
            "GENERATION_MAX_GRAPH_PATHS_PER_ITEM",
            int(generation_defaults.get("generation_max_graph_paths_per_item", 1)),
        ),
        generation_max_evidence_units_per_item=source.get_int(
            "GENERATION_MAX_EVIDENCE_UNITS_PER_ITEM",
            int(generation_defaults.get("generation_max_evidence_units_per_item", 4)),
        ),
        generation_include_document_evidence=source.get_bool(
            "GENERATION_INCLUDE_DOCUMENT_EVIDENCE",
            bool(generation_defaults.get("generation_include_document_evidence", False)),
        ),
        generation_compose_include_content=source.get_bool(
            "GENERATION_COMPOSE_INCLUDE_CONTENT",
            bool(generation_defaults.get("generation_compose_include_content", False)),
        ),
        generation_fallback_on_timeout=source.get_bool(
            "GENERATION_FALLBACK_ON_TIMEOUT",
            bool(generation_defaults.get("generation_fallback_on_timeout", False)),
        ),
    )


def load_graph_settings(
    source: EnvConfigSource,
    defaults: Mapping[str, Any] | None = None,
) -> GraphSettings:
    graph_defaults = _mapping_defaults(defaults)
    return GraphSettings(
        enable_semantic_graph_schema=source.get_bool(
            "ENABLE_SEMANTIC_GRAPH_SCHEMA",
            bool(graph_defaults.get("enable_semantic_graph_schema", True)),
        ),
        chunk_size=source.get_int("CHUNK_SIZE", int(graph_defaults.get("chunk_size", 500))),
        chunk_overlap=source.get_int(
            "CHUNK_OVERLAP",
            int(graph_defaults.get("chunk_overlap", 50)),
        ),
        max_graph_depth=source.get_int(
            "MAX_GRAPH_DEPTH",
            int(graph_defaults.get("max_graph_depth", 2)),
        ),
        graph_rank_base_weight=source.get_float(
            "GRAPH_RANK_BASE_WEIGHT",
            float(graph_defaults.get("graph_rank_base_weight", 1.0)),
        ),
        graph_rank_semantic_relation_weight=source.get_float(
            "GRAPH_RANK_SEMANTIC_RELATION_WEIGHT",
            float(graph_defaults.get("graph_rank_semantic_relation_weight", 0.08)),
        ),
        graph_rank_evidence_unit_weight=source.get_float(
            "GRAPH_RANK_EVIDENCE_UNIT_WEIGHT",
            float(graph_defaults.get("graph_rank_evidence_unit_weight", 0.03)),
        ),
        graph_rank_relationship_weight=source.get_float(
            "GRAPH_RANK_RELATIONSHIP_WEIGHT",
            float(graph_defaults.get("graph_rank_relationship_weight", 0.01)),
        ),
        graph_rank_recipe_presence_weight=source.get_float(
            "GRAPH_RANK_RECIPE_PRESENCE_WEIGHT",
            float(graph_defaults.get("graph_rank_recipe_presence_weight", 0.1)),
        ),
        graph_rank_query_overlap_weight=source.get_float(
            "GRAPH_RANK_QUERY_OVERLAP_WEIGHT",
            float(graph_defaults.get("graph_rank_query_overlap_weight", 0.02)),
        ),
        entity_linker_limit_per_entity=source.get_int(
            "ENTITY_LINKER_LIMIT_PER_ENTITY",
            int(graph_defaults.get("entity_linker_limit_per_entity", 4)),
        ),
        entity_linker_min_confidence=source.get_float(
            "ENTITY_LINKER_MIN_CONFIDENCE",
            float(graph_defaults.get("entity_linker_min_confidence", 0.45)),
        ),
        entity_linker_max_same_name_candidates=source.get_int(
            "ENTITY_LINKER_MAX_SAME_NAME_CANDIDATES",
            int(graph_defaults.get("entity_linker_max_same_name_candidates", 2)),
        ),
        entity_linker_query_type_label_priorities=source.get_json_dict(
            "ENTITY_LINKER_QUERY_TYPE_LABEL_PRIORITIES",
            dict(
                graph_defaults.get(
                    "entity_linker_query_type_label_priorities",
                    default_entity_linker_query_type_priorities(),
                )
            ),
        ),
        entity_linker_relation_label_priorities=source.get_json_dict(
            "ENTITY_LINKER_RELATION_LABEL_PRIORITIES",
            dict(
                graph_defaults.get(
                    "entity_linker_relation_label_priorities",
                    default_entity_linker_relation_priorities(),
                )
            ),
        ),
    )


def load_observability_settings(
    source: EnvConfigSource,
    defaults: Mapping[str, Any] | None = None,
) -> ObservabilitySettings:
    observability_defaults = _mapping_defaults(defaults)
    return ObservabilitySettings(
        enable_query_tracing=source.get_bool(
            "ENABLE_QUERY_TRACING",
            bool(observability_defaults.get("enable_query_tracing", True)),
        ),
        query_trace_path=source.get_str(
            "QUERY_TRACE_PATH",
            str(observability_defaults.get("query_trace_path", "storage/traces/query_trace.jsonl")),
        ),
        query_trace_async_enabled=source.get_bool(
            "QUERY_TRACE_ASYNC_ENABLED",
            bool(observability_defaults.get("query_trace_async_enabled", True)),
        ),
        query_trace_max_queue_size=source.get_int(
            "QUERY_TRACE_MAX_QUEUE_SIZE",
            int(observability_defaults.get("query_trace_max_queue_size", 256)),
        ),
        query_trace_fingerprint_salt=source.get_str(
            "QUERY_TRACE_FINGERPRINT_SALT",
            str(observability_defaults.get("query_trace_fingerprint_salt", "")),
        ),
        enable_opentelemetry=source.get_bool(
            "ENABLE_OPENTELEMETRY",
            bool(observability_defaults.get("enable_opentelemetry", False)),
        ),
        otel_service_name=source.get_str(
            "OTEL_SERVICE_NAME",
            str(observability_defaults.get("otel_service_name", "graphrag")),
        ),
        otel_exporter_otlp_endpoint=source.get_str(
            "OTEL_EXPORTER_OTLP_ENDPOINT",
            str(
                observability_defaults.get(
                    "otel_exporter_otlp_endpoint",
                    "",
                )
            ),
        ),
        otel_trace_sample_ratio=min(
            1.0,
            max(
                0.0,
                source.get_float(
                    "OTEL_TRACE_SAMPLE_RATIO",
                    float(
                        observability_defaults.get(
                            "otel_trace_sample_ratio",
                            1.0,
                        )
                    ),
                ),
            ),
        ),
        enable_prometheus=source.get_bool(
            "ENABLE_PROMETHEUS",
            bool(observability_defaults.get("enable_prometheus", True)),
        ),
    )


def load_api_settings(
    source: EnvConfigSource,
    defaults: Mapping[str, Any] | None = None,
) -> ApiSettings:
    api_defaults = _mapping_defaults(defaults)
    access_token = source.get_first("API_ACCESS_TOKEN", "GRAPH_RAG_API_TOKEN") or str(
        api_defaults.get("access_token", "")
    )
    return ApiSettings(
        auth_enabled=source.get_bool(
            "API_AUTH_ENABLED",
            bool(api_defaults.get("auth_enabled", True)),
        ),
        access_token=access_token,
        max_request_body_bytes=max(
            1024,
            source.get_int(
                "API_MAX_REQUEST_BODY_BYTES",
                int(api_defaults.get("max_request_body_bytes", 16 * 1024)),
            ),
        ),
        max_concurrent_answers=max(
            0,
            source.get_int(
                "API_MAX_CONCURRENT_ANSWERS",
                int(api_defaults.get("max_concurrent_answers", 0)),
            ),
        ),
        answer_acquire_timeout_seconds=max(
            0.0,
            source.get_float(
                "API_ANSWER_ACQUIRE_TIMEOUT_SECONDS",
                float(api_defaults.get("answer_acquire_timeout_seconds", 0.25)),
            ),
        ),
        stream_executor_max_workers=max(
            1,
            source.get_int(
                "API_STREAM_EXECUTOR_MAX_WORKERS",
                int(api_defaults.get("stream_executor_max_workers", 4)),
            ),
        ),
        stream_queue_max_size=max(
            1,
            source.get_int(
                "API_STREAM_QUEUE_MAX_SIZE",
                int(api_defaults.get("stream_queue_max_size", 64)),
            ),
        ),
        serving_hot_refresh_enabled=source.get_bool(
            "SERVING_HOT_REFRESH_ENABLED",
            bool(api_defaults.get("serving_hot_refresh_enabled", True)),
        ),
        serving_hot_refresh_interval_seconds=max(
            0.1,
            source.get_float(
                "SERVING_HOT_REFRESH_INTERVAL_SECONDS",
                float(api_defaults.get("serving_hot_refresh_interval_seconds", 2.0)),
            ),
        ),
    )


__all__ = [
    "load_api_settings",
    "load_model_settings",
    "load_retrieval_settings",
    "load_generation_settings",
    "load_graph_settings",
    "load_observability_settings",
    "load_storage_settings",
]
