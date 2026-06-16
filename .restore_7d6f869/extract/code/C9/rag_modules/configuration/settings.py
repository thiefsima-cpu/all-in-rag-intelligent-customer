"""Domain configuration objects and loaders for GraphRAG."""

from __future__ import annotations

import os
from dataclasses import dataclass, fields as dataclass_fields
from typing import Any, Dict, List, Mapping

from dotenv import load_dotenv

from rag_modules.query_semantics import (
    default_entity_linker_query_type_priorities,
    default_entity_linker_relation_priorities,
)

from .env import EnvConfigSource, default_env_source


class ConfigSection:
    """Serializable section base."""

    def to_dict(self) -> Dict[str, Any]:
        return {field.name: getattr(self, field.name) for field in dataclass_fields(self)}


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


@dataclass(slots=True)
class QueryUnderstandingSettings(ConfigSection):
    query_plan_cache_size: int
    fast_rule_query_planning: bool
    query_planner_llm_temperature: float
    query_planner_llm_max_tokens: int
    query_plan_reasoning_complexity_threshold: float
    query_plan_reasoning_relationship_threshold: float
    query_plan_relation_intensity_base: float
    query_plan_relation_intensity_step: float
    query_plan_complexity_base: float
    query_plan_complexity_step: float
    query_plan_source_entity_limit: int
    query_plan_entity_keyword_limit: int
    query_plan_topic_keyword_limit: int
    query_plan_target_entity_limit: int
    query_plan_multi_hop_hint_entity_count: int
    query_plan_multi_hop_hint_relationship_threshold: float
    query_plan_combined_strategy_relationship_threshold: float
    query_plan_combined_strategy_complexity_threshold: float
    query_plan_source_entity_seed_relationship_threshold: float
    query_plan_source_entity_backfill_relationship_threshold: float
    query_plan_rule_fallback_confidence: float
    query_semantic_relation_intensity_reference_ratio: float
    query_semantic_complexity_relation_hit_weight: float
    query_semantic_complexity_constraint_hit_weight: float
    query_semantic_complexity_structural_hit_weight: float
    query_semantic_complexity_length_weight: float
    query_semantic_complexity_length_norm_chars: int
    query_semantic_reasoning_complexity_threshold: float
    query_semantic_reasoning_relationship_threshold: float
    query_semantic_high_relationship_routing_threshold: float
    query_semantic_relation_hit_intensity_boost_base: float
    query_semantic_relation_hit_intensity_boost_step: float
    query_semantic_relation_hit_complexity_boost_base: float
    query_semantic_relation_hit_complexity_boost_step: float
    query_semantic_source_entity_limit: int
    query_semantic_entity_keyword_limit: int
    query_semantic_profile_entity_keyword_limit: int
    query_semantic_topic_keyword_limit: int
    query_semantic_profile_topic_keyword_start: int
    query_semantic_profile_topic_keyword_limit: int
    query_semantic_target_entity_limit: int
    query_semantic_multi_hop_hint_entity_count: int
    query_semantic_multi_hop_hint_relationship_threshold: float
    query_semantic_combined_strategy_relationship_threshold: float
    query_semantic_combined_strategy_complexity_threshold: float
    query_semantic_source_entity_seed_relationship_threshold: float
    query_semantic_source_entity_backfill_relationship_threshold: float
    query_semantic_rule_fallback_confidence: float
    query_semantic_entity_relation_max_depth: int
    query_semantic_path_finding_max_depth: int
    query_semantic_path_finding_high_intensity_max_depth: int
    query_semantic_path_finding_high_intensity_threshold: float
    query_semantic_subgraph_max_depth: int
    query_semantic_subgraph_high_intensity_max_depth: int
    query_semantic_subgraph_high_intensity_threshold: float
    query_semantic_clustering_max_depth: int
    query_semantic_default_max_depth: int
    query_semantic_default_high_intensity_max_depth: int
    query_semantic_default_high_intensity_threshold: float
    query_semantic_entity_relation_max_nodes: int
    query_semantic_path_finding_max_nodes: int
    query_semantic_subgraph_max_nodes: int
    query_semantic_clustering_max_nodes: int
    query_semantic_default_max_nodes: int
    query_semantic_graph_query_max_depth_cap: int
    query_semantic_graph_query_fallback_name_chars: int
    query_semantic_adaptive_multi_hop_subgraph_threshold: float
    query_semantic_adaptive_subgraph_multi_hop_threshold: float
    query_semantic_adaptive_entity_relation_multi_hop_threshold: float
    query_semantic_adaptive_subgraph_max_depth: int
    query_semantic_adaptive_subgraph_max_nodes: int
    query_semantic_adaptive_multi_hop_max_depth: int
    query_semantic_adaptive_multi_hop_max_nodes: int
    query_semantic_adaptive_entity_relation_max_depth: int
    query_semantic_adaptive_entity_relation_max_nodes: int


@dataclass(slots=True)
class GenerationSettings(ConfigSection):
    temperature: float
    max_tokens: int
    generation_timeout_seconds: int
    generation_stream_timeout_seconds: int
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


SECTION_TYPES = {
    "storage": StorageSettings,
    "models": ModelSettings,
    "retrieval": RetrievalSettings,
    "query_understanding": QueryUnderstandingSettings,
    "generation": GenerationSettings,
    "graph": GraphSettings,
    "observability": ObservabilitySettings,
}
SECTION_ORDER = tuple(SECTION_TYPES.keys())
SECTION_FIELD_NAMES = {
    section_name: tuple(field.name for field in dataclass_fields(section_type))
    for section_name, section_type in SECTION_TYPES.items()
}
FLAT_FIELD_TO_SECTION = {
    field_name: section_name
    for section_name, field_names in SECTION_FIELD_NAMES.items()
    for field_name in field_names
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

    def __post_init__(self) -> None:
        self.storage.milvus_dimension = self.models.embedding_dimension
        if not self.storage.artifact_manifest_path:
            self.storage.artifact_manifest_path = os.path.join(
                self.storage.index_cache_dir,
                "artifact_manifest.json",
            )

    def __getattr__(self, name: str) -> Any:
        section_name = FLAT_FIELD_TO_SECTION.get(name)
        if section_name is None:
            raise AttributeError(f"{self.__class__.__name__!s} has no attribute {name!r}")
        return getattr(getattr(self, section_name), name)

    def __dir__(self) -> List[str]:
        return sorted(set(super().__dir__()) | set(FLAT_FIELD_TO_SECTION))

    def to_domain_dict(self) -> Dict[str, Dict[str, Any]]:
        return {
            section_name: getattr(self, section_name).to_dict()
            for section_name in SECTION_ORDER
        }

    def to_dict(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = {}
        for section_name in SECTION_ORDER:
            payload.update(getattr(self, section_name).to_dict())
        if payload.get("api_key"):
            payload["api_key"] = "***"
        return payload

    def with_overrides(self, overrides: Mapping[str, Any]) -> "GraphRAGConfig":
        merged = self.to_domain_dict()
        _apply_overrides(merged, overrides)
        return _build_config_from_domain_dict(merged)

    @classmethod
    def from_dict(cls, config_dict: Mapping[str, Any]) -> "GraphRAGConfig":
        if isinstance(config_dict, GraphRAGConfig):
            return config_dict
        base = load_config()
        merged = base.to_domain_dict()
        _apply_overrides(merged, config_dict)
        return _build_config_from_domain_dict(merged)


def _apply_overrides(domain_payload: Dict[str, Dict[str, Any]], overrides: Mapping[str, Any]) -> None:
    unknown_fields: List[str] = []

    for section_name in SECTION_ORDER:
        nested = overrides.get(section_name)
        if nested is None:
            continue
        if not isinstance(nested, Mapping):
            raise TypeError(f"Config section {section_name!r} must be a mapping.")
        for key, value in nested.items():
            if key not in SECTION_FIELD_NAMES[section_name]:
                unknown_fields.append(f"{section_name}.{key}")
                continue
            domain_payload[section_name][key] = value

    for key, value in overrides.items():
        if key in SECTION_ORDER:
            continue
        section_name = FLAT_FIELD_TO_SECTION.get(str(key))
        if section_name is None:
            unknown_fields.append(str(key))
            continue
        domain_payload[section_name][str(key)] = value

    if unknown_fields:
        unknown_fields.sort()
        raise KeyError(f"Unknown configuration fields: {', '.join(unknown_fields)}")


def _build_config_from_domain_dict(domain_payload: Mapping[str, Mapping[str, Any]]) -> GraphRAGConfig:
    return GraphRAGConfig(
        storage=StorageSettings(**dict(domain_payload["storage"])),
        models=ModelSettings(**dict(domain_payload["models"])),
        retrieval=RetrievalSettings(**dict(domain_payload["retrieval"])),
        query_understanding=QueryUnderstandingSettings(**dict(domain_payload["query_understanding"])),
        generation=GenerationSettings(**dict(domain_payload["generation"])),
        graph=GraphSettings(**dict(domain_payload["graph"])),
        observability=ObservabilitySettings(**dict(domain_payload["observability"])),
    )


def _load_storage_settings(source: EnvConfigSource) -> StorageSettings:
    index_cache_dir = source.get_str("INDEX_CACHE_DIR", "storage/indexes")
    artifact_manifest_path = source.get_str(
        "ARTIFACT_MANIFEST_PATH",
        os.path.join(index_cache_dir, "artifact_manifest.json"),
    )
    return StorageSettings(
        neo4j_uri=source.get_str("NEO4J_URI", "bolt://localhost:7687"),
        neo4j_user=source.get_str("NEO4J_USER", "neo4j"),
        neo4j_password=source.get_str("NEO4J_PASSWORD", "password"),
        neo4j_database=source.get_str("NEO4J_DATABASE", "neo4j"),
        milvus_host=source.get_str("MILVUS_HOST", "localhost"),
        milvus_port=source.get_int("MILVUS_PORT", 19530),
        milvus_collection_name=source.get_str("MILVUS_COLLECTION_NAME", "cooking_knowledge"),
        milvus_dimension=source.get_int("MILVUS_DIMENSION", 1024),
        enable_index_cache=source.get_bool("ENABLE_INDEX_CACHE", True),
        index_cache_dir=index_cache_dir,
        artifact_manifest_path=artifact_manifest_path,
    )


def _load_model_settings(source: EnvConfigSource) -> ModelSettings:
    api_key = (
        source.get_first("DASHSCOPE_API_KEY", "OPENAI_API_KEY", "MOONSHOT_API_KEY")
        or ""
    )
    return ModelSettings(
        api_key=api_key,
        llm_base_url=source.get_str(
            "LLM_BASE_URL",
            "https://dashscope.aliyuncs.com/compatible-mode/v1",
        ),
        embedding_base_url=source.get_str(
            "EMBEDDING_BASE_URL",
            "https://dashscope.aliyuncs.com/api/v1/services/embeddings/multimodal-embedding/multimodal-embedding",
        ),
        rerank_base_url=source.get_str(
            "RERANK_BASE_URL",
            "https://dashscope.aliyuncs.com/api/v1/services/rerank/text-rerank/text-rerank",
        ),
        embedding_model=source.get_str("EMBEDDING_MODEL", "qwen3-vl-embedding"),
        llm_model=source.get_str("LLM_MODEL", "qwen3.7-plus"),
        rerank_model=source.get_str("RERANK_MODEL", "qwen3-vl-rerank"),
        embedding_dimension=source.get_int("EMBEDDING_DIMENSION", 1024),
        embedding_batch_size=source.get_int("EMBEDDING_BATCH_SIZE", 10),
        enable_rerank=source.get_bool("ENABLE_RERANK", True),
        llm_timeout_seconds=source.get_int("LLM_TIMEOUT_SECONDS", 20),
        embedding_timeout_seconds=source.get_int("EMBEDDING_TIMEOUT_SECONDS", 60),
        rerank_timeout_seconds=source.get_int("RERANK_TIMEOUT_SECONDS", 20),
    )


def _load_retrieval_settings(source: EnvConfigSource) -> RetrievalSettings:
    return RetrievalSettings(
        top_k=source.get_int("TOP_K", 5),
        vector_search_ef=source.get_int("VECTOR_SEARCH_EF", 128),
        vector_search_max_k=source.get_int("VECTOR_SEARCH_MAX_K", 50),
        rrf_k=source.get_int("RRF_K", 60),
        hybrid_default_candidate_multiplier=source.get_int("HYBRID_DEFAULT_CANDIDATE_MULTIPLIER", 2),
        hybrid_default_candidate_min_candidates=source.get_int("HYBRID_DEFAULT_CANDIDATE_MIN_CANDIDATES", 10),
        hybrid_constraint_candidate_multiplier=source.get_int("HYBRID_CONSTRAINT_CANDIDATE_MULTIPLIER", 6),
        hybrid_constraint_candidate_min_candidates=source.get_int("HYBRID_CONSTRAINT_CANDIDATE_MIN_CANDIDATES", 30),
        router_combined_candidate_multiplier=source.get_int("ROUTER_COMBINED_CANDIDATE_MULTIPLIER", 6),
        router_combined_candidate_min_candidates=source.get_int("ROUTER_COMBINED_CANDIDATE_MIN_CANDIDATES", 30),
        router_graph_supplement_candidate_multiplier=source.get_int(
            "ROUTER_GRAPH_SUPPLEMENT_CANDIDATE_MULTIPLIER",
            2,
        ),
        router_graph_supplement_candidate_min_candidates=source.get_int(
            "ROUTER_GRAPH_SUPPLEMENT_CANDIDATE_MIN_CANDIDATES",
            10,
        ),
        retrieval_preserve_graph_evidence=source.get_bool("RETRIEVAL_PRESERVE_GRAPH_EVIDENCE", True),
        enable_parent_doc_retrieval=source.get_bool("ENABLE_PARENT_DOC_RETRIEVAL", True),
        parent_doc_top_n=source.get_int("PARENT_DOC_TOP_N", 3),
        parent_doc_max_chars=source.get_int("PARENT_DOC_MAX_CHARS", 4000),
    )


def _load_query_understanding_settings(source: EnvConfigSource) -> QueryUnderstandingSettings:
    return QueryUnderstandingSettings(
        query_plan_cache_size=source.get_int("QUERY_PLAN_CACHE_SIZE", 128),
        fast_rule_query_planning=source.get_bool("FAST_RULE_QUERY_PLANNING", True),
        query_planner_llm_temperature=source.get_float("QUERY_PLANNER_LLM_TEMPERATURE", 0.0),
        query_planner_llm_max_tokens=source.get_int("QUERY_PLANNER_LLM_MAX_TOKENS", 1200),
        query_plan_reasoning_complexity_threshold=source.get_float(
            "QUERY_PLAN_REASONING_COMPLEXITY_THRESHOLD",
            0.7,
        ),
        query_plan_reasoning_relationship_threshold=source.get_float(
            "QUERY_PLAN_REASONING_RELATIONSHIP_THRESHOLD",
            0.7,
        ),
        query_plan_relation_intensity_base=source.get_float("QUERY_PLAN_RELATION_INTENSITY_BASE", 0.45),
        query_plan_relation_intensity_step=source.get_float("QUERY_PLAN_RELATION_INTENSITY_STEP", 0.12),
        query_plan_complexity_base=source.get_float("QUERY_PLAN_COMPLEXITY_BASE", 0.55),
        query_plan_complexity_step=source.get_float("QUERY_PLAN_COMPLEXITY_STEP", 0.08),
        query_plan_source_entity_limit=source.get_int("QUERY_PLAN_SOURCE_ENTITY_LIMIT", 3),
        query_plan_entity_keyword_limit=source.get_int("QUERY_PLAN_ENTITY_KEYWORD_LIMIT", 4),
        query_plan_topic_keyword_limit=source.get_int("QUERY_PLAN_TOPIC_KEYWORD_LIMIT", 4),
        query_plan_target_entity_limit=source.get_int("QUERY_PLAN_TARGET_ENTITY_LIMIT", 2),
        query_plan_multi_hop_hint_entity_count=source.get_int("QUERY_PLAN_MULTI_HOP_HINT_ENTITY_COUNT", 2),
        query_plan_multi_hop_hint_relationship_threshold=source.get_float(
            "QUERY_PLAN_MULTI_HOP_HINT_RELATIONSHIP_THRESHOLD",
            0.55,
        ),
        query_plan_combined_strategy_relationship_threshold=source.get_float(
            "QUERY_PLAN_COMBINED_STRATEGY_RELATIONSHIP_THRESHOLD",
            0.4,
        ),
        query_plan_combined_strategy_complexity_threshold=source.get_float(
            "QUERY_PLAN_COMBINED_STRATEGY_COMPLEXITY_THRESHOLD",
            0.6,
        ),
        query_plan_source_entity_seed_relationship_threshold=source.get_float(
            "QUERY_PLAN_SOURCE_ENTITY_SEED_RELATIONSHIP_THRESHOLD",
            0.4,
        ),
        query_plan_source_entity_backfill_relationship_threshold=source.get_float(
            "QUERY_PLAN_SOURCE_ENTITY_BACKFILL_RELATIONSHIP_THRESHOLD",
            0.55,
        ),
        query_plan_rule_fallback_confidence=source.get_float(
            "QUERY_PLAN_RULE_FALLBACK_CONFIDENCE",
            0.45,
        ),
        query_semantic_relation_intensity_reference_ratio=source.get_float_alias(
            "QUERY_SEMANTIC_RELATION_INTENSITY_REFERENCE_RATIO",
            default=0.5,
        ),
        query_semantic_complexity_relation_hit_weight=source.get_float_alias(
            "QUERY_SEMANTIC_COMPLEXITY_RELATION_HIT_WEIGHT",
            default=0.14,
        ),
        query_semantic_complexity_constraint_hit_weight=source.get_float_alias(
            "QUERY_SEMANTIC_COMPLEXITY_CONSTRAINT_HIT_WEIGHT",
            default=0.10,
        ),
        query_semantic_complexity_structural_hit_weight=source.get_float_alias(
            "QUERY_SEMANTIC_COMPLEXITY_STRUCTURAL_HIT_WEIGHT",
            default=0.12,
        ),
        query_semantic_complexity_length_weight=source.get_float_alias(
            "QUERY_SEMANTIC_COMPLEXITY_LENGTH_WEIGHT",
            default=0.28,
        ),
        query_semantic_complexity_length_norm_chars=source.get_int_alias(
            "QUERY_SEMANTIC_COMPLEXITY_LENGTH_NORM_CHARS",
            default=140,
        ),
        query_semantic_reasoning_complexity_threshold=source.get_float_alias(
            "QUERY_SEMANTIC_REASONING_COMPLEXITY_THRESHOLD",
            "QUERY_PLAN_REASONING_COMPLEXITY_THRESHOLD",
            default=0.7,
        ),
        query_semantic_reasoning_relationship_threshold=source.get_float_alias(
            "QUERY_SEMANTIC_REASONING_RELATIONSHIP_THRESHOLD",
            default=0.4,
        ),
        query_semantic_high_relationship_routing_threshold=source.get_float_alias(
            "QUERY_SEMANTIC_HIGH_RELATIONSHIP_ROUTING_THRESHOLD",
            "QUERY_PLAN_REASONING_RELATIONSHIP_THRESHOLD",
            default=0.7,
        ),
        query_semantic_relation_hit_intensity_boost_base=source.get_float_alias(
            "QUERY_SEMANTIC_RELATION_HIT_INTENSITY_BOOST_BASE",
            "QUERY_PLAN_RELATION_INTENSITY_BASE",
            default=0.45,
        ),
        query_semantic_relation_hit_intensity_boost_step=source.get_float_alias(
            "QUERY_SEMANTIC_RELATION_HIT_INTENSITY_BOOST_STEP",
            "QUERY_PLAN_RELATION_INTENSITY_STEP",
            default=0.12,
        ),
        query_semantic_relation_hit_complexity_boost_base=source.get_float_alias(
            "QUERY_SEMANTIC_RELATION_HIT_COMPLEXITY_BOOST_BASE",
            "QUERY_PLAN_COMPLEXITY_BASE",
            default=0.55,
        ),
        query_semantic_relation_hit_complexity_boost_step=source.get_float_alias(
            "QUERY_SEMANTIC_RELATION_HIT_COMPLEXITY_BOOST_STEP",
            "QUERY_PLAN_COMPLEXITY_STEP",
            default=0.08,
        ),
        query_semantic_source_entity_limit=source.get_int_alias(
            "QUERY_SEMANTIC_SOURCE_ENTITY_LIMIT",
            "QUERY_PLAN_SOURCE_ENTITY_LIMIT",
            default=3,
        ),
        query_semantic_entity_keyword_limit=source.get_int_alias(
            "QUERY_SEMANTIC_ENTITY_KEYWORD_LIMIT",
            "QUERY_PLAN_ENTITY_KEYWORD_LIMIT",
            default=4,
        ),
        query_semantic_profile_entity_keyword_limit=source.get_int_alias(
            "QUERY_SEMANTIC_PROFILE_ENTITY_KEYWORD_LIMIT",
            default=6,
        ),
        query_semantic_topic_keyword_limit=source.get_int_alias(
            "QUERY_SEMANTIC_TOPIC_KEYWORD_LIMIT",
            "QUERY_PLAN_TOPIC_KEYWORD_LIMIT",
            default=4,
        ),
        query_semantic_profile_topic_keyword_start=source.get_int_alias(
            "QUERY_SEMANTIC_PROFILE_TOPIC_KEYWORD_START",
            default=4,
        ),
        query_semantic_profile_topic_keyword_limit=source.get_int_alias(
            "QUERY_SEMANTIC_PROFILE_TOPIC_KEYWORD_LIMIT",
            default=6,
        ),
        query_semantic_target_entity_limit=source.get_int_alias(
            "QUERY_SEMANTIC_TARGET_ENTITY_LIMIT",
            "QUERY_PLAN_TARGET_ENTITY_LIMIT",
            default=2,
        ),
        query_semantic_multi_hop_hint_entity_count=source.get_int_alias(
            "QUERY_SEMANTIC_MULTI_HOP_HINT_ENTITY_COUNT",
            "QUERY_PLAN_MULTI_HOP_HINT_ENTITY_COUNT",
            default=2,
        ),
        query_semantic_multi_hop_hint_relationship_threshold=source.get_float_alias(
            "QUERY_SEMANTIC_MULTI_HOP_HINT_RELATIONSHIP_THRESHOLD",
            "QUERY_PLAN_MULTI_HOP_HINT_RELATIONSHIP_THRESHOLD",
            default=0.55,
        ),
        query_semantic_combined_strategy_relationship_threshold=source.get_float_alias(
            "QUERY_SEMANTIC_COMBINED_STRATEGY_RELATIONSHIP_THRESHOLD",
            "QUERY_PLAN_COMBINED_STRATEGY_RELATIONSHIP_THRESHOLD",
            default=0.4,
        ),
        query_semantic_combined_strategy_complexity_threshold=source.get_float_alias(
            "QUERY_SEMANTIC_COMBINED_STRATEGY_COMPLEXITY_THRESHOLD",
            "QUERY_PLAN_COMBINED_STRATEGY_COMPLEXITY_THRESHOLD",
            default=0.6,
        ),
        query_semantic_source_entity_seed_relationship_threshold=source.get_float_alias(
            "QUERY_SEMANTIC_SOURCE_ENTITY_SEED_RELATIONSHIP_THRESHOLD",
            "QUERY_PLAN_SOURCE_ENTITY_SEED_RELATIONSHIP_THRESHOLD",
            default=0.4,
        ),
        query_semantic_source_entity_backfill_relationship_threshold=source.get_float_alias(
            "QUERY_SEMANTIC_SOURCE_ENTITY_BACKFILL_RELATIONSHIP_THRESHOLD",
            "QUERY_PLAN_SOURCE_ENTITY_BACKFILL_RELATIONSHIP_THRESHOLD",
            default=0.55,
        ),
        query_semantic_rule_fallback_confidence=source.get_float_alias(
            "QUERY_SEMANTIC_RULE_FALLBACK_CONFIDENCE",
            "QUERY_PLAN_RULE_FALLBACK_CONFIDENCE",
            default=0.45,
        ),
        query_semantic_entity_relation_max_depth=source.get_int_alias(
            "QUERY_SEMANTIC_ENTITY_RELATION_MAX_DEPTH",
            default=1,
        ),
        query_semantic_path_finding_max_depth=source.get_int_alias(
            "QUERY_SEMANTIC_PATH_FINDING_MAX_DEPTH",
            default=3,
        ),
        query_semantic_path_finding_high_intensity_max_depth=source.get_int_alias(
            "QUERY_SEMANTIC_PATH_FINDING_HIGH_INTENSITY_MAX_DEPTH",
            default=4,
        ),
        query_semantic_path_finding_high_intensity_threshold=source.get_float_alias(
            "QUERY_SEMANTIC_PATH_FINDING_HIGH_INTENSITY_THRESHOLD",
            default=0.6,
        ),
        query_semantic_subgraph_max_depth=source.get_int_alias(
            "QUERY_SEMANTIC_SUBGRAPH_MAX_DEPTH",
            default=2,
        ),
        query_semantic_subgraph_high_intensity_max_depth=source.get_int_alias(
            "QUERY_SEMANTIC_SUBGRAPH_HIGH_INTENSITY_MAX_DEPTH",
            default=3,
        ),
        query_semantic_subgraph_high_intensity_threshold=source.get_float_alias(
            "QUERY_SEMANTIC_SUBGRAPH_HIGH_INTENSITY_THRESHOLD",
            default=0.5,
        ),
        query_semantic_clustering_max_depth=source.get_int_alias(
            "QUERY_SEMANTIC_CLUSTERING_MAX_DEPTH",
            default=3,
        ),
        query_semantic_default_max_depth=source.get_int_alias(
            "QUERY_SEMANTIC_DEFAULT_MAX_DEPTH",
            default=2,
        ),
        query_semantic_default_high_intensity_max_depth=source.get_int_alias(
            "QUERY_SEMANTIC_DEFAULT_HIGH_INTENSITY_MAX_DEPTH",
            default=3,
        ),
        query_semantic_default_high_intensity_threshold=source.get_float_alias(
            "QUERY_SEMANTIC_DEFAULT_HIGH_INTENSITY_THRESHOLD",
            default=0.7,
        ),
        query_semantic_entity_relation_max_nodes=source.get_int_alias(
            "QUERY_SEMANTIC_ENTITY_RELATION_MAX_NODES",
            default=20,
        ),
        query_semantic_path_finding_max_nodes=source.get_int_alias(
            "QUERY_SEMANTIC_PATH_FINDING_MAX_NODES",
            default=40,
        ),
        query_semantic_subgraph_max_nodes=source.get_int_alias(
            "QUERY_SEMANTIC_SUBGRAPH_MAX_NODES",
            default=80,
        ),
        query_semantic_clustering_max_nodes=source.get_int_alias(
            "QUERY_SEMANTIC_CLUSTERING_MAX_NODES",
            default=60,
        ),
        query_semantic_default_max_nodes=source.get_int_alias(
            "QUERY_SEMANTIC_DEFAULT_MAX_NODES",
            default=50,
        ),
        query_semantic_graph_query_max_depth_cap=source.get_int_alias(
            "QUERY_SEMANTIC_GRAPH_QUERY_MAX_DEPTH_CAP",
            default=4,
        ),
        query_semantic_graph_query_fallback_name_chars=source.get_int_alias(
            "QUERY_SEMANTIC_GRAPH_QUERY_FALLBACK_NAME_CHARS",
            default=16,
        ),
        query_semantic_adaptive_multi_hop_subgraph_threshold=source.get_float_alias(
            "QUERY_SEMANTIC_ADAPTIVE_MULTI_HOP_SUBGRAPH_THRESHOLD",
            default=0.7,
        ),
        query_semantic_adaptive_subgraph_multi_hop_threshold=source.get_float_alias(
            "QUERY_SEMANTIC_ADAPTIVE_SUBGRAPH_MULTI_HOP_THRESHOLD",
            default=0.45,
        ),
        query_semantic_adaptive_entity_relation_multi_hop_threshold=source.get_float_alias(
            "QUERY_SEMANTIC_ADAPTIVE_ENTITY_RELATION_MULTI_HOP_THRESHOLD",
            default=0.5,
        ),
        query_semantic_adaptive_subgraph_max_depth=source.get_int_alias(
            "QUERY_SEMANTIC_ADAPTIVE_SUBGRAPH_MAX_DEPTH",
            default=3,
        ),
        query_semantic_adaptive_subgraph_max_nodes=source.get_int_alias(
            "QUERY_SEMANTIC_ADAPTIVE_SUBGRAPH_MAX_NODES",
            default=100,
        ),
        query_semantic_adaptive_multi_hop_max_depth=source.get_int_alias(
            "QUERY_SEMANTIC_ADAPTIVE_MULTI_HOP_MAX_DEPTH",
            default=3,
        ),
        query_semantic_adaptive_multi_hop_max_nodes=source.get_int_alias(
            "QUERY_SEMANTIC_ADAPTIVE_MULTI_HOP_MAX_NODES",
            default=50,
        ),
        query_semantic_adaptive_entity_relation_max_depth=source.get_int_alias(
            "QUERY_SEMANTIC_ADAPTIVE_ENTITY_RELATION_MAX_DEPTH",
            default=2,
        ),
        query_semantic_adaptive_entity_relation_max_nodes=source.get_int_alias(
            "QUERY_SEMANTIC_ADAPTIVE_ENTITY_RELATION_MAX_NODES",
            default=40,
        ),
    )


def _load_generation_settings(source: EnvConfigSource) -> GenerationSettings:
    return GenerationSettings(
        temperature=source.get_float("TEMPERATURE", 0.1),
        max_tokens=source.get_int("MAX_TOKENS", 2048),
        generation_timeout_seconds=source.get_int("GENERATION_TIMEOUT_SECONDS", 25),
        generation_stream_timeout_seconds=source.get_int("GENERATION_STREAM_TIMEOUT_SECONDS", 25),
        generation_plan_max_tokens=source.get_int("GENERATION_PLAN_MAX_TOKENS", 600),
        generation_compose_max_tokens=source.get_int("GENERATION_COMPOSE_MAX_TOKENS", 1100),
        generation_direct_max_tokens=source.get_int("GENERATION_DIRECT_MAX_TOKENS", 700),
        generation_plan_temperature=source.get_float("GENERATION_PLAN_TEMPERATURE", 0.0),
        generation_planner_mode=source.get_str("GENERATION_PLANNER_MODE", "rule"),
        generation_max_retries=source.get_int("GENERATION_MAX_RETRIES", 3),
        generation_request_retries=source.get_int("GENERATION_REQUEST_RETRIES", 1),
        generation_stream_retries=source.get_int("GENERATION_STREAM_RETRIES", 2),
        generation_evidence_max_chars=source.get_int("GENERATION_EVIDENCE_MAX_CHARS", 700),
        generation_enable_two_stage=source.get_bool("GENERATION_ENABLE_TWO_STAGE", True),
        generation_two_stage_complexity_threshold=source.get_float(
            "GENERATION_TWO_STAGE_COMPLEXITY_THRESHOLD",
            0.68,
        ),
        generation_two_stage_relationship_threshold=source.get_float(
            "GENERATION_TWO_STAGE_RELATIONSHIP_THRESHOLD",
            0.58,
        ),
        generation_direct_max_evidence_items=source.get_int("GENERATION_DIRECT_MAX_EVIDENCE_ITEMS", 2),
        generation_two_stage_max_evidence_items=source.get_int("GENERATION_TWO_STAGE_MAX_EVIDENCE_ITEMS", 3),
        generation_plan_max_evidence_items=source.get_int("GENERATION_PLAN_MAX_EVIDENCE_ITEMS", 2),
        generation_max_graph_paths_per_item=source.get_int("GENERATION_MAX_GRAPH_PATHS_PER_ITEM", 1),
        generation_max_evidence_units_per_item=source.get_int("GENERATION_MAX_EVIDENCE_UNITS_PER_ITEM", 4),
        generation_include_document_evidence=source.get_bool("GENERATION_INCLUDE_DOCUMENT_EVIDENCE", False),
        generation_compose_include_content=source.get_bool("GENERATION_COMPOSE_INCLUDE_CONTENT", False),
        generation_fallback_on_timeout=source.get_bool("GENERATION_FALLBACK_ON_TIMEOUT", False),
    )


def _load_graph_settings(source: EnvConfigSource) -> GraphSettings:
    return GraphSettings(
        enable_semantic_graph_schema=source.get_bool("ENABLE_SEMANTIC_GRAPH_SCHEMA", True),
        chunk_size=source.get_int("CHUNK_SIZE", 500),
        chunk_overlap=source.get_int("CHUNK_OVERLAP", 50),
        max_graph_depth=source.get_int("MAX_GRAPH_DEPTH", 2),
        graph_rank_base_weight=source.get_float("GRAPH_RANK_BASE_WEIGHT", 1.0),
        graph_rank_semantic_relation_weight=source.get_float("GRAPH_RANK_SEMANTIC_RELATION_WEIGHT", 0.08),
        graph_rank_evidence_unit_weight=source.get_float("GRAPH_RANK_EVIDENCE_UNIT_WEIGHT", 0.03),
        graph_rank_relationship_weight=source.get_float("GRAPH_RANK_RELATIONSHIP_WEIGHT", 0.01),
        graph_rank_recipe_presence_weight=source.get_float("GRAPH_RANK_RECIPE_PRESENCE_WEIGHT", 0.1),
        graph_rank_query_overlap_weight=source.get_float("GRAPH_RANK_QUERY_OVERLAP_WEIGHT", 0.02),
        entity_linker_limit_per_entity=source.get_int("ENTITY_LINKER_LIMIT_PER_ENTITY", 4),
        entity_linker_min_confidence=source.get_float("ENTITY_LINKER_MIN_CONFIDENCE", 0.45),
        entity_linker_max_same_name_candidates=source.get_int("ENTITY_LINKER_MAX_SAME_NAME_CANDIDATES", 2),
        entity_linker_query_type_label_priorities=source.get_json_dict(
            "ENTITY_LINKER_QUERY_TYPE_LABEL_PRIORITIES",
            default_entity_linker_query_type_priorities(),
        ),
        entity_linker_relation_label_priorities=source.get_json_dict(
            "ENTITY_LINKER_RELATION_LABEL_PRIORITIES",
            default_entity_linker_relation_priorities(),
        ),
    )


def _load_observability_settings(source: EnvConfigSource) -> ObservabilitySettings:
    return ObservabilitySettings(
        enable_query_tracing=source.get_bool("ENABLE_QUERY_TRACING", True),
        query_trace_path=source.get_str("QUERY_TRACE_PATH", "storage/traces/query_trace.jsonl"),
    )


def load_config(
    overrides: Mapping[str, Any] | None = None,
    *,
    source: EnvConfigSource | None = None,
) -> GraphRAGConfig:
    load_dotenv()
    env_source = source or default_env_source()
    config = GraphRAGConfig(
        storage=_load_storage_settings(env_source),
        models=_load_model_settings(env_source),
        retrieval=_load_retrieval_settings(env_source),
        query_understanding=_load_query_understanding_settings(env_source),
        generation=_load_generation_settings(env_source),
        graph=_load_graph_settings(env_source),
        observability=_load_observability_settings(env_source),
    )
    if overrides:
        return config.with_overrides(overrides)
    return config
