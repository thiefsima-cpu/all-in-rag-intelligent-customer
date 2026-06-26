"""Configuration models for GraphRAG."""

from __future__ import annotations

import os
from typing import Any, Dict, List, Mapping, Self

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from rag_modules.query_policy import get_query_policy
from rag_modules.query_understanding.registry import (
    default_entity_linker_query_type_priorities,
    default_entity_linker_relation_priorities,
)

from .validation import raise_validation_error

_QUERY_POLICY = get_query_policy()
_PLANNER_DEFAULTS = _QUERY_POLICY.runtime_section("planner")
_SEMANTIC_DEFAULTS = _QUERY_POLICY.runtime_section("semantics")


class ConfigSection(BaseModel):
    """Serializable section base."""

    model_config = ConfigDict(extra="forbid", strict=True, validate_assignment=True)

    def to_dict(self) -> Dict[str, Any]:
        return self.model_dump(mode="python")


class StorageSettings(ConfigSection):
    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = Field(default="password", repr=False)
    neo4j_database: str = "neo4j"
    milvus_host: str = "localhost"
    milvus_port: int = 19530
    milvus_collection_name: str = "cooking_knowledge"
    milvus_dimension: int = Field(default=1024, ge=0)
    enable_index_cache: bool = True
    index_cache_dir: str = "storage/indexes"
    artifact_manifest_path: str = os.path.join("storage/indexes", "artifact_manifest.json")
    milvus_blue_green_enabled: bool = True
    milvus_collection_alias_suffix: str = "__active"
    build_job_store_path: str = os.path.join("storage/indexes", "build_jobs.json")
    neo4j_max_connection_pool_size: int = Field(default=50, ge=1)
    neo4j_connection_acquisition_timeout_seconds: float = 30.0
    neo4j_max_connection_lifetime_seconds: float = 3600.0
    neo4j_connection_timeout_seconds: float = 15.0


class ModelSettings(ConfigSection):
    api_key: str = Field(default="", repr=False)
    llm_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    embedding_base_url: str = (
        "https://dashscope.aliyuncs.com/api/v1/services/embeddings/"
        "multimodal-embedding/multimodal-embedding"
    )
    rerank_base_url: str = (
        "https://dashscope.aliyuncs.com/api/v1/services/rerank/text-rerank/text-rerank"
    )
    embedding_model: str = "qwen3-vl-embedding"
    llm_model: str = "qwen3.7-plus"
    rerank_model: str = "qwen3-vl-rerank"
    embedding_dimension: int = Field(default=1024, ge=1)
    embedding_batch_size: int = 10
    enable_rerank: bool = True
    llm_timeout_seconds: int = 20
    embedding_timeout_seconds: int = 60
    rerank_timeout_seconds: int = 20
    http_pool_connections: int = Field(default=10, ge=1)
    http_pool_maxsize: int = Field(default=20, ge=1)
    circuit_breaker_failure_threshold: int = Field(default=5, ge=1)
    circuit_breaker_recovery_seconds: float = 30.0
    llm_input_cost_per_million_tokens: float = Field(default=0.0, ge=0.0)
    llm_output_cost_per_million_tokens: float = Field(default=0.0, ge=0.0)


class RetrievalSettings(ConfigSection):
    top_k: int = 5
    vector_search_ef: int = 128
    vector_search_max_k: int = 50
    rrf_k: int = 60
    hybrid_default_candidate_multiplier: int = 2
    hybrid_default_candidate_min_candidates: int = 10
    hybrid_constraint_candidate_multiplier: int = 6
    hybrid_constraint_candidate_min_candidates: int = 30
    router_combined_candidate_multiplier: int = 6
    router_combined_candidate_min_candidates: int = 30
    router_graph_supplement_candidate_multiplier: int = 2
    router_graph_supplement_candidate_min_candidates: int = 10
    retrieval_preserve_graph_evidence: bool = True
    enable_parent_doc_retrieval: bool = True
    parent_doc_top_n: int = 3
    parent_doc_max_chars: int = 4000
    candidate_source_failure_threshold: int = Field(default=1, ge=1)
    candidate_source_recovery_seconds: float = Field(default=30.0, ge=0.1)
    candidate_source_degradation_strategy: str = "continue"


class QueryPlannerSettings(ConfigSection):
    cache_size: int = int(_PLANNER_DEFAULTS.get("cache_size", 128))
    fast_rule_planning: bool = bool(_PLANNER_DEFAULTS.get("fast_rule_planning", True))
    llm_temperature: float = float(_PLANNER_DEFAULTS.get("llm_temperature", 0.0))
    llm_max_tokens: int = int(_PLANNER_DEFAULTS.get("llm_max_tokens", 1200))


class QuerySemanticScoringSettings(ConfigSection):
    relation_intensity_reference_ratio: float = float(
        _SEMANTIC_DEFAULTS.get("relation_intensity_reference_ratio", 0.5)
    )
    complexity_relation_hit_weight: float = float(
        _SEMANTIC_DEFAULTS.get("complexity_relation_hit_weight", 0.14)
    )
    complexity_constraint_hit_weight: float = float(
        _SEMANTIC_DEFAULTS.get("complexity_constraint_hit_weight", 0.1)
    )
    complexity_structural_hit_weight: float = float(
        _SEMANTIC_DEFAULTS.get("complexity_structural_hit_weight", 0.12)
    )
    complexity_length_weight: float = float(
        _SEMANTIC_DEFAULTS.get("complexity_length_weight", 0.28)
    )
    complexity_length_norm_chars: int = int(
        _SEMANTIC_DEFAULTS.get("complexity_length_norm_chars", 140)
    )
    reasoning_complexity_threshold: float = float(
        _SEMANTIC_DEFAULTS.get("reasoning_complexity_threshold", 0.7)
    )
    reasoning_relationship_threshold: float = float(
        _SEMANTIC_DEFAULTS.get("reasoning_relationship_threshold", 0.4)
    )
    relation_hit_intensity_boost_base: float = float(
        _SEMANTIC_DEFAULTS.get("relation_hit_intensity_boost_base", 0.45)
    )
    relation_hit_intensity_boost_step: float = float(
        _SEMANTIC_DEFAULTS.get("relation_hit_intensity_boost_step", 0.12)
    )
    relation_hit_complexity_boost_base: float = float(
        _SEMANTIC_DEFAULTS.get("relation_hit_complexity_boost_base", 0.55)
    )
    relation_hit_complexity_boost_step: float = float(
        _SEMANTIC_DEFAULTS.get("relation_hit_complexity_boost_step", 0.08)
    )


class QuerySemanticExtractionSettings(ConfigSection):
    source_entity_limit: int = int(_SEMANTIC_DEFAULTS.get("source_entity_limit", 3))
    entity_keyword_limit: int = int(_SEMANTIC_DEFAULTS.get("entity_keyword_limit", 4))
    semantic_profile_entity_keyword_limit: int = int(
        _SEMANTIC_DEFAULTS.get("semantic_profile_entity_keyword_limit", 6)
    )
    topic_keyword_limit: int = int(_SEMANTIC_DEFAULTS.get("topic_keyword_limit", 4))
    semantic_profile_topic_keyword_start: int = int(
        _SEMANTIC_DEFAULTS.get("semantic_profile_topic_keyword_start", 4)
    )
    semantic_profile_topic_keyword_limit: int = int(
        _SEMANTIC_DEFAULTS.get("semantic_profile_topic_keyword_limit", 6)
    )
    target_entity_limit: int = int(_SEMANTIC_DEFAULTS.get("target_entity_limit", 2))


class QuerySemanticRoutingSettings(ConfigSection):
    high_relationship_routing_threshold: float = float(
        _SEMANTIC_DEFAULTS.get("high_relationship_routing_threshold", 0.7)
    )
    multi_hop_hint_entity_count: int = int(
        _SEMANTIC_DEFAULTS.get("multi_hop_hint_entity_count", 2)
    )
    multi_hop_hint_relationship_threshold: float = float(
        _SEMANTIC_DEFAULTS.get("multi_hop_hint_relationship_threshold", 0.55)
    )
    combined_strategy_relationship_threshold: float = float(
        _SEMANTIC_DEFAULTS.get("combined_strategy_relationship_threshold", 0.4)
    )
    combined_strategy_complexity_threshold: float = float(
        _SEMANTIC_DEFAULTS.get("combined_strategy_complexity_threshold", 0.6)
    )
    source_entity_seed_relationship_threshold: float = float(
        _SEMANTIC_DEFAULTS.get("source_entity_seed_relationship_threshold", 0.4)
    )
    source_entity_backfill_relationship_threshold: float = float(
        _SEMANTIC_DEFAULTS.get("source_entity_backfill_relationship_threshold", 0.55)
    )
    rule_fallback_confidence: float = float(
        _SEMANTIC_DEFAULTS.get("rule_fallback_confidence", 0.45)
    )


class QuerySemanticTraversalSettings(ConfigSection):
    entity_relation_max_depth: int = int(
        _SEMANTIC_DEFAULTS.get("entity_relation_max_depth", 1)
    )
    path_finding_max_depth: int = int(_SEMANTIC_DEFAULTS.get("path_finding_max_depth", 3))
    path_finding_high_intensity_max_depth: int = int(
        _SEMANTIC_DEFAULTS.get("path_finding_high_intensity_max_depth", 4)
    )
    path_finding_high_intensity_threshold: float = float(
        _SEMANTIC_DEFAULTS.get("path_finding_high_intensity_threshold", 0.6)
    )
    subgraph_max_depth: int = int(_SEMANTIC_DEFAULTS.get("subgraph_max_depth", 2))
    subgraph_high_intensity_max_depth: int = int(
        _SEMANTIC_DEFAULTS.get("subgraph_high_intensity_max_depth", 3)
    )
    subgraph_high_intensity_threshold: float = float(
        _SEMANTIC_DEFAULTS.get("subgraph_high_intensity_threshold", 0.5)
    )
    clustering_max_depth: int = int(_SEMANTIC_DEFAULTS.get("clustering_max_depth", 3))
    default_max_depth: int = int(_SEMANTIC_DEFAULTS.get("default_max_depth", 2))
    default_high_intensity_max_depth: int = int(
        _SEMANTIC_DEFAULTS.get("default_high_intensity_max_depth", 3)
    )
    default_high_intensity_threshold: float = float(
        _SEMANTIC_DEFAULTS.get("default_high_intensity_threshold", 0.7)
    )
    entity_relation_max_nodes: int = int(_SEMANTIC_DEFAULTS.get("entity_relation_max_nodes", 20))
    path_finding_max_nodes: int = int(_SEMANTIC_DEFAULTS.get("path_finding_max_nodes", 40))
    subgraph_max_nodes: int = int(_SEMANTIC_DEFAULTS.get("subgraph_max_nodes", 80))
    clustering_max_nodes: int = int(_SEMANTIC_DEFAULTS.get("clustering_max_nodes", 60))
    default_max_nodes: int = int(_SEMANTIC_DEFAULTS.get("default_max_nodes", 50))
    graph_query_max_depth_cap: int = int(
        _SEMANTIC_DEFAULTS.get("graph_query_max_depth_cap", 4)
    )
    graph_query_fallback_name_chars: int = int(
        _SEMANTIC_DEFAULTS.get("graph_query_fallback_name_chars", 16)
    )


class QuerySemanticAdaptiveTraversalSettings(ConfigSection):
    multi_hop_subgraph_threshold: float = float(
        _SEMANTIC_DEFAULTS.get("adaptive_multi_hop_subgraph_threshold", 0.7)
    )
    subgraph_multi_hop_threshold: float = float(
        _SEMANTIC_DEFAULTS.get("adaptive_subgraph_multi_hop_threshold", 0.45)
    )
    entity_relation_multi_hop_threshold: float = float(
        _SEMANTIC_DEFAULTS.get("adaptive_entity_relation_multi_hop_threshold", 0.5)
    )
    subgraph_max_depth: int = int(_SEMANTIC_DEFAULTS.get("adaptive_subgraph_max_depth", 3))
    subgraph_max_nodes: int = int(_SEMANTIC_DEFAULTS.get("adaptive_subgraph_max_nodes", 100))
    multi_hop_max_depth: int = int(_SEMANTIC_DEFAULTS.get("adaptive_multi_hop_max_depth", 3))
    multi_hop_max_nodes: int = int(_SEMANTIC_DEFAULTS.get("adaptive_multi_hop_max_nodes", 50))
    entity_relation_max_depth: int = int(
        _SEMANTIC_DEFAULTS.get("adaptive_entity_relation_max_depth", 2)
    )
    entity_relation_max_nodes: int = int(
        _SEMANTIC_DEFAULTS.get("adaptive_entity_relation_max_nodes", 40)
    )


class QuerySemanticSettings(ConfigSection):
    scoring: QuerySemanticScoringSettings = Field(
        default_factory=QuerySemanticScoringSettings
    )
    extraction: QuerySemanticExtractionSettings = Field(
        default_factory=QuerySemanticExtractionSettings
    )
    routing: QuerySemanticRoutingSettings = Field(default_factory=QuerySemanticRoutingSettings)
    traversal: QuerySemanticTraversalSettings = Field(
        default_factory=QuerySemanticTraversalSettings
    )
    adaptive_traversal: QuerySemanticAdaptiveTraversalSettings = Field(
        default_factory=QuerySemanticAdaptiveTraversalSettings
    )

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Self:
        return cls.model_validate(dict(data or {}))


class QueryUnderstandingSettings(ConfigSection):
    planner: QueryPlannerSettings = Field(default_factory=QueryPlannerSettings)
    semantics: QuerySemanticSettings = Field(default_factory=QuerySemanticSettings)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Self:
        return cls.model_validate(dict(data or {}))


class GenerationSettings(ConfigSection):
    temperature: float = 0.1
    max_tokens: int = 2048
    generation_timeout_seconds: int = 25
    generation_stream_timeout_seconds: int = 25
    generation_latency_budget_seconds: int = 24
    generation_plan_max_tokens: int = 600
    generation_compose_max_tokens: int = 1100
    generation_direct_max_tokens: int = 700
    generation_plan_temperature: float = 0.0
    generation_planner_mode: str = "rule"
    generation_max_retries: int = 1
    generation_request_retries: int = 1
    generation_stream_retries: int = 1
    generation_evidence_max_chars: int = 700
    generation_enable_two_stage: bool = True
    generation_two_stage_complexity_threshold: float = 0.68
    generation_two_stage_relationship_threshold: float = 0.58
    generation_direct_max_evidence_items: int = 2
    generation_two_stage_max_evidence_items: int = 3
    generation_plan_max_evidence_items: int = 2
    generation_max_graph_paths_per_item: int = 1
    generation_max_evidence_units_per_item: int = 4
    generation_include_document_evidence: bool = False
    generation_compose_include_content: bool = False
    generation_fallback_on_timeout: bool = False


class GraphSettings(ConfigSection):
    enable_semantic_graph_schema: bool = True
    chunk_size: int = 500
    chunk_overlap: int = 50
    max_graph_depth: int = 2
    graph_rank_base_weight: float = 1.0
    graph_rank_semantic_relation_weight: float = 0.08
    graph_rank_evidence_unit_weight: float = 0.03
    graph_rank_relationship_weight: float = 0.01
    graph_rank_recipe_presence_weight: float = 0.1
    graph_rank_query_overlap_weight: float = 0.02
    entity_linker_limit_per_entity: int = 4
    entity_linker_min_confidence: float = 0.45
    entity_linker_max_same_name_candidates: int = 2
    entity_linker_query_type_label_priorities: Dict[str, List[str]] = Field(
        default_factory=default_entity_linker_query_type_priorities
    )
    entity_linker_relation_label_priorities: Dict[str, List[str]] = Field(
        default_factory=default_entity_linker_relation_priorities
    )


class ObservabilitySettings(ConfigSection):
    enable_query_tracing: bool = True
    query_trace_path: str = "storage/traces/query_trace.jsonl"
    query_trace_async_enabled: bool = True
    query_trace_max_queue_size: int = 256
    query_trace_fingerprint_salt: str = Field(default="", repr=False)
    enable_opentelemetry: bool = False
    otel_service_name: str = "graphrag"
    otel_exporter_otlp_endpoint: str = ""
    otel_trace_sample_ratio: float = Field(default=1.0, ge=0.0, le=1.0)
    enable_prometheus: bool = True
    prometheus_public: bool = False


class ApiSettings(ConfigSection):
    auth_enabled: bool = True
    access_token: str = Field(default="", repr=False)
    docs_enabled: bool = False
    openapi_enabled: bool = False
    docs_public: bool = False
    openapi_public: bool = False
    max_request_body_bytes: int = Field(default=16 * 1024, ge=1024)
    max_concurrent_answers: int = Field(default=0, ge=0)
    answer_acquire_timeout_seconds: float = Field(default=0.25, ge=0.0)
    stream_executor_max_workers: int = Field(default=4, ge=1)
    stream_queue_max_size: int = Field(default=64, ge=1)
    serving_hot_refresh_enabled: bool = True
    serving_hot_refresh_interval_seconds: float = Field(default=2.0, ge=0.1)


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
    section_name: tuple(section_type.model_fields) for section_name, section_type in SECTION_TYPES.items()
}


class GraphRAGConfig(BaseModel):
    """Root configuration with true nested domain sections."""

    model_config = ConfigDict(extra="forbid", strict=True, validate_assignment=True)

    storage: StorageSettings = Field(default_factory=StorageSettings)
    models: ModelSettings = Field(default_factory=ModelSettings)
    retrieval: RetrievalSettings = Field(default_factory=RetrievalSettings)
    query_understanding: QueryUnderstandingSettings = Field(
        default_factory=QueryUnderstandingSettings
    )
    generation: GenerationSettings = Field(default_factory=GenerationSettings)
    graph: GraphSettings = Field(default_factory=GraphSettings)
    observability: ObservabilitySettings = Field(default_factory=ObservabilitySettings)
    api: ApiSettings = Field(default_factory=ApiSettings)
    profile_name: str = ""
    profile_path: str = ""
    profile_hash: str = ""

    @model_validator(mode="after")
    def _normalize_derived_storage_fields(self) -> Self:
        configured_milvus_dimension = int(self.storage.milvus_dimension or 0)
        embedding_dimension = int(self.models.embedding_dimension)
        if configured_milvus_dimension and configured_milvus_dimension != embedding_dimension:
            message = (
                "MILVUS_DIMENSION must match EMBEDDING_DIMENSION so the vector store schema "
                "matches the active embedding model."
            )
            raise ValidationError.from_exception_data(
                self.__class__.__name__,
                [
                    {
                        "type": "value_error",
                        "loc": ("storage", "milvus_dimension"),
                        "msg": message,
                        "input": configured_milvus_dimension,
                        "ctx": {"error": ValueError(message)},
                    },
                    {
                        "type": "value_error",
                        "loc": ("models", "embedding_dimension"),
                        "msg": message,
                        "input": embedding_dimension,
                        "ctx": {"error": ValueError(message)},
                    },
                ],
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
        return self

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
        from .assembly import apply_overrides

        merged = self.to_domain_dict()
        apply_overrides(merged, overrides)
        try:
            return self.__class__.model_validate(
                {
                    **merged,
                    "profile_name": self.profile_name,
                    "profile_path": self.profile_path,
                    "profile_hash": self.profile_hash,
                }
            )
        except ValidationError as exc:
            raise_validation_error(
                exc,
                source_kind="overrides",
                source="GraphRAGConfig.with_overrides",
            )

    @classmethod
    def from_dict(cls, config_dict: Mapping[str, Any]) -> "GraphRAGConfig":
        if isinstance(config_dict, cls):
            return config_dict

        from .assembly import apply_overrides

        payload = dict(config_dict or {})
        profile_metadata = {
            key: str(payload.pop(key, ""))
            for key in ("profile_name", "profile_path", "profile_hash")
        }
        merged = cls().to_domain_dict()
        apply_overrides(merged, payload)
        try:
            return cls.model_validate({**merged, **profile_metadata})
        except ValidationError as exc:
            raise_validation_error(
                exc,
                source_kind="overrides",
                source="GraphRAGConfig.from_dict",
            )


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
