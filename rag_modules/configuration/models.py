"""Configuration models for GraphRAG."""

from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Dict, List, Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

from ..domains import get_domain_pack
from ..kernel.json_types import JsonObject, coerce_json_object
from ..kernel.retrieval import (
    CandidateSourceDegradationStrategy,
    candidate_source_degradation_strategy,
)


class ConfigSection(BaseModel):
    """Serializable section base."""

    model_config = ConfigDict(extra="forbid", strict=True, validate_assignment=True)

    def to_dict(self) -> JsonObject:
        return coerce_json_object(self.model_dump(mode="json"))


class ApiSettings(ConfigSection):
    auth_enabled: bool = True
    access_token: str = Field(default="", repr=False)
    docs_enabled: bool = False
    openapi_enabled: bool = False
    docs_public: bool = False
    openapi_public: bool = False
    max_request_body_bytes: int = Field(default=16 * 1024, ge=1024)
    max_concurrent_answers: int = Field(default=4, ge=1)
    answer_acquire_timeout_seconds: float = Field(default=0.25, ge=0.0)
    stream_executor_max_workers: int = Field(default=4, ge=1)
    stream_executor_max_outstanding: int = Field(default=8, ge=1)
    stream_event_queue_max_size: int = Field(default=64, ge=1)
    build_job_runner_backend: Literal["in_process", "external_worker"] = "in_process"
    build_job_runner_max_workers: int = Field(default=1, ge=1)
    build_job_worker_poll_interval_seconds: float = Field(default=1.0, ge=0.1)
    build_job_lease_seconds: float = Field(default=30.0, ge=1.0)
    build_job_heartbeat_seconds: float = Field(default=10.0, ge=0.1)
    build_job_retention_limit: int = Field(default=100, ge=1)
    build_job_list_default_limit: int = Field(default=50, ge=1)
    build_job_list_max_limit: int = Field(default=100, ge=1)
    build_job_repository_backend: Literal["file", "postgresql"] = "file"
    build_job_audit_retention_days: int = Field(default=90, ge=1)
    build_job_postgres_pool_min_size: int = Field(default=1, ge=1)
    build_job_postgres_pool_max_size: int = Field(default=10, ge=1)
    build_job_postgres_pool_timeout_seconds: float = Field(default=5.0, gt=0.0)
    serving_hot_refresh_enabled: bool = True
    serving_hot_refresh_interval_seconds: float = Field(default=2.0, ge=0.1)

    @model_validator(mode="after")
    def _validate_build_job_limits(self) -> Self:
        if self.build_job_list_default_limit > self.build_job_list_max_limit:
            raise ValueError(
                "api.build_job_list_default_limit must be less than or equal to "
                "api.build_job_list_max_limit."
            )
        if self.build_job_heartbeat_seconds >= self.build_job_lease_seconds:
            raise ValueError(
                "api.build_job_heartbeat_seconds must be less than api.build_job_lease_seconds."
            )
        if self.stream_executor_max_outstanding < self.stream_executor_max_workers:
            raise ValueError(
                "api.stream_executor_max_outstanding must be greater than or equal to "
                "api.stream_executor_max_workers."
            )
        if self.build_job_postgres_pool_min_size > self.build_job_postgres_pool_max_size:
            raise ValueError(
                "api.build_job_postgres_pool_min_size must be less than or equal to "
                "api.build_job_postgres_pool_max_size."
            )
        return self


_GENERATION_PLANNER_MODE_VALUES = ("rule", "hybrid", "llm")
_DEFAULT_GENERATION_PLANNER_MODE = "rule"


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

    @model_validator(mode="after")
    def normalize_generation_planner_mode(self) -> Self:
        normalized = self.generation_planner_mode.strip().lower() or (
            _DEFAULT_GENERATION_PLANNER_MODE
        )
        if normalized not in _GENERATION_PLANNER_MODE_VALUES:
            supported = ", ".join(_GENERATION_PLANNER_MODE_VALUES)
            raise ValueError(f"generation_planner_mode must be one of: {supported}") from None
        object.__setattr__(self, "generation_planner_mode", normalized)
        return self


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
    entity_linker_query_type_label_priorities: Dict[str, List[str]] = Field(default_factory=dict)
    entity_linker_relation_label_priorities: Dict[str, List[str]] = Field(default_factory=dict)


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
    llm_model: str
    llm_enable_thinking: bool | None = None
    rerank_model: str = "qwen3-vl-rerank"
    embedding_dimension: int = Field(default=1024, ge=1)
    embedding_batch_size: int = 10
    enable_rerank: bool = True
    llm_timeout_seconds: int
    embedding_timeout_seconds: int = 60
    rerank_timeout_seconds: int = 20
    http_pool_connections: int = Field(default=10, ge=1)
    http_pool_maxsize: int = Field(default=20, ge=1)
    circuit_breaker_failure_threshold: int = Field(default=5, ge=1)
    circuit_breaker_recovery_seconds: float = 30.0
    llm_input_cost_per_million_tokens: float = Field(default=0.0, ge=0.0)
    llm_output_cost_per_million_tokens: float = Field(default=0.0, ge=0.0)


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


class QueryPolicySelectorSettings(ConfigSection):
    bundle: str = "c9-default-v1"
    bundle_path: str = ""


class QueryPlannerSettings(ConfigSection):
    cache_size: int
    fast_rule_planning: bool
    llm_temperature: float
    llm_max_tokens: int


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


class QuerySemanticExtractionSettings(ConfigSection):
    source_entity_limit: int
    entity_keyword_limit: int
    semantic_profile_entity_keyword_limit: int
    topic_keyword_limit: int
    semantic_profile_topic_keyword_start: int
    semantic_profile_topic_keyword_limit: int
    target_entity_limit: int


class QuerySemanticRoutingSettings(ConfigSection):
    high_relationship_routing_threshold: float
    multi_hop_hint_entity_count: int
    multi_hop_hint_relationship_threshold: float
    combined_strategy_relationship_threshold: float
    combined_strategy_complexity_threshold: float
    source_entity_seed_relationship_threshold: float
    source_entity_backfill_relationship_threshold: float
    rule_fallback_confidence: float


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


class QuerySemanticSettings(ConfigSection):
    scoring: QuerySemanticScoringSettings
    extraction: QuerySemanticExtractionSettings
    routing: QuerySemanticRoutingSettings
    traversal: QuerySemanticTraversalSettings
    adaptive_traversal: QuerySemanticAdaptiveTraversalSettings

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> Self:
        return cls.model_validate(dict(data or {}))


class QueryUnderstandingSettings(ConfigSection):
    policy: QueryPolicySelectorSettings = Field(default_factory=QueryPolicySelectorSettings)
    planner: QueryPlannerSettings
    semantics: QuerySemanticSettings

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> Self:
        return cls.model_validate(dict(data or {}))


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
    retrieval_graph_preservation_strategies: list[str] = ["graph_rag", "combined"]
    enable_parent_doc_retrieval: bool = True
    parent_doc_top_n: int = 3
    parent_doc_max_chars: int = 4000
    candidate_source_failure_threshold: int = Field(ge=1)
    candidate_source_recovery_seconds: float = Field(ge=0.1)
    candidate_source_degradation_strategy: str

    @model_validator(mode="after")
    def normalize_degradation_strategy(self) -> Self:
        try:
            strategy = candidate_source_degradation_strategy(
                self.candidate_source_degradation_strategy
            )
        except ValueError:
            supported = ", ".join(strategy.value for strategy in CandidateSourceDegradationStrategy)
            raise ValueError(
                f"candidate_source_degradation_strategy must be one of: {supported}"
            ) from None
        object.__setattr__(self, "candidate_source_degradation_strategy", strategy.value)
        return self


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
    artifact_manifest_path: str = ""
    milvus_blue_green_enabled: bool = True
    milvus_collection_alias_suffix: str = "__active"
    build_job_store_path: str = ""
    build_job_postgres_dsn: str = Field(default="", repr=False)
    neo4j_max_connection_pool_size: int = Field(default=50, ge=1)
    neo4j_connection_acquisition_timeout_seconds: float = 30.0
    neo4j_max_connection_lifetime_seconds: float = 3600.0
    neo4j_connection_timeout_seconds: float = 15.0


class DomainSettings(ConfigSection):
    """Select the versioned business-domain behavior pack."""

    name: str = "recipe"

    @field_validator("name")
    @classmethod
    def validate_domain_pack_name(cls, value: str) -> str:
        return get_domain_pack(value).name


SECTION_TYPES: dict[str, type[ConfigSection]] = {
    "domain": DomainSettings,
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
    section_name: tuple(section_type.model_fields)
    for section_name, section_type in SECTION_TYPES.items()
}


def default_domain_payload() -> JsonObject:
    return {
        section_name: section_type.model_construct().to_dict()
        for section_name, section_type in SECTION_TYPES.items()
    }


def _clear_storage_derived_paths_for_overrides(
    domain_payload: dict[str, object],
    overrides: Mapping[str, object],
) -> None:
    storage_overrides = overrides.get("storage")
    storage_payload = domain_payload.get("storage")
    if not isinstance(storage_overrides, Mapping) or not isinstance(storage_payload, dict):
        return

    index_cache_changed = "index_cache_dir" in storage_overrides
    artifact_manifest_changed = "artifact_manifest_path" in storage_overrides
    if index_cache_changed and not artifact_manifest_changed:
        storage_payload["artifact_manifest_path"] = ""
    if (index_cache_changed or artifact_manifest_changed) and (
        "build_job_store_path" not in storage_overrides
    ):
        storage_payload["build_job_store_path"] = ""


class GraphRAGConfig(BaseModel):
    """Root configuration with true nested domain sections."""

    model_config = ConfigDict(extra="forbid", strict=True, validate_assignment=True)

    domain: DomainSettings = Field(default_factory=DomainSettings)
    storage: StorageSettings = Field(default_factory=StorageSettings)
    models: ModelSettings
    retrieval: RetrievalSettings
    query_understanding: QueryUnderstandingSettings
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
                        "input": configured_milvus_dimension,
                        "ctx": {"error": ValueError(message)},
                    },
                    {
                        "type": "value_error",
                        "loc": ("models", "embedding_dimension"),
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

    def to_domain_dict(self) -> JsonObject:
        return {
            "domain": self.domain.to_dict(),
            "storage": self.storage.to_dict(),
            "models": self.models.to_dict(),
            "retrieval": self.retrieval.to_dict(),
            "query_understanding": self.query_understanding.to_dict(),
            "generation": self.generation.to_dict(),
            "graph": self.graph.to_dict(),
            "observability": self.observability.to_dict(),
            "api": self.api.to_dict(),
        }

    def to_dict(self) -> JsonObject:
        payload = self.to_domain_dict()
        if self.profile_name:
            payload["profile_name"] = self.profile_name
        if self.profile_path:
            payload["profile_path"] = self.profile_path
        if self.profile_hash:
            payload["profile_hash"] = self.profile_hash
        _redact_secret(payload, "models", "api_key")
        _redact_secret(payload, "storage", "neo4j_password")
        _redact_secret(payload, "storage", "build_job_postgres_dsn")
        _redact_secret(payload, "api", "access_token")
        _redact_secret(payload, "observability", "query_trace_fingerprint_salt")
        return payload

    def with_overrides(self, overrides: Mapping[str, object]) -> "GraphRAGConfig":
        merged: dict[str, object] = dict(self.to_domain_dict())
        _clear_storage_derived_paths_for_overrides(merged, overrides)
        from .assembly import merge_overrides
        from .env import EnvConfigSource
        from .loader import load_config

        merge_overrides(merged, overrides)
        config = load_config(
            overrides=merged,
            source=EnvConfigSource(environ={}),
            _overrides_source="GraphRAGConfig.with_overrides",
        )
        config.profile_name = self.profile_name
        config.profile_path = self.profile_path
        config.profile_hash = self.profile_hash
        return config

    @classmethod
    def from_dict(cls, config_dict: Mapping[str, object]) -> "GraphRAGConfig":
        if isinstance(config_dict, cls):
            return config_dict

        payload = dict(config_dict or {})
        profile_metadata = {
            key: str(payload.pop(key, ""))
            for key in ("profile_name", "profile_path", "profile_hash")
        }
        from .env import EnvConfigSource
        from .loader import load_config

        config = load_config(
            overrides=payload,
            source=EnvConfigSource(environ={}),
            _overrides_source="GraphRAGConfig.from_dict",
        )
        config.profile_name = profile_metadata["profile_name"]
        config.profile_path = profile_metadata["profile_path"]
        config.profile_hash = profile_metadata["profile_hash"]
        return config


def _redact_secret(payload: JsonObject, section_name: str, field_name: str) -> None:
    section = payload.get(section_name)
    if isinstance(section, dict) and section.get(field_name):
        section[field_name] = "***"


__all__ = [
    "ApiSettings",
    "ConfigSection",
    "DomainSettings",
    "GenerationSettings",
    "GraphRAGConfig",
    "GraphSettings",
    "ModelSettings",
    "ObservabilitySettings",
    "QueryPolicySelectorSettings",
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
