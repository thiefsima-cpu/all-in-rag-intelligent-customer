"""Canonical environment override schema."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

EnvValueKind = Literal["str", "int", "float", "bool", "json_dict"]


@dataclass(frozen=True, slots=True)
class EnvFieldSpec:
    """Schema destination for one environment override field."""

    names: tuple[str, ...]
    path: tuple[str, ...]
    value_kind: EnvValueKind

    @property
    def dotted_path(self) -> str:
        return ".".join(self.path)


def spec(
    names: str | tuple[str, ...], path: tuple[str, ...], value_kind: EnvValueKind
) -> EnvFieldSpec:
    normalized_names = (names,) if isinstance(names, str) else names
    return EnvFieldSpec(names=normalized_names, path=path, value_kind=value_kind)


def _specs(
    *rows: tuple[str | tuple[str, ...], tuple[str, ...], EnvValueKind],
) -> tuple[EnvFieldSpec, ...]:
    return tuple(spec(*row) for row in rows)


_API_ENV_FIELD_SPECS = _specs(
    ("API_ACCESS_TOKEN", ("api", "access_token"), "str"),
    ("API_AUTH_ENABLED", ("api", "auth_enabled"), "bool"),
    ("API_DOCS_ENABLED", ("api", "docs_enabled"), "bool"),
    ("API_OPENAPI_ENABLED", ("api", "openapi_enabled"), "bool"),
    ("API_DOCS_PUBLIC", ("api", "docs_public"), "bool"),
    ("API_OPENAPI_PUBLIC", ("api", "openapi_public"), "bool"),
    ("API_MAX_REQUEST_BODY_BYTES", ("api", "max_request_body_bytes"), "int"),
    ("API_MAX_CONCURRENT_ANSWERS", ("api", "max_concurrent_answers"), "int"),
    ("API_ANSWER_ACQUIRE_TIMEOUT_SECONDS", ("api", "answer_acquire_timeout_seconds"), "float"),
    ("API_STREAM_EXECUTOR_MAX_WORKERS", ("api", "stream_executor_max_workers"), "int"),
    ("API_STREAM_EXECUTOR_MAX_OUTSTANDING", ("api", "stream_executor_max_outstanding"), "int"),
    ("API_STREAM_EVENT_QUEUE_MAX_SIZE", ("api", "stream_event_queue_max_size"), "int"),
    ("API_BUILD_JOB_RUNNER_BACKEND", ("api", "build_job_runner_backend"), "str"),
    ("API_BUILD_JOB_RUNNER_MAX_WORKERS", ("api", "build_job_runner_max_workers"), "int"),
    (
        "API_BUILD_JOB_WORKER_POLL_INTERVAL_SECONDS",
        ("api", "build_job_worker_poll_interval_seconds"),
        "float",
    ),
    ("API_BUILD_JOB_RETENTION_LIMIT", ("api", "build_job_retention_limit"), "int"),
    ("API_BUILD_JOB_LIST_DEFAULT_LIMIT", ("api", "build_job_list_default_limit"), "int"),
    ("API_BUILD_JOB_LIST_MAX_LIMIT", ("api", "build_job_list_max_limit"), "int"),
    ("API_BUILD_JOB_LEASE_SECONDS", ("api", "build_job_lease_seconds"), "float"),
    ("API_BUILD_JOB_HEARTBEAT_SECONDS", ("api", "build_job_heartbeat_seconds"), "float"),
    ("API_BUILD_JOB_REPOSITORY_BACKEND", ("api", "build_job_repository_backend"), "str"),
    ("API_BUILD_JOB_AUDIT_RETENTION_DAYS", ("api", "build_job_audit_retention_days"), "int"),
    (
        "API_BUILD_JOB_POSTGRES_POOL_MIN_SIZE",
        ("api", "build_job_postgres_pool_min_size"),
        "int",
    ),
    (
        "API_BUILD_JOB_POSTGRES_POOL_MAX_SIZE",
        ("api", "build_job_postgres_pool_max_size"),
        "int",
    ),
    (
        "API_BUILD_JOB_POSTGRES_POOL_TIMEOUT_SECONDS",
        ("api", "build_job_postgres_pool_timeout_seconds"),
        "float",
    ),
    ("SERVING_HOT_REFRESH_ENABLED", ("api", "serving_hot_refresh_enabled"), "bool"),
    (
        "SERVING_HOT_REFRESH_INTERVAL_SECONDS",
        ("api", "serving_hot_refresh_interval_seconds"),
        "float",
    ),
)
_DOMAIN_ENV_FIELD_SPECS = _specs((("GRAPH_RAG_DOMAIN", "RAG_DOMAIN"), ("domain", "name"), "str"))
_GENERATION_ENV_FIELD_SPECS = _specs(
    ("TEMPERATURE", ("generation", "temperature"), "float"),
    ("MAX_TOKENS", ("generation", "max_tokens"), "int"),
    ("GENERATION_TIMEOUT_SECONDS", ("generation", "generation_timeout_seconds"), "int"),
    (
        "GENERATION_STREAM_TIMEOUT_SECONDS",
        ("generation", "generation_stream_timeout_seconds"),
        "int",
    ),
    (
        "GENERATION_LATENCY_BUDGET_SECONDS",
        ("generation", "generation_latency_budget_seconds"),
        "int",
    ),
    ("GENERATION_PLAN_MAX_TOKENS", ("generation", "generation_plan_max_tokens"), "int"),
    ("GENERATION_COMPOSE_MAX_TOKENS", ("generation", "generation_compose_max_tokens"), "int"),
    ("GENERATION_DIRECT_MAX_TOKENS", ("generation", "generation_direct_max_tokens"), "int"),
    ("GENERATION_PLAN_TEMPERATURE", ("generation", "generation_plan_temperature"), "float"),
    ("GENERATION_PLANNER_MODE", ("generation", "generation_planner_mode"), "str"),
    ("GENERATION_MAX_RETRIES", ("generation", "generation_max_retries"), "int"),
    ("GENERATION_REQUEST_RETRIES", ("generation", "generation_request_retries"), "int"),
    ("GENERATION_STREAM_RETRIES", ("generation", "generation_stream_retries"), "int"),
    ("GENERATION_EVIDENCE_MAX_CHARS", ("generation", "generation_evidence_max_chars"), "int"),
    ("GENERATION_ENABLE_TWO_STAGE", ("generation", "generation_enable_two_stage"), "bool"),
    (
        "GENERATION_TWO_STAGE_COMPLEXITY_THRESHOLD",
        ("generation", "generation_two_stage_complexity_threshold"),
        "float",
    ),
    (
        "GENERATION_TWO_STAGE_RELATIONSHIP_THRESHOLD",
        ("generation", "generation_two_stage_relationship_threshold"),
        "float",
    ),
    (
        "GENERATION_DIRECT_MAX_EVIDENCE_ITEMS",
        ("generation", "generation_direct_max_evidence_items"),
        "int",
    ),
    (
        "GENERATION_TWO_STAGE_MAX_EVIDENCE_ITEMS",
        ("generation", "generation_two_stage_max_evidence_items"),
        "int",
    ),
    (
        "GENERATION_PLAN_MAX_EVIDENCE_ITEMS",
        ("generation", "generation_plan_max_evidence_items"),
        "int",
    ),
    (
        "GENERATION_MAX_GRAPH_PATHS_PER_ITEM",
        ("generation", "generation_max_graph_paths_per_item"),
        "int",
    ),
    (
        "GENERATION_MAX_EVIDENCE_UNITS_PER_ITEM",
        ("generation", "generation_max_evidence_units_per_item"),
        "int",
    ),
    (
        "GENERATION_INCLUDE_DOCUMENT_EVIDENCE",
        ("generation", "generation_include_document_evidence"),
        "bool",
    ),
    (
        "GENERATION_COMPOSE_INCLUDE_CONTENT",
        ("generation", "generation_compose_include_content"),
        "bool",
    ),
    ("GENERATION_FALLBACK_ON_TIMEOUT", ("generation", "generation_fallback_on_timeout"), "bool"),
)
_GRAPH_ENV_FIELD_SPECS = _specs(
    ("ENABLE_SEMANTIC_GRAPH_SCHEMA", ("graph", "enable_semantic_graph_schema"), "bool"),
    ("CHUNK_SIZE", ("graph", "chunk_size"), "int"),
    ("CHUNK_OVERLAP", ("graph", "chunk_overlap"), "int"),
    ("MAX_GRAPH_DEPTH", ("graph", "max_graph_depth"), "int"),
    ("GRAPH_RANK_BASE_WEIGHT", ("graph", "graph_rank_base_weight"), "float"),
    (
        "GRAPH_RANK_SEMANTIC_RELATION_WEIGHT",
        ("graph", "graph_rank_semantic_relation_weight"),
        "float",
    ),
    ("GRAPH_RANK_EVIDENCE_UNIT_WEIGHT", ("graph", "graph_rank_evidence_unit_weight"), "float"),
    ("GRAPH_RANK_RELATIONSHIP_WEIGHT", ("graph", "graph_rank_relationship_weight"), "float"),
    ("GRAPH_RANK_RECIPE_PRESENCE_WEIGHT", ("graph", "graph_rank_recipe_presence_weight"), "float"),
    ("GRAPH_RANK_QUERY_OVERLAP_WEIGHT", ("graph", "graph_rank_query_overlap_weight"), "float"),
    ("ENTITY_LINKER_LIMIT_PER_ENTITY", ("graph", "entity_linker_limit_per_entity"), "int"),
    ("ENTITY_LINKER_MIN_CONFIDENCE", ("graph", "entity_linker_min_confidence"), "float"),
    (
        "ENTITY_LINKER_MAX_SAME_NAME_CANDIDATES",
        ("graph", "entity_linker_max_same_name_candidates"),
        "int",
    ),
    (
        "ENTITY_LINKER_QUERY_TYPE_LABEL_PRIORITIES",
        ("graph", "entity_linker_query_type_label_priorities"),
        "json_dict",
    ),
    (
        "ENTITY_LINKER_RELATION_LABEL_PRIORITIES",
        ("graph", "entity_linker_relation_label_priorities"),
        "json_dict",
    ),
)
_MODEL_ENV_FIELD_SPECS = _specs(
    (("DASHSCOPE_API_KEY", "OPENAI_API_KEY", "MOONSHOT_API_KEY"), ("models", "api_key"), "str"),
    ("LLM_BASE_URL", ("models", "llm_base_url"), "str"),
    ("EMBEDDING_BASE_URL", ("models", "embedding_base_url"), "str"),
    ("RERANK_BASE_URL", ("models", "rerank_base_url"), "str"),
    ("EMBEDDING_MODEL", ("models", "embedding_model"), "str"),
    ("LLM_MODEL", ("models", "llm_model"), "str"),
    ("LLM_ENABLE_THINKING", ("models", "llm_enable_thinking"), "bool"),
    ("RERANK_MODEL", ("models", "rerank_model"), "str"),
    ("EMBEDDING_DIMENSION", ("models", "embedding_dimension"), "int"),
    ("EMBEDDING_BATCH_SIZE", ("models", "embedding_batch_size"), "int"),
    ("ENABLE_RERANK", ("models", "enable_rerank"), "bool"),
    ("LLM_TIMEOUT_SECONDS", ("models", "llm_timeout_seconds"), "int"),
    ("EMBEDDING_TIMEOUT_SECONDS", ("models", "embedding_timeout_seconds"), "int"),
    ("RERANK_TIMEOUT_SECONDS", ("models", "rerank_timeout_seconds"), "int"),
    ("HTTP_POOL_CONNECTIONS", ("models", "http_pool_connections"), "int"),
    ("HTTP_POOL_MAXSIZE", ("models", "http_pool_maxsize"), "int"),
    ("CIRCUIT_BREAKER_FAILURE_THRESHOLD", ("models", "circuit_breaker_failure_threshold"), "int"),
    ("CIRCUIT_BREAKER_RECOVERY_SECONDS", ("models", "circuit_breaker_recovery_seconds"), "float"),
    ("LLM_INPUT_COST_PER_MILLION_TOKENS", ("models", "llm_input_cost_per_million_tokens"), "float"),
    (
        "LLM_OUTPUT_COST_PER_MILLION_TOKENS",
        ("models", "llm_output_cost_per_million_tokens"),
        "float",
    ),
)
_OBSERVABILITY_ENV_FIELD_SPECS = _specs(
    ("ENABLE_QUERY_TRACING", ("observability", "enable_query_tracing"), "bool"),
    ("QUERY_TRACE_PATH", ("observability", "query_trace_path"), "str"),
    ("QUERY_TRACE_ASYNC_ENABLED", ("observability", "query_trace_async_enabled"), "bool"),
    ("QUERY_TRACE_MAX_QUEUE_SIZE", ("observability", "query_trace_max_queue_size"), "int"),
    ("QUERY_TRACE_FINGERPRINT_SALT", ("observability", "query_trace_fingerprint_salt"), "str"),
    ("ENABLE_OPENTELEMETRY", ("observability", "enable_opentelemetry"), "bool"),
    ("OTEL_SERVICE_NAME", ("observability", "otel_service_name"), "str"),
    ("OTEL_EXPORTER_OTLP_ENDPOINT", ("observability", "otel_exporter_otlp_endpoint"), "str"),
    ("OTEL_TRACE_SAMPLE_RATIO", ("observability", "otel_trace_sample_ratio"), "float"),
    ("ENABLE_PROMETHEUS", ("observability", "enable_prometheus"), "bool"),
    ("PROMETHEUS_METRICS_PUBLIC", ("observability", "prometheus_public"), "bool"),
)
_QUERY_UNDERSTANDING_ENV_FIELD_SPECS = _specs(
    ("QUERY_POLICY_BUNDLE", ("query_understanding", "policy", "bundle"), "str"),
    ("QUERY_POLICY_BUNDLE_PATH", ("query_understanding", "policy", "bundle_path"), "str"),
    ("QUERY_PLAN_CACHE_SIZE", ("query_understanding", "planner", "cache_size"), "int"),
    ("FAST_RULE_QUERY_PLANNING", ("query_understanding", "planner", "fast_rule_planning"), "bool"),
    (
        "QUERY_PLANNER_LLM_TEMPERATURE",
        ("query_understanding", "planner", "llm_temperature"),
        "float",
    ),
    ("QUERY_PLANNER_LLM_MAX_TOKENS", ("query_understanding", "planner", "llm_max_tokens"), "int"),
    (
        "QUERY_SEMANTIC_RELATION_INTENSITY_REFERENCE_RATIO",
        ("query_understanding", "semantics", "scoring", "relation_intensity_reference_ratio"),
        "float",
    ),
    (
        "QUERY_SEMANTIC_COMPLEXITY_RELATION_HIT_WEIGHT",
        ("query_understanding", "semantics", "scoring", "complexity_relation_hit_weight"),
        "float",
    ),
    (
        "QUERY_SEMANTIC_COMPLEXITY_CONSTRAINT_HIT_WEIGHT",
        ("query_understanding", "semantics", "scoring", "complexity_constraint_hit_weight"),
        "float",
    ),
    (
        "QUERY_SEMANTIC_COMPLEXITY_STRUCTURAL_HIT_WEIGHT",
        ("query_understanding", "semantics", "scoring", "complexity_structural_hit_weight"),
        "float",
    ),
    (
        "QUERY_SEMANTIC_COMPLEXITY_LENGTH_WEIGHT",
        ("query_understanding", "semantics", "scoring", "complexity_length_weight"),
        "float",
    ),
    (
        "QUERY_SEMANTIC_COMPLEXITY_LENGTH_NORM_CHARS",
        ("query_understanding", "semantics", "scoring", "complexity_length_norm_chars"),
        "int",
    ),
    (
        "QUERY_SEMANTIC_REASONING_COMPLEXITY_THRESHOLD",
        ("query_understanding", "semantics", "scoring", "reasoning_complexity_threshold"),
        "float",
    ),
    (
        "QUERY_SEMANTIC_REASONING_RELATIONSHIP_THRESHOLD",
        ("query_understanding", "semantics", "scoring", "reasoning_relationship_threshold"),
        "float",
    ),
    (
        "QUERY_SEMANTIC_RELATION_HIT_INTENSITY_BOOST_BASE",
        ("query_understanding", "semantics", "scoring", "relation_hit_intensity_boost_base"),
        "float",
    ),
    (
        "QUERY_SEMANTIC_RELATION_HIT_INTENSITY_BOOST_STEP",
        ("query_understanding", "semantics", "scoring", "relation_hit_intensity_boost_step"),
        "float",
    ),
    (
        "QUERY_SEMANTIC_RELATION_HIT_COMPLEXITY_BOOST_BASE",
        ("query_understanding", "semantics", "scoring", "relation_hit_complexity_boost_base"),
        "float",
    ),
    (
        "QUERY_SEMANTIC_RELATION_HIT_COMPLEXITY_BOOST_STEP",
        ("query_understanding", "semantics", "scoring", "relation_hit_complexity_boost_step"),
        "float",
    ),
    (
        "QUERY_SEMANTIC_SOURCE_ENTITY_LIMIT",
        ("query_understanding", "semantics", "extraction", "source_entity_limit"),
        "int",
    ),
    (
        "QUERY_SEMANTIC_ENTITY_KEYWORD_LIMIT",
        ("query_understanding", "semantics", "extraction", "entity_keyword_limit"),
        "int",
    ),
    (
        "QUERY_SEMANTIC_PROFILE_ENTITY_KEYWORD_LIMIT",
        ("query_understanding", "semantics", "extraction", "semantic_profile_entity_keyword_limit"),
        "int",
    ),
    (
        "QUERY_SEMANTIC_TOPIC_KEYWORD_LIMIT",
        ("query_understanding", "semantics", "extraction", "topic_keyword_limit"),
        "int",
    ),
    (
        "QUERY_SEMANTIC_PROFILE_TOPIC_KEYWORD_START",
        ("query_understanding", "semantics", "extraction", "semantic_profile_topic_keyword_start"),
        "int",
    ),
    (
        "QUERY_SEMANTIC_PROFILE_TOPIC_KEYWORD_LIMIT",
        ("query_understanding", "semantics", "extraction", "semantic_profile_topic_keyword_limit"),
        "int",
    ),
    (
        "QUERY_SEMANTIC_TARGET_ENTITY_LIMIT",
        ("query_understanding", "semantics", "extraction", "target_entity_limit"),
        "int",
    ),
    (
        "QUERY_SEMANTIC_HIGH_RELATIONSHIP_ROUTING_THRESHOLD",
        ("query_understanding", "semantics", "routing", "high_relationship_routing_threshold"),
        "float",
    ),
    (
        "QUERY_SEMANTIC_MULTI_HOP_HINT_ENTITY_COUNT",
        ("query_understanding", "semantics", "routing", "multi_hop_hint_entity_count"),
        "int",
    ),
    (
        "QUERY_SEMANTIC_MULTI_HOP_HINT_RELATIONSHIP_THRESHOLD",
        ("query_understanding", "semantics", "routing", "multi_hop_hint_relationship_threshold"),
        "float",
    ),
    (
        "QUERY_SEMANTIC_COMBINED_STRATEGY_RELATIONSHIP_THRESHOLD",
        ("query_understanding", "semantics", "routing", "combined_strategy_relationship_threshold"),
        "float",
    ),
    (
        "QUERY_SEMANTIC_COMBINED_STRATEGY_COMPLEXITY_THRESHOLD",
        ("query_understanding", "semantics", "routing", "combined_strategy_complexity_threshold"),
        "float",
    ),
    (
        "QUERY_SEMANTIC_SOURCE_ENTITY_SEED_RELATIONSHIP_THRESHOLD",
        (
            "query_understanding",
            "semantics",
            "routing",
            "source_entity_seed_relationship_threshold",
        ),
        "float",
    ),
    (
        "QUERY_SEMANTIC_SOURCE_ENTITY_BACKFILL_RELATIONSHIP_THRESHOLD",
        (
            "query_understanding",
            "semantics",
            "routing",
            "source_entity_backfill_relationship_threshold",
        ),
        "float",
    ),
    (
        "QUERY_SEMANTIC_RULE_FALLBACK_CONFIDENCE",
        ("query_understanding", "semantics", "routing", "rule_fallback_confidence"),
        "float",
    ),
    (
        "QUERY_SEMANTIC_ENTITY_RELATION_MAX_DEPTH",
        ("query_understanding", "semantics", "traversal", "entity_relation_max_depth"),
        "int",
    ),
    (
        "QUERY_SEMANTIC_PATH_FINDING_MAX_DEPTH",
        ("query_understanding", "semantics", "traversal", "path_finding_max_depth"),
        "int",
    ),
    (
        "QUERY_SEMANTIC_PATH_FINDING_HIGH_INTENSITY_MAX_DEPTH",
        ("query_understanding", "semantics", "traversal", "path_finding_high_intensity_max_depth"),
        "int",
    ),
    (
        "QUERY_SEMANTIC_PATH_FINDING_HIGH_INTENSITY_THRESHOLD",
        ("query_understanding", "semantics", "traversal", "path_finding_high_intensity_threshold"),
        "float",
    ),
    (
        "QUERY_SEMANTIC_SUBGRAPH_MAX_DEPTH",
        ("query_understanding", "semantics", "traversal", "subgraph_max_depth"),
        "int",
    ),
    (
        "QUERY_SEMANTIC_SUBGRAPH_HIGH_INTENSITY_MAX_DEPTH",
        ("query_understanding", "semantics", "traversal", "subgraph_high_intensity_max_depth"),
        "int",
    ),
    (
        "QUERY_SEMANTIC_SUBGRAPH_HIGH_INTENSITY_THRESHOLD",
        ("query_understanding", "semantics", "traversal", "subgraph_high_intensity_threshold"),
        "float",
    ),
    (
        "QUERY_SEMANTIC_CLUSTERING_MAX_DEPTH",
        ("query_understanding", "semantics", "traversal", "clustering_max_depth"),
        "int",
    ),
    (
        "QUERY_SEMANTIC_DEFAULT_MAX_DEPTH",
        ("query_understanding", "semantics", "traversal", "default_max_depth"),
        "int",
    ),
    (
        "QUERY_SEMANTIC_DEFAULT_HIGH_INTENSITY_MAX_DEPTH",
        ("query_understanding", "semantics", "traversal", "default_high_intensity_max_depth"),
        "int",
    ),
    (
        "QUERY_SEMANTIC_DEFAULT_HIGH_INTENSITY_THRESHOLD",
        ("query_understanding", "semantics", "traversal", "default_high_intensity_threshold"),
        "float",
    ),
    (
        "QUERY_SEMANTIC_ENTITY_RELATION_MAX_NODES",
        ("query_understanding", "semantics", "traversal", "entity_relation_max_nodes"),
        "int",
    ),
    (
        "QUERY_SEMANTIC_PATH_FINDING_MAX_NODES",
        ("query_understanding", "semantics", "traversal", "path_finding_max_nodes"),
        "int",
    ),
    (
        "QUERY_SEMANTIC_SUBGRAPH_MAX_NODES",
        ("query_understanding", "semantics", "traversal", "subgraph_max_nodes"),
        "int",
    ),
    (
        "QUERY_SEMANTIC_CLUSTERING_MAX_NODES",
        ("query_understanding", "semantics", "traversal", "clustering_max_nodes"),
        "int",
    ),
    (
        "QUERY_SEMANTIC_DEFAULT_MAX_NODES",
        ("query_understanding", "semantics", "traversal", "default_max_nodes"),
        "int",
    ),
    (
        "QUERY_SEMANTIC_GRAPH_QUERY_MAX_DEPTH_CAP",
        ("query_understanding", "semantics", "traversal", "graph_query_max_depth_cap"),
        "int",
    ),
    (
        "QUERY_SEMANTIC_GRAPH_QUERY_FALLBACK_NAME_CHARS",
        ("query_understanding", "semantics", "traversal", "graph_query_fallback_name_chars"),
        "int",
    ),
    (
        "QUERY_SEMANTIC_ADAPTIVE_MULTI_HOP_SUBGRAPH_THRESHOLD",
        ("query_understanding", "semantics", "adaptive_traversal", "multi_hop_subgraph_threshold"),
        "float",
    ),
    (
        "QUERY_SEMANTIC_ADAPTIVE_SUBGRAPH_MULTI_HOP_THRESHOLD",
        ("query_understanding", "semantics", "adaptive_traversal", "subgraph_multi_hop_threshold"),
        "float",
    ),
    (
        "QUERY_SEMANTIC_ADAPTIVE_ENTITY_RELATION_MULTI_HOP_THRESHOLD",
        (
            "query_understanding",
            "semantics",
            "adaptive_traversal",
            "entity_relation_multi_hop_threshold",
        ),
        "float",
    ),
    (
        "QUERY_SEMANTIC_ADAPTIVE_SUBGRAPH_MAX_DEPTH",
        ("query_understanding", "semantics", "adaptive_traversal", "subgraph_max_depth"),
        "int",
    ),
    (
        "QUERY_SEMANTIC_ADAPTIVE_SUBGRAPH_MAX_NODES",
        ("query_understanding", "semantics", "adaptive_traversal", "subgraph_max_nodes"),
        "int",
    ),
    (
        "QUERY_SEMANTIC_ADAPTIVE_MULTI_HOP_MAX_DEPTH",
        ("query_understanding", "semantics", "adaptive_traversal", "multi_hop_max_depth"),
        "int",
    ),
    (
        "QUERY_SEMANTIC_ADAPTIVE_MULTI_HOP_MAX_NODES",
        ("query_understanding", "semantics", "adaptive_traversal", "multi_hop_max_nodes"),
        "int",
    ),
    (
        "QUERY_SEMANTIC_ADAPTIVE_ENTITY_RELATION_MAX_DEPTH",
        ("query_understanding", "semantics", "adaptive_traversal", "entity_relation_max_depth"),
        "int",
    ),
    (
        "QUERY_SEMANTIC_ADAPTIVE_ENTITY_RELATION_MAX_NODES",
        ("query_understanding", "semantics", "adaptive_traversal", "entity_relation_max_nodes"),
        "int",
    ),
)
_RETRIEVAL_ENV_FIELD_SPECS = _specs(
    ("TOP_K", ("retrieval", "top_k"), "int"),
    ("VECTOR_SEARCH_EF", ("retrieval", "vector_search_ef"), "int"),
    ("VECTOR_SEARCH_MAX_K", ("retrieval", "vector_search_max_k"), "int"),
    ("RRF_K", ("retrieval", "rrf_k"), "int"),
    (
        "HYBRID_DEFAULT_CANDIDATE_MULTIPLIER",
        ("retrieval", "hybrid_default_candidate_multiplier"),
        "int",
    ),
    (
        "HYBRID_DEFAULT_CANDIDATE_MIN_CANDIDATES",
        ("retrieval", "hybrid_default_candidate_min_candidates"),
        "int",
    ),
    (
        "HYBRID_CONSTRAINT_CANDIDATE_MULTIPLIER",
        ("retrieval", "hybrid_constraint_candidate_multiplier"),
        "int",
    ),
    (
        "HYBRID_CONSTRAINT_CANDIDATE_MIN_CANDIDATES",
        ("retrieval", "hybrid_constraint_candidate_min_candidates"),
        "int",
    ),
    (
        "ROUTER_COMBINED_CANDIDATE_MULTIPLIER",
        ("retrieval", "router_combined_candidate_multiplier"),
        "int",
    ),
    (
        "ROUTER_COMBINED_CANDIDATE_MIN_CANDIDATES",
        ("retrieval", "router_combined_candidate_min_candidates"),
        "int",
    ),
    (
        "ROUTER_GRAPH_SUPPLEMENT_CANDIDATE_MULTIPLIER",
        ("retrieval", "router_graph_supplement_candidate_multiplier"),
        "int",
    ),
    (
        "ROUTER_GRAPH_SUPPLEMENT_CANDIDATE_MIN_CANDIDATES",
        ("retrieval", "router_graph_supplement_candidate_min_candidates"),
        "int",
    ),
    (
        "RETRIEVAL_PRESERVE_GRAPH_EVIDENCE",
        ("retrieval", "retrieval_preserve_graph_evidence"),
        "bool",
    ),
    ("ENABLE_PARENT_DOC_RETRIEVAL", ("retrieval", "enable_parent_doc_retrieval"), "bool"),
    ("PARENT_DOC_TOP_N", ("retrieval", "parent_doc_top_n"), "int"),
    ("PARENT_DOC_MAX_CHARS", ("retrieval", "parent_doc_max_chars"), "int"),
    (
        "RETRIEVAL_CANDIDATE_SOURCE_FAILURE_THRESHOLD",
        ("retrieval", "candidate_source_failure_threshold"),
        "int",
    ),
    (
        "RETRIEVAL_CANDIDATE_SOURCE_RECOVERY_SECONDS",
        ("retrieval", "candidate_source_recovery_seconds"),
        "float",
    ),
    (
        "RETRIEVAL_CANDIDATE_SOURCE_DEGRADATION_STRATEGY",
        ("retrieval", "candidate_source_degradation_strategy"),
        "str",
    ),
)
_STORAGE_ENV_FIELD_SPECS = _specs(
    ("INDEX_CACHE_DIR", ("storage", "index_cache_dir"), "str"),
    ("ARTIFACT_MANIFEST_PATH", ("storage", "artifact_manifest_path"), "str"),
    ("NEO4J_URI", ("storage", "neo4j_uri"), "str"),
    ("NEO4J_USER", ("storage", "neo4j_user"), "str"),
    ("NEO4J_PASSWORD", ("storage", "neo4j_password"), "str"),
    ("NEO4J_DATABASE", ("storage", "neo4j_database"), "str"),
    ("MILVUS_HOST", ("storage", "milvus_host"), "str"),
    ("MILVUS_PORT", ("storage", "milvus_port"), "int"),
    ("MILVUS_COLLECTION_NAME", ("storage", "milvus_collection_name"), "str"),
    ("MILVUS_DIMENSION", ("storage", "milvus_dimension"), "int"),
    ("ENABLE_INDEX_CACHE", ("storage", "enable_index_cache"), "bool"),
    ("MILVUS_BLUE_GREEN_ENABLED", ("storage", "milvus_blue_green_enabled"), "bool"),
    ("MILVUS_COLLECTION_ALIAS_SUFFIX", ("storage", "milvus_collection_alias_suffix"), "str"),
    ("BUILD_JOB_STORE_PATH", ("storage", "build_job_store_path"), "str"),
    ("BUILD_JOB_POSTGRES_DSN", ("storage", "build_job_postgres_dsn"), "str"),
    ("NEO4J_MAX_CONNECTION_POOL_SIZE", ("storage", "neo4j_max_connection_pool_size"), "int"),
    (
        "NEO4J_CONNECTION_ACQUISITION_TIMEOUT_SECONDS",
        ("storage", "neo4j_connection_acquisition_timeout_seconds"),
        "float",
    ),
    (
        "NEO4J_MAX_CONNECTION_LIFETIME_SECONDS",
        ("storage", "neo4j_max_connection_lifetime_seconds"),
        "float",
    ),
    ("NEO4J_CONNECTION_TIMEOUT_SECONDS", ("storage", "neo4j_connection_timeout_seconds"), "float"),
)

ENV_FIELD_SPECS: tuple[EnvFieldSpec, ...] = (
    *_API_ENV_FIELD_SPECS,
    *_DOMAIN_ENV_FIELD_SPECS,
    *_GENERATION_ENV_FIELD_SPECS,
    *_GRAPH_ENV_FIELD_SPECS,
    *_MODEL_ENV_FIELD_SPECS,
    *_OBSERVABILITY_ENV_FIELD_SPECS,
    *_QUERY_UNDERSTANDING_ENV_FIELD_SPECS,
    *_RETRIEVAL_ENV_FIELD_SPECS,
    *_STORAGE_ENV_FIELD_SPECS,
)

__all__ = ["ENV_FIELD_SPECS", "EnvFieldSpec", "EnvValueKind"]
