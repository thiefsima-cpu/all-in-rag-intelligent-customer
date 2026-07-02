"""Query understanding configuration section models."""

from __future__ import annotations

from typing import Any, Mapping, Self

from pydantic import Field

from rag_modules.query_policy import get_query_policy

from .base import ConfigSection

_QUERY_POLICY = get_query_policy()
_PLANNER_DEFAULTS = _QUERY_POLICY.runtime_defaults.planner
_SEMANTIC_DEFAULTS = _QUERY_POLICY.runtime_defaults.semantics


class QueryPolicySelectorSettings(ConfigSection):
    bundle: str = "c9-default-v1"
    bundle_path: str = ""


class QueryPlannerSettings(ConfigSection):
    cache_size: int = int(_PLANNER_DEFAULTS.cache_size)
    fast_rule_planning: bool = bool(_PLANNER_DEFAULTS.fast_rule_planning)
    llm_temperature: float = float(_PLANNER_DEFAULTS.llm_temperature)
    llm_max_tokens: int = int(_PLANNER_DEFAULTS.llm_max_tokens)


class QuerySemanticScoringSettings(ConfigSection):
    relation_intensity_reference_ratio: float = float(
        _SEMANTIC_DEFAULTS.relation_intensity_reference_ratio
    )
    complexity_relation_hit_weight: float = float(_SEMANTIC_DEFAULTS.complexity_relation_hit_weight)
    complexity_constraint_hit_weight: float = float(
        _SEMANTIC_DEFAULTS.complexity_constraint_hit_weight
    )
    complexity_structural_hit_weight: float = float(
        _SEMANTIC_DEFAULTS.complexity_structural_hit_weight
    )
    complexity_length_weight: float = float(_SEMANTIC_DEFAULTS.complexity_length_weight)
    complexity_length_norm_chars: int = int(_SEMANTIC_DEFAULTS.complexity_length_norm_chars)
    reasoning_complexity_threshold: float = float(_SEMANTIC_DEFAULTS.reasoning_complexity_threshold)
    reasoning_relationship_threshold: float = float(
        _SEMANTIC_DEFAULTS.reasoning_relationship_threshold
    )
    relation_hit_intensity_boost_base: float = float(
        _SEMANTIC_DEFAULTS.relation_hit_intensity_boost_base
    )
    relation_hit_intensity_boost_step: float = float(
        _SEMANTIC_DEFAULTS.relation_hit_intensity_boost_step
    )
    relation_hit_complexity_boost_base: float = float(
        _SEMANTIC_DEFAULTS.relation_hit_complexity_boost_base
    )
    relation_hit_complexity_boost_step: float = float(
        _SEMANTIC_DEFAULTS.relation_hit_complexity_boost_step
    )


class QuerySemanticExtractionSettings(ConfigSection):
    source_entity_limit: int = int(_SEMANTIC_DEFAULTS.source_entity_limit)
    entity_keyword_limit: int = int(_SEMANTIC_DEFAULTS.entity_keyword_limit)
    semantic_profile_entity_keyword_limit: int = int(
        _SEMANTIC_DEFAULTS.semantic_profile_entity_keyword_limit
    )
    topic_keyword_limit: int = int(_SEMANTIC_DEFAULTS.topic_keyword_limit)
    semantic_profile_topic_keyword_start: int = int(
        _SEMANTIC_DEFAULTS.semantic_profile_topic_keyword_start
    )
    semantic_profile_topic_keyword_limit: int = int(
        _SEMANTIC_DEFAULTS.semantic_profile_topic_keyword_limit
    )
    target_entity_limit: int = int(_SEMANTIC_DEFAULTS.target_entity_limit)


class QuerySemanticRoutingSettings(ConfigSection):
    high_relationship_routing_threshold: float = float(
        _SEMANTIC_DEFAULTS.high_relationship_routing_threshold
    )
    multi_hop_hint_entity_count: int = int(_SEMANTIC_DEFAULTS.multi_hop_hint_entity_count)
    multi_hop_hint_relationship_threshold: float = float(
        _SEMANTIC_DEFAULTS.multi_hop_hint_relationship_threshold
    )
    combined_strategy_relationship_threshold: float = float(
        _SEMANTIC_DEFAULTS.combined_strategy_relationship_threshold
    )
    combined_strategy_complexity_threshold: float = float(
        _SEMANTIC_DEFAULTS.combined_strategy_complexity_threshold
    )
    source_entity_seed_relationship_threshold: float = float(
        _SEMANTIC_DEFAULTS.source_entity_seed_relationship_threshold
    )
    source_entity_backfill_relationship_threshold: float = float(
        _SEMANTIC_DEFAULTS.source_entity_backfill_relationship_threshold
    )
    rule_fallback_confidence: float = float(_SEMANTIC_DEFAULTS.rule_fallback_confidence)


class QuerySemanticTraversalSettings(ConfigSection):
    entity_relation_max_depth: int = int(_SEMANTIC_DEFAULTS.entity_relation_max_depth)
    path_finding_max_depth: int = int(_SEMANTIC_DEFAULTS.path_finding_max_depth)
    path_finding_high_intensity_max_depth: int = int(
        _SEMANTIC_DEFAULTS.path_finding_high_intensity_max_depth
    )
    path_finding_high_intensity_threshold: float = float(
        _SEMANTIC_DEFAULTS.path_finding_high_intensity_threshold
    )
    subgraph_max_depth: int = int(_SEMANTIC_DEFAULTS.subgraph_max_depth)
    subgraph_high_intensity_max_depth: int = int(
        _SEMANTIC_DEFAULTS.subgraph_high_intensity_max_depth
    )
    subgraph_high_intensity_threshold: float = float(
        _SEMANTIC_DEFAULTS.subgraph_high_intensity_threshold
    )
    clustering_max_depth: int = int(_SEMANTIC_DEFAULTS.clustering_max_depth)
    default_max_depth: int = int(_SEMANTIC_DEFAULTS.default_max_depth)
    default_high_intensity_max_depth: int = int(_SEMANTIC_DEFAULTS.default_high_intensity_max_depth)
    default_high_intensity_threshold: float = float(
        _SEMANTIC_DEFAULTS.default_high_intensity_threshold
    )
    entity_relation_max_nodes: int = int(_SEMANTIC_DEFAULTS.entity_relation_max_nodes)
    path_finding_max_nodes: int = int(_SEMANTIC_DEFAULTS.path_finding_max_nodes)
    subgraph_max_nodes: int = int(_SEMANTIC_DEFAULTS.subgraph_max_nodes)
    clustering_max_nodes: int = int(_SEMANTIC_DEFAULTS.clustering_max_nodes)
    default_max_nodes: int = int(_SEMANTIC_DEFAULTS.default_max_nodes)
    graph_query_max_depth_cap: int = int(_SEMANTIC_DEFAULTS.graph_query_max_depth_cap)
    graph_query_fallback_name_chars: int = int(_SEMANTIC_DEFAULTS.graph_query_fallback_name_chars)


class QuerySemanticAdaptiveTraversalSettings(ConfigSection):
    multi_hop_subgraph_threshold: float = float(
        _SEMANTIC_DEFAULTS.adaptive_multi_hop_subgraph_threshold
    )
    subgraph_multi_hop_threshold: float = float(
        _SEMANTIC_DEFAULTS.adaptive_subgraph_multi_hop_threshold
    )
    entity_relation_multi_hop_threshold: float = float(
        _SEMANTIC_DEFAULTS.adaptive_entity_relation_multi_hop_threshold
    )
    subgraph_max_depth: int = int(_SEMANTIC_DEFAULTS.adaptive_subgraph_max_depth)
    subgraph_max_nodes: int = int(_SEMANTIC_DEFAULTS.adaptive_subgraph_max_nodes)
    multi_hop_max_depth: int = int(_SEMANTIC_DEFAULTS.adaptive_multi_hop_max_depth)
    multi_hop_max_nodes: int = int(_SEMANTIC_DEFAULTS.adaptive_multi_hop_max_nodes)
    entity_relation_max_depth: int = int(_SEMANTIC_DEFAULTS.adaptive_entity_relation_max_depth)
    entity_relation_max_nodes: int = int(_SEMANTIC_DEFAULTS.adaptive_entity_relation_max_nodes)


class QuerySemanticSettings(ConfigSection):
    scoring: QuerySemanticScoringSettings = Field(default_factory=QuerySemanticScoringSettings)
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
    policy: QueryPolicySelectorSettings = Field(default_factory=QueryPolicySelectorSettings)
    planner: QueryPlannerSettings = Field(default_factory=QueryPlannerSettings)
    semantics: QuerySemanticSettings = Field(default_factory=QuerySemanticSettings)

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
