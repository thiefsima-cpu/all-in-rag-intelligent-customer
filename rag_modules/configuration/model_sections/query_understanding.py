"""Query understanding configuration section models."""

from __future__ import annotations

from typing import Any, Mapping, Self

from pydantic import Field

from rag_modules.query_policy import get_query_policy

from .base import ConfigSection

_QUERY_POLICY = get_query_policy()
_PLANNER_DEFAULTS = _QUERY_POLICY.runtime_section("planner")
_SEMANTIC_DEFAULTS = _QUERY_POLICY.runtime_section("semantics")


class QueryPolicySelectorSettings(ConfigSection):
    bundle: str = "c9-default-v1"
    bundle_path: str = ""


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
    multi_hop_hint_entity_count: int = int(_SEMANTIC_DEFAULTS.get("multi_hop_hint_entity_count", 2))
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
    entity_relation_max_depth: int = int(_SEMANTIC_DEFAULTS.get("entity_relation_max_depth", 1))
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
    graph_query_max_depth_cap: int = int(_SEMANTIC_DEFAULTS.get("graph_query_max_depth_cap", 4))
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
