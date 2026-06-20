"""Dedicated loader for query-understanding configuration sections."""

from __future__ import annotations
from typing import Any, Mapping

from rag_modules.query_policy import get_query_policy

from .env import EnvConfigSource
from .models import (
    QueryPlannerSettings,
    QuerySemanticAdaptiveTraversalSettings,
    QuerySemanticExtractionSettings,
    QuerySemanticRoutingSettings,
    QuerySemanticScoringSettings,
    QuerySemanticSettings,
    QuerySemanticTraversalSettings,
    QueryUnderstandingSettings,
)

_QUERY_POLICY = get_query_policy()
_PLANNER_DEFAULTS = _QUERY_POLICY.runtime_section("planner")
_SEMANTIC_DEFAULTS = _QUERY_POLICY.runtime_section("semantics")


def _mapping_defaults(defaults: Mapping[str, Any] | None) -> dict[str, Any]:
    return dict(defaults or {})


def load_query_understanding_settings(
    source: EnvConfigSource,
    defaults: Mapping[str, Any] | None = None,
) -> QueryUnderstandingSettings:
    query_defaults = _mapping_defaults(defaults)
    return QueryUnderstandingSettings(
        planner=_load_query_planner_settings(source, query_defaults.get("planner")),
        semantics=_load_query_semantic_settings(source, query_defaults.get("semantics")),
    )


def _load_query_planner_settings(
    source: EnvConfigSource,
    defaults: Mapping[str, Any] | None = None,
) -> QueryPlannerSettings:
    planner_defaults = {**_PLANNER_DEFAULTS, **_mapping_defaults(defaults)}
    return QueryPlannerSettings(
        cache_size=source.get_int(
            "QUERY_PLAN_CACHE_SIZE",
            int(planner_defaults.get("cache_size", 128)),
        ),
        fast_rule_planning=source.get_bool(
            "FAST_RULE_QUERY_PLANNING",
            bool(planner_defaults.get("fast_rule_planning", True)),
        ),
        llm_temperature=source.get_float(
            "QUERY_PLANNER_LLM_TEMPERATURE",
            float(planner_defaults.get("llm_temperature", 0.0)),
        ),
        llm_max_tokens=source.get_int(
            "QUERY_PLANNER_LLM_MAX_TOKENS",
            int(planner_defaults.get("llm_max_tokens", 1200)),
        ),
    )


def _load_query_semantic_settings(
    source: EnvConfigSource,
    defaults: Mapping[str, Any] | None = None,
) -> QuerySemanticSettings:
    semantic_defaults = _mapping_defaults(defaults)
    return QuerySemanticSettings(
        scoring=_load_query_semantic_scoring_settings(source, semantic_defaults.get("scoring")),
        extraction=_load_query_semantic_extraction_settings(source, semantic_defaults.get("extraction")),
        routing=_load_query_semantic_routing_settings(source, semantic_defaults.get("routing")),
        traversal=_load_query_semantic_traversal_settings(source, semantic_defaults.get("traversal")),
        adaptive_traversal=_load_query_semantic_adaptive_traversal_settings(
            source,
            semantic_defaults.get("adaptive_traversal"),
        ),
    )


def _load_query_semantic_scoring_settings(
    source: EnvConfigSource,
    defaults: Mapping[str, Any] | None = None,
) -> QuerySemanticScoringSettings:
    semantic_defaults = {**_SEMANTIC_DEFAULTS, **_mapping_defaults(defaults)}
    return QuerySemanticScoringSettings(
        relation_intensity_reference_ratio=source.get_float_alias(
            "QUERY_SEMANTIC_RELATION_INTENSITY_REFERENCE_RATIO",
            default=float(semantic_defaults.get("relation_intensity_reference_ratio", 0.5)),
        ),
        complexity_relation_hit_weight=source.get_float_alias(
            "QUERY_SEMANTIC_COMPLEXITY_RELATION_HIT_WEIGHT",
            default=float(semantic_defaults.get("complexity_relation_hit_weight", 0.14)),
        ),
        complexity_constraint_hit_weight=source.get_float_alias(
            "QUERY_SEMANTIC_COMPLEXITY_CONSTRAINT_HIT_WEIGHT",
            default=float(semantic_defaults.get("complexity_constraint_hit_weight", 0.1)),
        ),
        complexity_structural_hit_weight=source.get_float_alias(
            "QUERY_SEMANTIC_COMPLEXITY_STRUCTURAL_HIT_WEIGHT",
            default=float(semantic_defaults.get("complexity_structural_hit_weight", 0.12)),
        ),
        complexity_length_weight=source.get_float_alias(
            "QUERY_SEMANTIC_COMPLEXITY_LENGTH_WEIGHT",
            default=float(semantic_defaults.get("complexity_length_weight", 0.28)),
        ),
        complexity_length_norm_chars=source.get_int_alias(
            "QUERY_SEMANTIC_COMPLEXITY_LENGTH_NORM_CHARS",
            default=int(semantic_defaults.get("complexity_length_norm_chars", 140)),
        ),
        reasoning_complexity_threshold=source.get_float_alias(
            "QUERY_SEMANTIC_REASONING_COMPLEXITY_THRESHOLD",
            default=float(semantic_defaults.get("reasoning_complexity_threshold", 0.7)),
        ),
        reasoning_relationship_threshold=source.get_float_alias(
            "QUERY_SEMANTIC_REASONING_RELATIONSHIP_THRESHOLD",
            default=float(semantic_defaults.get("reasoning_relationship_threshold", 0.4)),
        ),
        relation_hit_intensity_boost_base=source.get_float_alias(
            "QUERY_SEMANTIC_RELATION_HIT_INTENSITY_BOOST_BASE",
            default=float(semantic_defaults.get("relation_hit_intensity_boost_base", 0.45)),
        ),
        relation_hit_intensity_boost_step=source.get_float_alias(
            "QUERY_SEMANTIC_RELATION_HIT_INTENSITY_BOOST_STEP",
            default=float(semantic_defaults.get("relation_hit_intensity_boost_step", 0.12)),
        ),
        relation_hit_complexity_boost_base=source.get_float_alias(
            "QUERY_SEMANTIC_RELATION_HIT_COMPLEXITY_BOOST_BASE",
            default=float(semantic_defaults.get("relation_hit_complexity_boost_base", 0.55)),
        ),
        relation_hit_complexity_boost_step=source.get_float_alias(
            "QUERY_SEMANTIC_RELATION_HIT_COMPLEXITY_BOOST_STEP",
            default=float(semantic_defaults.get("relation_hit_complexity_boost_step", 0.08)),
        ),
    )


def _load_query_semantic_extraction_settings(
    source: EnvConfigSource,
    defaults: Mapping[str, Any] | None = None,
) -> QuerySemanticExtractionSettings:
    semantic_defaults = {**_SEMANTIC_DEFAULTS, **_mapping_defaults(defaults)}
    return QuerySemanticExtractionSettings(
        source_entity_limit=source.get_int_alias(
            "QUERY_SEMANTIC_SOURCE_ENTITY_LIMIT",
            default=int(semantic_defaults.get("source_entity_limit", 3)),
        ),
        entity_keyword_limit=source.get_int_alias(
            "QUERY_SEMANTIC_ENTITY_KEYWORD_LIMIT",
            default=int(semantic_defaults.get("entity_keyword_limit", 4)),
        ),
        semantic_profile_entity_keyword_limit=source.get_int_alias(
            "QUERY_SEMANTIC_PROFILE_ENTITY_KEYWORD_LIMIT",
            default=int(semantic_defaults.get("semantic_profile_entity_keyword_limit", 6)),
        ),
        topic_keyword_limit=source.get_int_alias(
            "QUERY_SEMANTIC_TOPIC_KEYWORD_LIMIT",
            default=int(semantic_defaults.get("topic_keyword_limit", 4)),
        ),
        semantic_profile_topic_keyword_start=source.get_int_alias(
            "QUERY_SEMANTIC_PROFILE_TOPIC_KEYWORD_START",
            default=int(semantic_defaults.get("semantic_profile_topic_keyword_start", 4)),
        ),
        semantic_profile_topic_keyword_limit=source.get_int_alias(
            "QUERY_SEMANTIC_PROFILE_TOPIC_KEYWORD_LIMIT",
            default=int(semantic_defaults.get("semantic_profile_topic_keyword_limit", 6)),
        ),
        target_entity_limit=source.get_int_alias(
            "QUERY_SEMANTIC_TARGET_ENTITY_LIMIT",
            default=int(semantic_defaults.get("target_entity_limit", 2)),
        ),
    )


def _load_query_semantic_routing_settings(
    source: EnvConfigSource,
    defaults: Mapping[str, Any] | None = None,
) -> QuerySemanticRoutingSettings:
    semantic_defaults = {**_SEMANTIC_DEFAULTS, **_mapping_defaults(defaults)}
    return QuerySemanticRoutingSettings(
        high_relationship_routing_threshold=source.get_float_alias(
            "QUERY_SEMANTIC_HIGH_RELATIONSHIP_ROUTING_THRESHOLD",
            default=float(semantic_defaults.get("high_relationship_routing_threshold", 0.7)),
        ),
        multi_hop_hint_entity_count=source.get_int_alias(
            "QUERY_SEMANTIC_MULTI_HOP_HINT_ENTITY_COUNT",
            default=int(semantic_defaults.get("multi_hop_hint_entity_count", 2)),
        ),
        multi_hop_hint_relationship_threshold=source.get_float_alias(
            "QUERY_SEMANTIC_MULTI_HOP_HINT_RELATIONSHIP_THRESHOLD",
            default=float(semantic_defaults.get("multi_hop_hint_relationship_threshold", 0.55)),
        ),
        combined_strategy_relationship_threshold=source.get_float_alias(
            "QUERY_SEMANTIC_COMBINED_STRATEGY_RELATIONSHIP_THRESHOLD",
            default=float(semantic_defaults.get("combined_strategy_relationship_threshold", 0.4)),
        ),
        combined_strategy_complexity_threshold=source.get_float_alias(
            "QUERY_SEMANTIC_COMBINED_STRATEGY_COMPLEXITY_THRESHOLD",
            default=float(semantic_defaults.get("combined_strategy_complexity_threshold", 0.6)),
        ),
        source_entity_seed_relationship_threshold=source.get_float_alias(
            "QUERY_SEMANTIC_SOURCE_ENTITY_SEED_RELATIONSHIP_THRESHOLD",
            default=float(semantic_defaults.get("source_entity_seed_relationship_threshold", 0.4)),
        ),
        source_entity_backfill_relationship_threshold=source.get_float_alias(
            "QUERY_SEMANTIC_SOURCE_ENTITY_BACKFILL_RELATIONSHIP_THRESHOLD",
            default=float(semantic_defaults.get("source_entity_backfill_relationship_threshold", 0.55)),
        ),
        rule_fallback_confidence=source.get_float_alias(
            "QUERY_SEMANTIC_RULE_FALLBACK_CONFIDENCE",
            default=float(semantic_defaults.get("rule_fallback_confidence", 0.45)),
        ),
    )


def _load_query_semantic_traversal_settings(
    source: EnvConfigSource,
    defaults: Mapping[str, Any] | None = None,
) -> QuerySemanticTraversalSettings:
    semantic_defaults = {**_SEMANTIC_DEFAULTS, **_mapping_defaults(defaults)}
    return QuerySemanticTraversalSettings(
        entity_relation_max_depth=source.get_int_alias(
            "QUERY_SEMANTIC_ENTITY_RELATION_MAX_DEPTH",
            default=int(semantic_defaults.get("entity_relation_max_depth", 1)),
        ),
        path_finding_max_depth=source.get_int_alias(
            "QUERY_SEMANTIC_PATH_FINDING_MAX_DEPTH",
            default=int(semantic_defaults.get("path_finding_max_depth", 3)),
        ),
        path_finding_high_intensity_max_depth=source.get_int_alias(
            "QUERY_SEMANTIC_PATH_FINDING_HIGH_INTENSITY_MAX_DEPTH",
            default=int(semantic_defaults.get("path_finding_high_intensity_max_depth", 4)),
        ),
        path_finding_high_intensity_threshold=source.get_float_alias(
            "QUERY_SEMANTIC_PATH_FINDING_HIGH_INTENSITY_THRESHOLD",
            default=float(semantic_defaults.get("path_finding_high_intensity_threshold", 0.6)),
        ),
        subgraph_max_depth=source.get_int_alias(
            "QUERY_SEMANTIC_SUBGRAPH_MAX_DEPTH",
            default=int(semantic_defaults.get("subgraph_max_depth", 2)),
        ),
        subgraph_high_intensity_max_depth=source.get_int_alias(
            "QUERY_SEMANTIC_SUBGRAPH_HIGH_INTENSITY_MAX_DEPTH",
            default=int(semantic_defaults.get("subgraph_high_intensity_max_depth", 3)),
        ),
        subgraph_high_intensity_threshold=source.get_float_alias(
            "QUERY_SEMANTIC_SUBGRAPH_HIGH_INTENSITY_THRESHOLD",
            default=float(semantic_defaults.get("subgraph_high_intensity_threshold", 0.5)),
        ),
        clustering_max_depth=source.get_int_alias(
            "QUERY_SEMANTIC_CLUSTERING_MAX_DEPTH",
            default=int(semantic_defaults.get("clustering_max_depth", 3)),
        ),
        default_max_depth=source.get_int_alias(
            "QUERY_SEMANTIC_DEFAULT_MAX_DEPTH",
            default=int(semantic_defaults.get("default_max_depth", 2)),
        ),
        default_high_intensity_max_depth=source.get_int_alias(
            "QUERY_SEMANTIC_DEFAULT_HIGH_INTENSITY_MAX_DEPTH",
            default=int(semantic_defaults.get("default_high_intensity_max_depth", 3)),
        ),
        default_high_intensity_threshold=source.get_float_alias(
            "QUERY_SEMANTIC_DEFAULT_HIGH_INTENSITY_THRESHOLD",
            default=float(semantic_defaults.get("default_high_intensity_threshold", 0.7)),
        ),
        entity_relation_max_nodes=source.get_int_alias(
            "QUERY_SEMANTIC_ENTITY_RELATION_MAX_NODES",
            default=int(semantic_defaults.get("entity_relation_max_nodes", 20)),
        ),
        path_finding_max_nodes=source.get_int_alias(
            "QUERY_SEMANTIC_PATH_FINDING_MAX_NODES",
            default=int(semantic_defaults.get("path_finding_max_nodes", 40)),
        ),
        subgraph_max_nodes=source.get_int_alias(
            "QUERY_SEMANTIC_SUBGRAPH_MAX_NODES",
            default=int(semantic_defaults.get("subgraph_max_nodes", 80)),
        ),
        clustering_max_nodes=source.get_int_alias(
            "QUERY_SEMANTIC_CLUSTERING_MAX_NODES",
            default=int(semantic_defaults.get("clustering_max_nodes", 60)),
        ),
        default_max_nodes=source.get_int_alias(
            "QUERY_SEMANTIC_DEFAULT_MAX_NODES",
            default=int(semantic_defaults.get("default_max_nodes", 50)),
        ),
        graph_query_max_depth_cap=source.get_int_alias(
            "QUERY_SEMANTIC_GRAPH_QUERY_MAX_DEPTH_CAP",
            default=int(semantic_defaults.get("graph_query_max_depth_cap", 4)),
        ),
        graph_query_fallback_name_chars=source.get_int_alias(
            "QUERY_SEMANTIC_GRAPH_QUERY_FALLBACK_NAME_CHARS",
            default=int(semantic_defaults.get("graph_query_fallback_name_chars", 16)),
        ),
    )


def _load_query_semantic_adaptive_traversal_settings(
    source: EnvConfigSource,
    defaults: Mapping[str, Any] | None = None,
) -> QuerySemanticAdaptiveTraversalSettings:
    semantic_defaults = {**_SEMANTIC_DEFAULTS, **_mapping_defaults(defaults)}
    return QuerySemanticAdaptiveTraversalSettings(
        multi_hop_subgraph_threshold=source.get_float_alias(
            "QUERY_SEMANTIC_ADAPTIVE_MULTI_HOP_SUBGRAPH_THRESHOLD",
            default=float(semantic_defaults.get("adaptive_multi_hop_subgraph_threshold", 0.7)),
        ),
        subgraph_multi_hop_threshold=source.get_float_alias(
            "QUERY_SEMANTIC_ADAPTIVE_SUBGRAPH_MULTI_HOP_THRESHOLD",
            default=float(semantic_defaults.get("adaptive_subgraph_multi_hop_threshold", 0.45)),
        ),
        entity_relation_multi_hop_threshold=source.get_float_alias(
            "QUERY_SEMANTIC_ADAPTIVE_ENTITY_RELATION_MULTI_HOP_THRESHOLD",
            default=float(semantic_defaults.get("adaptive_entity_relation_multi_hop_threshold", 0.5)),
        ),
        subgraph_max_depth=source.get_int_alias(
            "QUERY_SEMANTIC_ADAPTIVE_SUBGRAPH_MAX_DEPTH",
            default=int(semantic_defaults.get("adaptive_subgraph_max_depth", 3)),
        ),
        subgraph_max_nodes=source.get_int_alias(
            "QUERY_SEMANTIC_ADAPTIVE_SUBGRAPH_MAX_NODES",
            default=int(semantic_defaults.get("adaptive_subgraph_max_nodes", 100)),
        ),
        multi_hop_max_depth=source.get_int_alias(
            "QUERY_SEMANTIC_ADAPTIVE_MULTI_HOP_MAX_DEPTH",
            default=int(semantic_defaults.get("adaptive_multi_hop_max_depth", 3)),
        ),
        multi_hop_max_nodes=source.get_int_alias(
            "QUERY_SEMANTIC_ADAPTIVE_MULTI_HOP_MAX_NODES",
            default=int(semantic_defaults.get("adaptive_multi_hop_max_nodes", 50)),
        ),
        entity_relation_max_depth=source.get_int_alias(
            "QUERY_SEMANTIC_ADAPTIVE_ENTITY_RELATION_MAX_DEPTH",
            default=int(semantic_defaults.get("adaptive_entity_relation_max_depth", 2)),
        ),
        entity_relation_max_nodes=source.get_int_alias(
            "QUERY_SEMANTIC_ADAPTIVE_ENTITY_RELATION_MAX_NODES",
            default=int(semantic_defaults.get("adaptive_entity_relation_max_nodes", 40)),
        ),
    )


__all__ = ["load_query_understanding_settings"]
