"""Environment-backed configuration helpers."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, Dict, List, Literal, Mapping

from .validation import raise_parser_error

EnvValueKind = Literal["str", "int", "float", "bool", "json_dict"]

_TRUE_TOKENS = {"1", "true", "yes", "y", "on"}
_FALSE_TOKENS = {"0", "false", "no", "n", "off"}


@dataclass(frozen=True, slots=True)
class EnvFieldSpec:
    """Schema destination for one environment override field."""

    names: tuple[str, ...]
    path: tuple[str, ...]
    value_kind: EnvValueKind

    @property
    def dotted_path(self) -> str:
        return ".".join(self.path)


@dataclass(slots=True)
class EnvConfigSource:
    """Typed access helpers over environment variables."""

    environ: Mapping[str, str | None]

    def get_str(self, name: str, default: str = "") -> str:
        value = self.environ.get(name)
        return str(value) if value not in (None, "") else default

    def get_int(self, name: str, default: int) -> int:
        value = self.environ.get(name)
        if value in (None, ""):
            return default
        return int(str(value))

    def get_float(self, name: str, default: float) -> float:
        value = self.environ.get(name)
        if value in (None, ""):
            return default
        return float(str(value))

    def get_bool(self, name: str, default: bool) -> bool:
        value = self.environ.get(name)
        if value in (None, ""):
            return default
        return str(value).strip().lower() in _TRUE_TOKENS

    def get_first_with_name(self, *names: str) -> tuple[str, str] | None:
        for name in names:
            value = self.environ.get(name)
            if value not in (None, ""):
                return name, str(value)
        return None

    def get_first(self, *names: str) -> str | None:
        found = self.get_first_with_name(*names)
        return found[1] if found is not None else None

    def get_int_alias(self, *names: str, default: int) -> int:
        value = self.get_first(*names)
        return int(value) if value is not None else default

    def get_float_alias(self, *names: str, default: float) -> float:
        value = self.get_first(*names)
        return float(value) if value is not None else default

    def get_json_dict(self, name: str, default: Dict[str, List[str]]) -> Dict[str, List[str]]:
        value = self.environ.get(name)
        if value in (None, ""):
            return {key: list(items) for key, items in default.items()}
        try:
            parsed = json.loads(str(value))
        except json.JSONDecodeError:
            return {key: list(items) for key, items in default.items()}
        if not isinstance(parsed, dict):
            return {key: list(items) for key, items in default.items()}

        normalized: Dict[str, List[str]] = {}
        for key, items in parsed.items():
            if isinstance(items, list):
                normalized[str(key)] = [str(item).strip() for item in items if str(item).strip()]
        return normalized or {key: list(items) for key, items in default.items()}


def _spec(
    names: str | tuple[str, ...],
    path: tuple[str, ...],
    value_kind: EnvValueKind,
) -> EnvFieldSpec:
    normalized_names = (names,) if isinstance(names, str) else names
    return EnvFieldSpec(names=normalized_names, path=path, value_kind=value_kind)


_ENV_FIELD_SPEC_GROUPS = (
    _spec(("API_ACCESS_TOKEN", "GRAPH_RAG_API_TOKEN"), ("api", "access_token"), "str"),
    _spec("API_AUTH_ENABLED", ("api", "auth_enabled"), "bool"),
    _spec("API_DOCS_ENABLED", ("api", "docs_enabled"), "bool"),
    _spec("API_OPENAPI_ENABLED", ("api", "openapi_enabled"), "bool"),
    _spec("API_DOCS_PUBLIC", ("api", "docs_public"), "bool"),
    _spec("API_OPENAPI_PUBLIC", ("api", "openapi_public"), "bool"),
    _spec("API_MAX_REQUEST_BODY_BYTES", ("api", "max_request_body_bytes"), "int"),
    _spec("API_MAX_CONCURRENT_ANSWERS", ("api", "max_concurrent_answers"), "int"),
    _spec(
        "API_ANSWER_ACQUIRE_TIMEOUT_SECONDS",
        ("api", "answer_acquire_timeout_seconds"),
        "float",
    ),
    _spec("API_STREAM_EXECUTOR_MAX_WORKERS", ("api", "stream_executor_max_workers"), "int"),
    _spec("API_STREAM_QUEUE_MAX_SIZE", ("api", "stream_queue_max_size"), "int"),
    _spec("SERVING_HOT_REFRESH_ENABLED", ("api", "serving_hot_refresh_enabled"), "bool"),
    _spec(
        "SERVING_HOT_REFRESH_INTERVAL_SECONDS",
        ("api", "serving_hot_refresh_interval_seconds"),
        "float",
    ),
    _spec("TEMPERATURE", ("generation", "temperature"), "float"),
    _spec("MAX_TOKENS", ("generation", "max_tokens"), "int"),
    _spec("GENERATION_TIMEOUT_SECONDS", ("generation", "generation_timeout_seconds"), "int"),
    _spec(
        "GENERATION_STREAM_TIMEOUT_SECONDS",
        ("generation", "generation_stream_timeout_seconds"),
        "int",
    ),
    _spec(
        "GENERATION_LATENCY_BUDGET_SECONDS",
        ("generation", "generation_latency_budget_seconds"),
        "int",
    ),
    _spec("GENERATION_PLAN_MAX_TOKENS", ("generation", "generation_plan_max_tokens"), "int"),
    _spec(
        "GENERATION_COMPOSE_MAX_TOKENS",
        ("generation", "generation_compose_max_tokens"),
        "int",
    ),
    _spec("GENERATION_DIRECT_MAX_TOKENS", ("generation", "generation_direct_max_tokens"), "int"),
    _spec(
        "GENERATION_PLAN_TEMPERATURE",
        ("generation", "generation_plan_temperature"),
        "float",
    ),
    _spec("GENERATION_PLANNER_MODE", ("generation", "generation_planner_mode"), "str"),
    _spec("GENERATION_MAX_RETRIES", ("generation", "generation_max_retries"), "int"),
    _spec("GENERATION_REQUEST_RETRIES", ("generation", "generation_request_retries"), "int"),
    _spec("GENERATION_STREAM_RETRIES", ("generation", "generation_stream_retries"), "int"),
    _spec("GENERATION_EVIDENCE_MAX_CHARS", ("generation", "generation_evidence_max_chars"), "int"),
    _spec(
        "GENERATION_ENABLE_TWO_STAGE",
        ("generation", "generation_enable_two_stage"),
        "bool",
    ),
    _spec(
        "GENERATION_TWO_STAGE_COMPLEXITY_THRESHOLD",
        ("generation", "generation_two_stage_complexity_threshold"),
        "float",
    ),
    _spec(
        "GENERATION_TWO_STAGE_RELATIONSHIP_THRESHOLD",
        ("generation", "generation_two_stage_relationship_threshold"),
        "float",
    ),
    _spec(
        "GENERATION_DIRECT_MAX_EVIDENCE_ITEMS",
        ("generation", "generation_direct_max_evidence_items"),
        "int",
    ),
    _spec(
        "GENERATION_TWO_STAGE_MAX_EVIDENCE_ITEMS",
        ("generation", "generation_two_stage_max_evidence_items"),
        "int",
    ),
    _spec(
        "GENERATION_PLAN_MAX_EVIDENCE_ITEMS",
        ("generation", "generation_plan_max_evidence_items"),
        "int",
    ),
    _spec(
        "GENERATION_MAX_GRAPH_PATHS_PER_ITEM",
        ("generation", "generation_max_graph_paths_per_item"),
        "int",
    ),
    _spec(
        "GENERATION_MAX_EVIDENCE_UNITS_PER_ITEM",
        ("generation", "generation_max_evidence_units_per_item"),
        "int",
    ),
    _spec(
        "GENERATION_INCLUDE_DOCUMENT_EVIDENCE",
        ("generation", "generation_include_document_evidence"),
        "bool",
    ),
    _spec(
        "GENERATION_COMPOSE_INCLUDE_CONTENT",
        ("generation", "generation_compose_include_content"),
        "bool",
    ),
    _spec(
        "GENERATION_FALLBACK_ON_TIMEOUT",
        ("generation", "generation_fallback_on_timeout"),
        "bool",
    ),
    _spec("ENABLE_SEMANTIC_GRAPH_SCHEMA", ("graph", "enable_semantic_graph_schema"), "bool"),
    _spec("CHUNK_SIZE", ("graph", "chunk_size"), "int"),
    _spec("CHUNK_OVERLAP", ("graph", "chunk_overlap"), "int"),
    _spec("MAX_GRAPH_DEPTH", ("graph", "max_graph_depth"), "int"),
    _spec("GRAPH_RANK_BASE_WEIGHT", ("graph", "graph_rank_base_weight"), "float"),
    _spec(
        "GRAPH_RANK_SEMANTIC_RELATION_WEIGHT",
        ("graph", "graph_rank_semantic_relation_weight"),
        "float",
    ),
    _spec(
        "GRAPH_RANK_EVIDENCE_UNIT_WEIGHT",
        ("graph", "graph_rank_evidence_unit_weight"),
        "float",
    ),
    _spec("GRAPH_RANK_RELATIONSHIP_WEIGHT", ("graph", "graph_rank_relationship_weight"), "float"),
    _spec(
        "GRAPH_RANK_RECIPE_PRESENCE_WEIGHT",
        ("graph", "graph_rank_recipe_presence_weight"),
        "float",
    ),
    _spec("GRAPH_RANK_QUERY_OVERLAP_WEIGHT", ("graph", "graph_rank_query_overlap_weight"), "float"),
    _spec("ENTITY_LINKER_LIMIT_PER_ENTITY", ("graph", "entity_linker_limit_per_entity"), "int"),
    _spec("ENTITY_LINKER_MIN_CONFIDENCE", ("graph", "entity_linker_min_confidence"), "float"),
    _spec(
        "ENTITY_LINKER_MAX_SAME_NAME_CANDIDATES",
        ("graph", "entity_linker_max_same_name_candidates"),
        "int",
    ),
    _spec(
        "ENTITY_LINKER_QUERY_TYPE_LABEL_PRIORITIES",
        ("graph", "entity_linker_query_type_label_priorities"),
        "json_dict",
    ),
    _spec(
        "ENTITY_LINKER_RELATION_LABEL_PRIORITIES",
        ("graph", "entity_linker_relation_label_priorities"),
        "json_dict",
    ),
    _spec(
        ("DASHSCOPE_API_KEY", "OPENAI_API_KEY", "MOONSHOT_API_KEY"), ("models", "api_key"), "str"
    ),
    _spec("LLM_BASE_URL", ("models", "llm_base_url"), "str"),
    _spec("EMBEDDING_BASE_URL", ("models", "embedding_base_url"), "str"),
    _spec("RERANK_BASE_URL", ("models", "rerank_base_url"), "str"),
    _spec("EMBEDDING_MODEL", ("models", "embedding_model"), "str"),
    _spec("LLM_MODEL", ("models", "llm_model"), "str"),
    _spec("RERANK_MODEL", ("models", "rerank_model"), "str"),
    _spec("EMBEDDING_DIMENSION", ("models", "embedding_dimension"), "int"),
    _spec("EMBEDDING_BATCH_SIZE", ("models", "embedding_batch_size"), "int"),
    _spec("ENABLE_RERANK", ("models", "enable_rerank"), "bool"),
    _spec("LLM_TIMEOUT_SECONDS", ("models", "llm_timeout_seconds"), "int"),
    _spec("EMBEDDING_TIMEOUT_SECONDS", ("models", "embedding_timeout_seconds"), "int"),
    _spec("RERANK_TIMEOUT_SECONDS", ("models", "rerank_timeout_seconds"), "int"),
    _spec("HTTP_POOL_CONNECTIONS", ("models", "http_pool_connections"), "int"),
    _spec("HTTP_POOL_MAXSIZE", ("models", "http_pool_maxsize"), "int"),
    _spec(
        "CIRCUIT_BREAKER_FAILURE_THRESHOLD",
        ("models", "circuit_breaker_failure_threshold"),
        "int",
    ),
    _spec(
        "CIRCUIT_BREAKER_RECOVERY_SECONDS",
        ("models", "circuit_breaker_recovery_seconds"),
        "float",
    ),
    _spec(
        "LLM_INPUT_COST_PER_MILLION_TOKENS",
        ("models", "llm_input_cost_per_million_tokens"),
        "float",
    ),
    _spec(
        "LLM_OUTPUT_COST_PER_MILLION_TOKENS",
        ("models", "llm_output_cost_per_million_tokens"),
        "float",
    ),
    _spec("ENABLE_QUERY_TRACING", ("observability", "enable_query_tracing"), "bool"),
    _spec("QUERY_TRACE_PATH", ("observability", "query_trace_path"), "str"),
    _spec(
        "QUERY_TRACE_ASYNC_ENABLED",
        ("observability", "query_trace_async_enabled"),
        "bool",
    ),
    _spec("QUERY_TRACE_MAX_QUEUE_SIZE", ("observability", "query_trace_max_queue_size"), "int"),
    _spec(
        "QUERY_TRACE_FINGERPRINT_SALT",
        ("observability", "query_trace_fingerprint_salt"),
        "str",
    ),
    _spec("ENABLE_OPENTELEMETRY", ("observability", "enable_opentelemetry"), "bool"),
    _spec("OTEL_SERVICE_NAME", ("observability", "otel_service_name"), "str"),
    _spec(
        "OTEL_EXPORTER_OTLP_ENDPOINT",
        ("observability", "otel_exporter_otlp_endpoint"),
        "str",
    ),
    _spec("OTEL_TRACE_SAMPLE_RATIO", ("observability", "otel_trace_sample_ratio"), "float"),
    _spec("ENABLE_PROMETHEUS", ("observability", "enable_prometheus"), "bool"),
    _spec("PROMETHEUS_METRICS_PUBLIC", ("observability", "prometheus_public"), "bool"),
    _spec("TOP_K", ("retrieval", "top_k"), "int"),
    _spec("VECTOR_SEARCH_EF", ("retrieval", "vector_search_ef"), "int"),
    _spec("VECTOR_SEARCH_MAX_K", ("retrieval", "vector_search_max_k"), "int"),
    _spec("RRF_K", ("retrieval", "rrf_k"), "int"),
    _spec(
        "HYBRID_DEFAULT_CANDIDATE_MULTIPLIER",
        ("retrieval", "hybrid_default_candidate_multiplier"),
        "int",
    ),
    _spec(
        "HYBRID_DEFAULT_CANDIDATE_MIN_CANDIDATES",
        ("retrieval", "hybrid_default_candidate_min_candidates"),
        "int",
    ),
    _spec(
        "HYBRID_CONSTRAINT_CANDIDATE_MULTIPLIER",
        ("retrieval", "hybrid_constraint_candidate_multiplier"),
        "int",
    ),
    _spec(
        "HYBRID_CONSTRAINT_CANDIDATE_MIN_CANDIDATES",
        ("retrieval", "hybrid_constraint_candidate_min_candidates"),
        "int",
    ),
    _spec(
        "ROUTER_COMBINED_CANDIDATE_MULTIPLIER",
        ("retrieval", "router_combined_candidate_multiplier"),
        "int",
    ),
    _spec(
        "ROUTER_COMBINED_CANDIDATE_MIN_CANDIDATES",
        ("retrieval", "router_combined_candidate_min_candidates"),
        "int",
    ),
    _spec(
        "ROUTER_GRAPH_SUPPLEMENT_CANDIDATE_MULTIPLIER",
        ("retrieval", "router_graph_supplement_candidate_multiplier"),
        "int",
    ),
    _spec(
        "ROUTER_GRAPH_SUPPLEMENT_CANDIDATE_MIN_CANDIDATES",
        ("retrieval", "router_graph_supplement_candidate_min_candidates"),
        "int",
    ),
    _spec(
        "RETRIEVAL_PRESERVE_GRAPH_EVIDENCE",
        ("retrieval", "retrieval_preserve_graph_evidence"),
        "bool",
    ),
    _spec(
        "ENABLE_PARENT_DOC_RETRIEVAL",
        ("retrieval", "enable_parent_doc_retrieval"),
        "bool",
    ),
    _spec("PARENT_DOC_TOP_N", ("retrieval", "parent_doc_top_n"), "int"),
    _spec("PARENT_DOC_MAX_CHARS", ("retrieval", "parent_doc_max_chars"), "int"),
    _spec(
        "RETRIEVAL_CANDIDATE_SOURCE_FAILURE_THRESHOLD",
        ("retrieval", "candidate_source_failure_threshold"),
        "int",
    ),
    _spec(
        "RETRIEVAL_CANDIDATE_SOURCE_RECOVERY_SECONDS",
        ("retrieval", "candidate_source_recovery_seconds"),
        "float",
    ),
    _spec(
        "RETRIEVAL_CANDIDATE_SOURCE_DEGRADATION_STRATEGY",
        ("retrieval", "candidate_source_degradation_strategy"),
        "str",
    ),
    _spec("INDEX_CACHE_DIR", ("storage", "index_cache_dir"), "str"),
    _spec("ARTIFACT_MANIFEST_PATH", ("storage", "artifact_manifest_path"), "str"),
    _spec("NEO4J_URI", ("storage", "neo4j_uri"), "str"),
    _spec("NEO4J_USER", ("storage", "neo4j_user"), "str"),
    _spec("NEO4J_PASSWORD", ("storage", "neo4j_password"), "str"),
    _spec("NEO4J_DATABASE", ("storage", "neo4j_database"), "str"),
    _spec("MILVUS_HOST", ("storage", "milvus_host"), "str"),
    _spec("MILVUS_PORT", ("storage", "milvus_port"), "int"),
    _spec("MILVUS_COLLECTION_NAME", ("storage", "milvus_collection_name"), "str"),
    _spec("MILVUS_DIMENSION", ("storage", "milvus_dimension"), "int"),
    _spec("ENABLE_INDEX_CACHE", ("storage", "enable_index_cache"), "bool"),
    _spec("MILVUS_BLUE_GREEN_ENABLED", ("storage", "milvus_blue_green_enabled"), "bool"),
    _spec("MILVUS_COLLECTION_ALIAS_SUFFIX", ("storage", "milvus_collection_alias_suffix"), "str"),
    _spec("BUILD_JOB_STORE_PATH", ("storage", "build_job_store_path"), "str"),
    _spec(
        "NEO4J_MAX_CONNECTION_POOL_SIZE",
        ("storage", "neo4j_max_connection_pool_size"),
        "int",
    ),
    _spec(
        "NEO4J_CONNECTION_ACQUISITION_TIMEOUT_SECONDS",
        ("storage", "neo4j_connection_acquisition_timeout_seconds"),
        "float",
    ),
    _spec(
        "NEO4J_MAX_CONNECTION_LIFETIME_SECONDS",
        ("storage", "neo4j_max_connection_lifetime_seconds"),
        "float",
    ),
    _spec(
        "NEO4J_CONNECTION_TIMEOUT_SECONDS",
        ("storage", "neo4j_connection_timeout_seconds"),
        "float",
    ),
    _spec(
        "QUERY_PLAN_CACHE_SIZE",
        ("query_understanding", "planner", "cache_size"),
        "int",
    ),
    _spec(
        "FAST_RULE_QUERY_PLANNING",
        ("query_understanding", "planner", "fast_rule_planning"),
        "bool",
    ),
    _spec(
        "QUERY_PLANNER_LLM_TEMPERATURE",
        ("query_understanding", "planner", "llm_temperature"),
        "float",
    ),
    _spec(
        "QUERY_PLANNER_LLM_MAX_TOKENS",
        ("query_understanding", "planner", "llm_max_tokens"),
        "int",
    ),
    _spec(
        "QUERY_SEMANTIC_RELATION_INTENSITY_REFERENCE_RATIO",
        ("query_understanding", "semantics", "scoring", "relation_intensity_reference_ratio"),
        "float",
    ),
    _spec(
        "QUERY_SEMANTIC_COMPLEXITY_RELATION_HIT_WEIGHT",
        ("query_understanding", "semantics", "scoring", "complexity_relation_hit_weight"),
        "float",
    ),
    _spec(
        "QUERY_SEMANTIC_COMPLEXITY_CONSTRAINT_HIT_WEIGHT",
        ("query_understanding", "semantics", "scoring", "complexity_constraint_hit_weight"),
        "float",
    ),
    _spec(
        "QUERY_SEMANTIC_COMPLEXITY_STRUCTURAL_HIT_WEIGHT",
        ("query_understanding", "semantics", "scoring", "complexity_structural_hit_weight"),
        "float",
    ),
    _spec(
        "QUERY_SEMANTIC_COMPLEXITY_LENGTH_WEIGHT",
        ("query_understanding", "semantics", "scoring", "complexity_length_weight"),
        "float",
    ),
    _spec(
        "QUERY_SEMANTIC_COMPLEXITY_LENGTH_NORM_CHARS",
        ("query_understanding", "semantics", "scoring", "complexity_length_norm_chars"),
        "int",
    ),
    _spec(
        "QUERY_SEMANTIC_REASONING_COMPLEXITY_THRESHOLD",
        ("query_understanding", "semantics", "scoring", "reasoning_complexity_threshold"),
        "float",
    ),
    _spec(
        "QUERY_SEMANTIC_REASONING_RELATIONSHIP_THRESHOLD",
        ("query_understanding", "semantics", "scoring", "reasoning_relationship_threshold"),
        "float",
    ),
    _spec(
        "QUERY_SEMANTIC_RELATION_HIT_INTENSITY_BOOST_BASE",
        ("query_understanding", "semantics", "scoring", "relation_hit_intensity_boost_base"),
        "float",
    ),
    _spec(
        "QUERY_SEMANTIC_RELATION_HIT_INTENSITY_BOOST_STEP",
        ("query_understanding", "semantics", "scoring", "relation_hit_intensity_boost_step"),
        "float",
    ),
    _spec(
        "QUERY_SEMANTIC_RELATION_HIT_COMPLEXITY_BOOST_BASE",
        ("query_understanding", "semantics", "scoring", "relation_hit_complexity_boost_base"),
        "float",
    ),
    _spec(
        "QUERY_SEMANTIC_RELATION_HIT_COMPLEXITY_BOOST_STEP",
        ("query_understanding", "semantics", "scoring", "relation_hit_complexity_boost_step"),
        "float",
    ),
    _spec(
        "QUERY_SEMANTIC_SOURCE_ENTITY_LIMIT",
        ("query_understanding", "semantics", "extraction", "source_entity_limit"),
        "int",
    ),
    _spec(
        "QUERY_SEMANTIC_ENTITY_KEYWORD_LIMIT",
        ("query_understanding", "semantics", "extraction", "entity_keyword_limit"),
        "int",
    ),
    _spec(
        "QUERY_SEMANTIC_PROFILE_ENTITY_KEYWORD_LIMIT",
        ("query_understanding", "semantics", "extraction", "semantic_profile_entity_keyword_limit"),
        "int",
    ),
    _spec(
        "QUERY_SEMANTIC_TOPIC_KEYWORD_LIMIT",
        ("query_understanding", "semantics", "extraction", "topic_keyword_limit"),
        "int",
    ),
    _spec(
        "QUERY_SEMANTIC_PROFILE_TOPIC_KEYWORD_START",
        ("query_understanding", "semantics", "extraction", "semantic_profile_topic_keyword_start"),
        "int",
    ),
    _spec(
        "QUERY_SEMANTIC_PROFILE_TOPIC_KEYWORD_LIMIT",
        ("query_understanding", "semantics", "extraction", "semantic_profile_topic_keyword_limit"),
        "int",
    ),
    _spec(
        "QUERY_SEMANTIC_TARGET_ENTITY_LIMIT",
        ("query_understanding", "semantics", "extraction", "target_entity_limit"),
        "int",
    ),
    _spec(
        "QUERY_SEMANTIC_HIGH_RELATIONSHIP_ROUTING_THRESHOLD",
        ("query_understanding", "semantics", "routing", "high_relationship_routing_threshold"),
        "float",
    ),
    _spec(
        "QUERY_SEMANTIC_MULTI_HOP_HINT_ENTITY_COUNT",
        ("query_understanding", "semantics", "routing", "multi_hop_hint_entity_count"),
        "int",
    ),
    _spec(
        "QUERY_SEMANTIC_MULTI_HOP_HINT_RELATIONSHIP_THRESHOLD",
        ("query_understanding", "semantics", "routing", "multi_hop_hint_relationship_threshold"),
        "float",
    ),
    _spec(
        "QUERY_SEMANTIC_COMBINED_STRATEGY_RELATIONSHIP_THRESHOLD",
        (
            "query_understanding",
            "semantics",
            "routing",
            "combined_strategy_relationship_threshold",
        ),
        "float",
    ),
    _spec(
        "QUERY_SEMANTIC_COMBINED_STRATEGY_COMPLEXITY_THRESHOLD",
        ("query_understanding", "semantics", "routing", "combined_strategy_complexity_threshold"),
        "float",
    ),
    _spec(
        "QUERY_SEMANTIC_SOURCE_ENTITY_SEED_RELATIONSHIP_THRESHOLD",
        (
            "query_understanding",
            "semantics",
            "routing",
            "source_entity_seed_relationship_threshold",
        ),
        "float",
    ),
    _spec(
        "QUERY_SEMANTIC_SOURCE_ENTITY_BACKFILL_RELATIONSHIP_THRESHOLD",
        (
            "query_understanding",
            "semantics",
            "routing",
            "source_entity_backfill_relationship_threshold",
        ),
        "float",
    ),
    _spec(
        "QUERY_SEMANTIC_RULE_FALLBACK_CONFIDENCE",
        ("query_understanding", "semantics", "routing", "rule_fallback_confidence"),
        "float",
    ),
    _spec(
        "QUERY_SEMANTIC_ENTITY_RELATION_MAX_DEPTH",
        ("query_understanding", "semantics", "traversal", "entity_relation_max_depth"),
        "int",
    ),
    _spec(
        "QUERY_SEMANTIC_PATH_FINDING_MAX_DEPTH",
        ("query_understanding", "semantics", "traversal", "path_finding_max_depth"),
        "int",
    ),
    _spec(
        "QUERY_SEMANTIC_PATH_FINDING_HIGH_INTENSITY_MAX_DEPTH",
        ("query_understanding", "semantics", "traversal", "path_finding_high_intensity_max_depth"),
        "int",
    ),
    _spec(
        "QUERY_SEMANTIC_PATH_FINDING_HIGH_INTENSITY_THRESHOLD",
        ("query_understanding", "semantics", "traversal", "path_finding_high_intensity_threshold"),
        "float",
    ),
    _spec(
        "QUERY_SEMANTIC_SUBGRAPH_MAX_DEPTH",
        ("query_understanding", "semantics", "traversal", "subgraph_max_depth"),
        "int",
    ),
    _spec(
        "QUERY_SEMANTIC_SUBGRAPH_HIGH_INTENSITY_MAX_DEPTH",
        ("query_understanding", "semantics", "traversal", "subgraph_high_intensity_max_depth"),
        "int",
    ),
    _spec(
        "QUERY_SEMANTIC_SUBGRAPH_HIGH_INTENSITY_THRESHOLD",
        ("query_understanding", "semantics", "traversal", "subgraph_high_intensity_threshold"),
        "float",
    ),
    _spec(
        "QUERY_SEMANTIC_CLUSTERING_MAX_DEPTH",
        ("query_understanding", "semantics", "traversal", "clustering_max_depth"),
        "int",
    ),
    _spec(
        "QUERY_SEMANTIC_DEFAULT_MAX_DEPTH",
        ("query_understanding", "semantics", "traversal", "default_max_depth"),
        "int",
    ),
    _spec(
        "QUERY_SEMANTIC_DEFAULT_HIGH_INTENSITY_MAX_DEPTH",
        ("query_understanding", "semantics", "traversal", "default_high_intensity_max_depth"),
        "int",
    ),
    _spec(
        "QUERY_SEMANTIC_DEFAULT_HIGH_INTENSITY_THRESHOLD",
        ("query_understanding", "semantics", "traversal", "default_high_intensity_threshold"),
        "float",
    ),
    _spec(
        "QUERY_SEMANTIC_ENTITY_RELATION_MAX_NODES",
        ("query_understanding", "semantics", "traversal", "entity_relation_max_nodes"),
        "int",
    ),
    _spec(
        "QUERY_SEMANTIC_PATH_FINDING_MAX_NODES",
        ("query_understanding", "semantics", "traversal", "path_finding_max_nodes"),
        "int",
    ),
    _spec(
        "QUERY_SEMANTIC_SUBGRAPH_MAX_NODES",
        ("query_understanding", "semantics", "traversal", "subgraph_max_nodes"),
        "int",
    ),
    _spec(
        "QUERY_SEMANTIC_CLUSTERING_MAX_NODES",
        ("query_understanding", "semantics", "traversal", "clustering_max_nodes"),
        "int",
    ),
    _spec(
        "QUERY_SEMANTIC_DEFAULT_MAX_NODES",
        ("query_understanding", "semantics", "traversal", "default_max_nodes"),
        "int",
    ),
    _spec(
        "QUERY_SEMANTIC_GRAPH_QUERY_MAX_DEPTH_CAP",
        ("query_understanding", "semantics", "traversal", "graph_query_max_depth_cap"),
        "int",
    ),
    _spec(
        "QUERY_SEMANTIC_GRAPH_QUERY_FALLBACK_NAME_CHARS",
        ("query_understanding", "semantics", "traversal", "graph_query_fallback_name_chars"),
        "int",
    ),
    _spec(
        "QUERY_SEMANTIC_ADAPTIVE_MULTI_HOP_SUBGRAPH_THRESHOLD",
        (
            "query_understanding",
            "semantics",
            "adaptive_traversal",
            "multi_hop_subgraph_threshold",
        ),
        "float",
    ),
    _spec(
        "QUERY_SEMANTIC_ADAPTIVE_SUBGRAPH_MULTI_HOP_THRESHOLD",
        (
            "query_understanding",
            "semantics",
            "adaptive_traversal",
            "subgraph_multi_hop_threshold",
        ),
        "float",
    ),
    _spec(
        "QUERY_SEMANTIC_ADAPTIVE_ENTITY_RELATION_MULTI_HOP_THRESHOLD",
        (
            "query_understanding",
            "semantics",
            "adaptive_traversal",
            "entity_relation_multi_hop_threshold",
        ),
        "float",
    ),
    _spec(
        "QUERY_SEMANTIC_ADAPTIVE_SUBGRAPH_MAX_DEPTH",
        ("query_understanding", "semantics", "adaptive_traversal", "subgraph_max_depth"),
        "int",
    ),
    _spec(
        "QUERY_SEMANTIC_ADAPTIVE_SUBGRAPH_MAX_NODES",
        ("query_understanding", "semantics", "adaptive_traversal", "subgraph_max_nodes"),
        "int",
    ),
    _spec(
        "QUERY_SEMANTIC_ADAPTIVE_MULTI_HOP_MAX_DEPTH",
        ("query_understanding", "semantics", "adaptive_traversal", "multi_hop_max_depth"),
        "int",
    ),
    _spec(
        "QUERY_SEMANTIC_ADAPTIVE_MULTI_HOP_MAX_NODES",
        ("query_understanding", "semantics", "adaptive_traversal", "multi_hop_max_nodes"),
        "int",
    ),
    _spec(
        "QUERY_SEMANTIC_ADAPTIVE_ENTITY_RELATION_MAX_DEPTH",
        ("query_understanding", "semantics", "adaptive_traversal", "entity_relation_max_depth"),
        "int",
    ),
    _spec(
        "QUERY_SEMANTIC_ADAPTIVE_ENTITY_RELATION_MAX_NODES",
        ("query_understanding", "semantics", "adaptive_traversal", "entity_relation_max_nodes"),
        "int",
    ),
)

ENV_FIELD_SPECS: dict[str, EnvFieldSpec] = {
    name: spec for spec in _ENV_FIELD_SPEC_GROUPS for name in spec.names
}


def _parse_bool(value: str, source: str, path: str) -> bool:
    normalized = value.strip().lower()
    if normalized in _TRUE_TOKENS:
        return True
    if normalized in _FALSE_TOKENS:
        return False
    raise_parser_error(
        source_kind="environment",
        source=source,
        path=path,
        message="expected boolean",
    )


def _parse_int(value: str, source: str, path: str) -> int:
    try:
        return int(value)
    except ValueError as exc:
        raise_parser_error(
            source_kind="environment",
            source=source,
            path=path,
            message="expected integer",
        )
        raise AssertionError("unreachable") from exc


def _parse_float(value: str, source: str, path: str) -> float:
    try:
        return float(value)
    except ValueError as exc:
        raise_parser_error(
            source_kind="environment",
            source=source,
            path=path,
            message="expected number",
        )
        raise AssertionError("unreachable") from exc


def _parse_json_dict(value: str, source: str, path: str) -> dict[str, list[str]]:
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise_parser_error(
            source_kind="environment",
            source=source,
            path=path,
            message="expected JSON object",
        )
        raise AssertionError("unreachable") from exc

    if not isinstance(parsed, dict):
        raise_parser_error(
            source_kind="environment",
            source=source,
            path=path,
            message="expected JSON object",
        )

    normalized: dict[str, list[str]] = {}
    for key, items in parsed.items():
        if not isinstance(key, str) or not isinstance(items, list):
            raise_parser_error(
                source_kind="environment",
                source=source,
                path=path,
                message="expected JSON object with string keys and string-list values",
            )
        if not all(isinstance(item, str) for item in items):
            raise_parser_error(
                source_kind="environment",
                source=source,
                path=path,
                message="expected JSON object with string keys and string-list values",
            )
        normalized[key] = list(items)
    return normalized


def _parse_value(spec: EnvFieldSpec, source: str, value: str) -> Any:
    path = spec.dotted_path
    if spec.value_kind == "str":
        return value
    if spec.value_kind == "int":
        return _parse_int(value, source, path)
    if spec.value_kind == "float":
        return _parse_float(value, source, path)
    if spec.value_kind == "bool":
        return _parse_bool(value, source, path)
    return _parse_json_dict(value, source, path)


def _assign_path(payload: dict[str, Any], path: tuple[str, ...], value: Any) -> None:
    target = payload
    for part in path[:-1]:
        next_value = target.setdefault(part, {})
        if not isinstance(next_value, dict):
            next_value = {}
            target[part] = next_value
        target = next_value
    target[path[-1]] = value


def build_env_overrides(
    source: EnvConfigSource,
    *,
    section_name: str | None = None,
) -> dict[str, Any]:
    """Build strict nested configuration overrides from supported environment variables."""

    payload: dict[str, Any] = {}
    seen_specs: set[EnvFieldSpec] = set()
    for spec in ENV_FIELD_SPECS.values():
        if section_name is not None and spec.path[:1] != (section_name,):
            continue
        if spec in seen_specs:
            continue
        seen_specs.add(spec)
        found = source.get_first_with_name(*spec.names)
        if found is None:
            continue
        env_name, raw_value = found
        _assign_path(payload, spec.path, _parse_value(spec, env_name, raw_value))
    return payload


def default_env_source() -> EnvConfigSource:
    return EnvConfigSource(environ=os.environ)


__all__ = [
    "ENV_FIELD_SPECS",
    "EnvConfigSource",
    "EnvFieldSpec",
    "build_env_overrides",
    "default_env_source",
]
