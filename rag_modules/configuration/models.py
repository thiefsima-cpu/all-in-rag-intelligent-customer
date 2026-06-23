"""Configuration models for GraphRAG."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from dataclasses import fields as dataclass_fields
from typing import Any, Dict, List, Mapping, cast


def _serialize_config_value(value: Any) -> Any:
    if isinstance(value, ConfigSection):
        return value.to_dict()
    if isinstance(value, Mapping):
        return {str(key): _serialize_config_value(item) for key, item in dict(value).items()}
    if isinstance(value, list):
        return [_serialize_config_value(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_serialize_config_value(item) for item in value)
    return value


class ConfigSection:
    """Serializable section base."""

    def to_dict(self) -> Dict[str, Any]:
        return {
            field.name: _serialize_config_value(getattr(self, field.name))
            for field in dataclass_fields(cast(Any, self))
        }


@dataclass(slots=True)
class StorageSettings(ConfigSection):
    neo4j_uri: str
    neo4j_user: str
    neo4j_password: str
    neo4j_database: str
    milvus_host: str
    milvus_port: int
    milvus_collection_name: str
    milvus_dimension: int
    enable_index_cache: bool
    index_cache_dir: str
    artifact_manifest_path: str
    milvus_blue_green_enabled: bool = True
    milvus_collection_alias_suffix: str = "__active"
    build_job_store_path: str = ""
    neo4j_max_connection_pool_size: int = 50
    neo4j_connection_acquisition_timeout_seconds: float = 30.0
    neo4j_max_connection_lifetime_seconds: float = 3600.0
    neo4j_connection_timeout_seconds: float = 15.0


@dataclass(slots=True)
class ModelSettings(ConfigSection):
    api_key: str
    llm_base_url: str
    embedding_base_url: str
    rerank_base_url: str
    embedding_model: str
    llm_model: str
    rerank_model: str
    embedding_dimension: int
    embedding_batch_size: int
    enable_rerank: bool
    llm_timeout_seconds: int
    embedding_timeout_seconds: int
    rerank_timeout_seconds: int
    http_pool_connections: int = 10
    http_pool_maxsize: int = 20
    circuit_breaker_failure_threshold: int = 5
    circuit_breaker_recovery_seconds: float = 30.0
    llm_input_cost_per_million_tokens: float = 0.0
    llm_output_cost_per_million_tokens: float = 0.0


@dataclass(slots=True)
class RetrievalSettings(ConfigSection):
    top_k: int
    vector_search_ef: int
    vector_search_max_k: int
    rrf_k: int
    hybrid_default_candidate_multiplier: int
    hybrid_default_candidate_min_candidates: int
    hybrid_constraint_candidate_multiplier: int
    hybrid_constraint_candidate_min_candidates: int
    router_combined_candidate_multiplier: int
    router_combined_candidate_min_candidates: int
    router_graph_supplement_candidate_multiplier: int
    router_graph_supplement_candidate_min_candidates: int
    retrieval_preserve_graph_evidence: bool
    enable_parent_doc_retrieval: bool
    parent_doc_top_n: int
    parent_doc_max_chars: int
    candidate_source_failure_threshold: int = 1
    candidate_source_recovery_seconds: float = 30.0
    candidate_source_degradation_strategy: str = "continue"


@dataclass(slots=True)
class QueryPlannerSettings(ConfigSection):
    cache_size: int
    fast_rule_planning: bool
    llm_temperature: float
    llm_max_tokens: int


@dataclass(slots=True)
class QuerySemanticScoringSettings(ConfigSection):
    relation_intensity_reference_ratio: float
    complexity_relation_hit_weight: float
    complexity_constraint_hit_weight: float
    complexity_structural_hit_weight: float
    complexity_length_weight: float
    complexity_length_norm_chars: int
    reasoning_complexity_threshold: float
    reasoning_relationship_threshold: float
    relation_hit_intensity_boost_base: float
    relation_hit_intensity_boost_step: float
    relation_hit_complexity_boost_base: float
    relation_hit_complexity_boost_step: float


@dataclass(slots=True)
class QuerySemanticExtractionSettings(ConfigSection):
    source_entity_limit: int
    entity_keyword_limit: int
    semantic_profile_entity_keyword_limit: int
    topic_keyword_limit: int
    semantic_profile_topic_keyword_start: int
    semantic_profile_topic_keyword_limit: int
    target_entity_limit: int


@dataclass(slots=True)
class QuerySemanticRoutingSettings(ConfigSection):
    high_relationship_routing_threshold: float
    multi_hop_hint_entity_count: int
    multi_hop_hint_relationship_threshold: float
    combined_strategy_relationship_threshold: float
    combined_strategy_complexity_threshold: float
    source_entity_seed_relationship_threshold: float
    source_entity_backfill_relationship_threshold: float
    rule_fallback_confidence: float


@dataclass(slots=True)
class QuerySemanticTraversalSettings(ConfigSection):
    entity_relation_max_depth: int
    path_finding_max_depth: int
    path_finding_high_intensity_max_depth: int
    path_finding_high_intensity_threshold: float
    subgraph_max_depth: int
    subgraph_high_intensity_max_depth: int
    subgraph_high_intensity_threshold: float
    clustering_max_depth: int
    default_max_depth: int
    default_high_intensity_max_depth: int
    default_high_intensity_threshold: float
    entity_relation_max_nodes: int
    path_finding_max_nodes: int
    subgraph_max_nodes: int
    clustering_max_nodes: int
    default_max_nodes: int
    graph_query_max_depth_cap: int
    graph_query_fallback_name_chars: int


@dataclass(slots=True)
class QuerySemanticAdaptiveTraversalSettings(ConfigSection):
    multi_hop_subgraph_threshold: float
    subgraph_multi_hop_threshold: float
    entity_relation_multi_hop_threshold: float
    subgraph_max_depth: int
    subgraph_max_nodes: int
    multi_hop_max_depth: int
    multi_hop_max_nodes: int
    entity_relation_max_depth: int
    entity_relation_max_nodes: int


@dataclass(slots=True)
class QuerySemanticSettings(ConfigSection):
    scoring: QuerySemanticScoringSettings
    extraction: QuerySemanticExtractionSettings
    routing: QuerySemanticRoutingSettings
    traversal: QuerySemanticTraversalSettings
    adaptive_traversal: QuerySemanticAdaptiveTraversalSettings

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "QuerySemanticSettings":
        payload = dict(data or {})
        return cls(
            scoring=QuerySemanticScoringSettings(**dict(payload.get("scoring") or {})),
            extraction=QuerySemanticExtractionSettings(**dict(payload.get("extraction") or {})),
            routing=QuerySemanticRoutingSettings(**dict(payload.get("routing") or {})),
            traversal=QuerySemanticTraversalSettings(**dict(payload.get("traversal") or {})),
            adaptive_traversal=QuerySemanticAdaptiveTraversalSettings(
                **dict(payload.get("adaptive_traversal") or {})
            ),
        )


@dataclass(slots=True)
class QueryUnderstandingSettings(ConfigSection):
    planner: QueryPlannerSettings
    semantics: QuerySemanticSettings

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "QueryUnderstandingSettings":
        payload = dict(data or {})
        return cls(
            planner=QueryPlannerSettings(**dict(payload.get("planner") or {})),
            semantics=QuerySemanticSettings.from_dict(payload.get("semantics") or {}),
        )


@dataclass(slots=True)
class GenerationSettings(ConfigSection):
    temperature: float
    max_tokens: int
    generation_timeout_seconds: int
    generation_stream_timeout_seconds: int
    generation_latency_budget_seconds: int
    generation_plan_max_tokens: int
    generation_compose_max_tokens: int
    generation_direct_max_tokens: int
    generation_plan_temperature: float
    generation_planner_mode: str
    generation_max_retries: int
    generation_request_retries: int
    generation_stream_retries: int
    generation_evidence_max_chars: int
    generation_enable_two_stage: bool
    generation_two_stage_complexity_threshold: float
    generation_two_stage_relationship_threshold: float
    generation_direct_max_evidence_items: int
    generation_two_stage_max_evidence_items: int
    generation_plan_max_evidence_items: int
    generation_max_graph_paths_per_item: int
    generation_max_evidence_units_per_item: int
    generation_include_document_evidence: bool
    generation_compose_include_content: bool
    generation_fallback_on_timeout: bool


@dataclass(slots=True)
class GraphSettings(ConfigSection):
    enable_semantic_graph_schema: bool
    chunk_size: int
    chunk_overlap: int
    max_graph_depth: int
    graph_rank_base_weight: float
    graph_rank_semantic_relation_weight: float
    graph_rank_evidence_unit_weight: float
    graph_rank_relationship_weight: float
    graph_rank_recipe_presence_weight: float
    graph_rank_query_overlap_weight: float
    entity_linker_limit_per_entity: int
    entity_linker_min_confidence: float
    entity_linker_max_same_name_candidates: int
    entity_linker_query_type_label_priorities: Dict[str, List[str]]
    entity_linker_relation_label_priorities: Dict[str, List[str]]


@dataclass(slots=True)
class ObservabilitySettings(ConfigSection):
    enable_query_tracing: bool
    query_trace_path: str
    query_trace_async_enabled: bool
    query_trace_max_queue_size: int
    query_trace_fingerprint_salt: str = field(default="", repr=False)
    enable_opentelemetry: bool = False
    otel_service_name: str = "graphrag"
    otel_exporter_otlp_endpoint: str = ""
    otel_trace_sample_ratio: float = 1.0
    enable_prometheus: bool = True
    prometheus_public: bool = False


@dataclass(slots=True)
class ApiSettings(ConfigSection):
    auth_enabled: bool = True
    access_token: str = field(default="", repr=False)
    docs_enabled: bool = False
    openapi_enabled: bool = False
    docs_public: bool = False
    openapi_public: bool = False
    max_request_body_bytes: int = 16 * 1024
    max_concurrent_answers: int = 0
    answer_acquire_timeout_seconds: float = 0.25
    stream_executor_max_workers: int = 4
    stream_queue_max_size: int = 64
    serving_hot_refresh_enabled: bool = True
    serving_hot_refresh_interval_seconds: float = 2.0


SECTION_TYPES = {
    "storage": StorageSettings,
    "models": ModelSettings,
    "retrieval": RetrievalSettings,
    "query_understanding": QueryUnderstandingSettings,
    "generation": GenerationSettings,
    "graph": GraphSettings,
    "observability": ObservabilitySettings,
    "api": ApiSettings,
}
SECTION_ORDER = tuple(SECTION_TYPES.keys())
SECTION_FIELD_NAMES = {
    section_name: tuple(field.name for field in dataclass_fields(section_type))
    for section_name, section_type in SECTION_TYPES.items()
}


@dataclass(slots=True)
class GraphRAGConfig:
    """Root configuration with true nested domain sections."""

    storage: StorageSettings
    models: ModelSettings
    retrieval: RetrievalSettings
    query_understanding: QueryUnderstandingSettings
    generation: GenerationSettings
    graph: GraphSettings
    observability: ObservabilitySettings
    api: ApiSettings
    profile_name: str = ""
    profile_path: str = ""
    profile_hash: str = ""

    def __post_init__(self) -> None:
        configured_milvus_dimension = int(self.storage.milvus_dimension or 0)
        embedding_dimension = int(self.models.embedding_dimension)
        if configured_milvus_dimension and configured_milvus_dimension != embedding_dimension:
            raise ValueError(
                "MILVUS_DIMENSION must match EMBEDDING_DIMENSION so the vector store schema "
                "matches the active embedding model."
            )
        self.storage.milvus_dimension = embedding_dimension
        if not self.storage.artifact_manifest_path:
            self.storage.artifact_manifest_path = os.path.join(
                self.storage.index_cache_dir,
                "artifact_manifest.json",
            )
        if not self.storage.build_job_store_path:
            self.storage.build_job_store_path = os.path.join(
                os.path.dirname(self.storage.artifact_manifest_path),
                "build_jobs.json",
            )

    def to_domain_dict(self) -> Dict[str, Dict[str, Any]]:
        return {
            section_name: getattr(self, section_name).to_dict() for section_name in SECTION_ORDER
        }

    def to_dict(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = self.to_domain_dict()
        if self.profile_name:
            payload["profile_name"] = self.profile_name
        if self.profile_path:
            payload["profile_path"] = self.profile_path
        if self.profile_hash:
            payload["profile_hash"] = self.profile_hash
        if payload["models"].get("api_key"):
            payload["models"]["api_key"] = "***"
        if payload["storage"].get("neo4j_password"):
            payload["storage"]["neo4j_password"] = "***"
        if payload["api"].get("access_token"):
            payload["api"]["access_token"] = "***"
        if payload["observability"].get("query_trace_fingerprint_salt"):
            payload["observability"]["query_trace_fingerprint_salt"] = "***"
        return payload

    def with_overrides(self, overrides: Mapping[str, Any]) -> "GraphRAGConfig":
        from .assembly import apply_overrides, build_config_from_domain_dict

        merged = self.to_domain_dict()
        apply_overrides(merged, overrides)
        config = build_config_from_domain_dict(merged)
        config.profile_name = self.profile_name
        config.profile_path = self.profile_path
        config.profile_hash = self.profile_hash
        return config

    @classmethod
    def from_dict(cls, config_dict: Mapping[str, Any]) -> "GraphRAGConfig":
        if isinstance(config_dict, cls):
            return config_dict
        from .assembly import apply_overrides, build_config_from_domain_dict
        from .env import EnvConfigSource
        from .loader import load_config

        base = load_config(source=EnvConfigSource(environ={}))
        merged = base.to_domain_dict()
        apply_overrides(merged, config_dict)
        return build_config_from_domain_dict(merged)


__all__ = [
    "ApiSettings",
    "ConfigSection",
    "GenerationSettings",
    "GraphRAGConfig",
    "GraphSettings",
    "ModelSettings",
    "ObservabilitySettings",
    "QueryPlannerSettings",
    "QuerySemanticAdaptiveTraversalSettings",
    "QuerySemanticExtractionSettings",
    "QuerySemanticRoutingSettings",
    "QuerySemanticScoringSettings",
    "QuerySemanticSettings",
    "QuerySemanticTraversalSettings",
    "QueryUnderstandingSettings",
    "RetrievalSettings",
    "SECTION_FIELD_NAMES",
    "SECTION_ORDER",
    "SECTION_TYPES",
    "StorageSettings",
]
