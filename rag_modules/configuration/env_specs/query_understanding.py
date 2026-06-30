"""Query Understanding environment override specs."""

from __future__ import annotations

from .base import EnvFieldSpec
from .base import spec as _spec

QUERY_UNDERSTANDING_ENV_FIELD_SPECS: tuple[EnvFieldSpec, ...] = (
    _spec(
        "QUERY_POLICY_BUNDLE",
        ("query_understanding", "policy", "bundle"),
        "str",
    ),
    _spec(
        "QUERY_POLICY_BUNDLE_PATH",
        ("query_understanding", "policy", "bundle_path"),
        "str",
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


__all__ = ["QUERY_UNDERSTANDING_ENV_FIELD_SPECS"]
