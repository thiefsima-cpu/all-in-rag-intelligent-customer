"""Query understanding configuration section models."""

from __future__ import annotations

from typing import Any, Mapping, Self

from pydantic import Field

from .base import ConfigSection


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
    def from_dict(cls, data: Mapping[str, Any]) -> Self:
        return cls.model_validate(dict(data or {}))


class QueryUnderstandingSettings(ConfigSection):
    policy: QueryPolicySelectorSettings = Field(default_factory=QueryPolicySelectorSettings)
    planner: QueryPlannerSettings
    semantics: QuerySemanticSettings

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Self:
        return cls.model_validate(dict(data or {}))


__all__ = [
    "QueryPolicySelectorSettings",
    "QueryPlannerSettings",
    "QuerySemanticAdaptiveTraversalSettings",
    "QuerySemanticExtractionSettings",
    "QuerySemanticRoutingSettings",
    "QuerySemanticScoringSettings",
    "QuerySemanticSettings",
    "QuerySemanticTraversalSettings",
    "QueryUnderstandingSettings",
]
