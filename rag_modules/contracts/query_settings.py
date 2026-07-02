"""Query planner and semantic runtime settings shared across subsystems."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict

from ..query_policy import get_query_policy
from ._common import bounded_float, coerce_int

_POLICY_BUNDLE = get_query_policy()
_PLANNER_DEFAULTS = _POLICY_BUNDLE.runtime_defaults.planner
_SEMANTIC_DEFAULTS = _POLICY_BUNDLE.runtime_defaults.semantics


@dataclass
class QueryPlannerRuntimeSettings:
    model_name: str = str(_PLANNER_DEFAULTS.model_name)
    cache_size: int = int(_PLANNER_DEFAULTS.cache_size)
    timeout_seconds: int = int(_PLANNER_DEFAULTS.timeout_seconds)
    fast_rule_planning: bool = bool(_PLANNER_DEFAULTS.fast_rule_planning)
    llm_temperature: float = float(_PLANNER_DEFAULTS.llm_temperature)
    llm_max_tokens: int = int(_PLANNER_DEFAULTS.llm_max_tokens)

    def __post_init__(self) -> None:
        self.model_name = str(self.model_name or _PLANNER_DEFAULTS.model_name)
        self.cache_size = coerce_int(self.cache_size, int(_PLANNER_DEFAULTS.cache_size))
        self.timeout_seconds = coerce_int(
            self.timeout_seconds,
            int(_PLANNER_DEFAULTS.timeout_seconds),
            minimum=1,
        )
        self.fast_rule_planning = bool(self.fast_rule_planning)
        self.llm_temperature = bounded_float(
            self.llm_temperature,
            float(_PLANNER_DEFAULTS.llm_temperature),
            maximum=2.0,
        )
        self.llm_max_tokens = coerce_int(
            self.llm_max_tokens,
            int(_PLANNER_DEFAULTS.llm_max_tokens),
            minimum=128,
        )

    @classmethod
    def from_config(cls, config) -> "QueryPlannerRuntimeSettings":
        models = config.models
        planner = config.query_understanding.planner
        return cls(
            model_name=models.llm_model or _PLANNER_DEFAULTS.model_name,
            cache_size=planner.cache_size,
            timeout_seconds=models.llm_timeout_seconds,
            fast_rule_planning=planner.fast_rule_planning,
            llm_temperature=planner.llm_temperature,
            llm_max_tokens=planner.llm_max_tokens,
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "model_name": self.model_name,
            "cache_size": self.cache_size,
            "timeout_seconds": self.timeout_seconds,
            "fast_rule_planning": self.fast_rule_planning,
            "llm_temperature": self.llm_temperature,
            "llm_max_tokens": self.llm_max_tokens,
        }


@dataclass
class QuerySemanticRuntimeSettings:
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
    high_relationship_routing_threshold: float = float(
        _SEMANTIC_DEFAULTS.high_relationship_routing_threshold
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
    adaptive_multi_hop_subgraph_threshold: float = float(
        _SEMANTIC_DEFAULTS.adaptive_multi_hop_subgraph_threshold
    )
    adaptive_subgraph_multi_hop_threshold: float = float(
        _SEMANTIC_DEFAULTS.adaptive_subgraph_multi_hop_threshold
    )
    adaptive_entity_relation_multi_hop_threshold: float = float(
        _SEMANTIC_DEFAULTS.adaptive_entity_relation_multi_hop_threshold
    )
    adaptive_subgraph_max_depth: int = int(_SEMANTIC_DEFAULTS.adaptive_subgraph_max_depth)
    adaptive_subgraph_max_nodes: int = int(_SEMANTIC_DEFAULTS.adaptive_subgraph_max_nodes)
    adaptive_multi_hop_max_depth: int = int(_SEMANTIC_DEFAULTS.adaptive_multi_hop_max_depth)
    adaptive_multi_hop_max_nodes: int = int(_SEMANTIC_DEFAULTS.adaptive_multi_hop_max_nodes)
    adaptive_entity_relation_max_depth: int = int(
        _SEMANTIC_DEFAULTS.adaptive_entity_relation_max_depth
    )
    adaptive_entity_relation_max_nodes: int = int(
        _SEMANTIC_DEFAULTS.adaptive_entity_relation_max_nodes
    )

    def __post_init__(self) -> None:
        defaults = _SEMANTIC_DEFAULTS
        for field_name in (
            "relation_intensity_reference_ratio",
            "reasoning_complexity_threshold",
            "reasoning_relationship_threshold",
            "high_relationship_routing_threshold",
            "relation_hit_intensity_boost_base",
            "relation_hit_complexity_boost_base",
            "multi_hop_hint_relationship_threshold",
            "combined_strategy_relationship_threshold",
            "combined_strategy_complexity_threshold",
            "source_entity_seed_relationship_threshold",
            "source_entity_backfill_relationship_threshold",
            "rule_fallback_confidence",
            "path_finding_high_intensity_threshold",
            "subgraph_high_intensity_threshold",
            "default_high_intensity_threshold",
            "adaptive_multi_hop_subgraph_threshold",
            "adaptive_subgraph_multi_hop_threshold",
            "adaptive_entity_relation_multi_hop_threshold",
        ):
            setattr(
                self,
                field_name,
                bounded_float(
                    getattr(self, field_name),
                    float(getattr(defaults, field_name)),
                ),
            )
        for field_name in (
            "complexity_relation_hit_weight",
            "complexity_constraint_hit_weight",
            "complexity_structural_hit_weight",
            "complexity_length_weight",
            "relation_hit_intensity_boost_step",
            "relation_hit_complexity_boost_step",
        ):
            setattr(
                self,
                field_name,
                bounded_float(
                    getattr(self, field_name),
                    float(getattr(defaults, field_name)),
                    maximum=5.0,
                ),
            )
        for field_name, minimum in (
            ("complexity_length_norm_chars", 1),
            ("source_entity_limit", 1),
            ("entity_keyword_limit", 1),
            ("semantic_profile_entity_keyword_limit", 1),
            ("topic_keyword_limit", 1),
            ("semantic_profile_topic_keyword_start", 0),
            ("semantic_profile_topic_keyword_limit", 1),
            ("target_entity_limit", 1),
            ("multi_hop_hint_entity_count", 1),
            ("entity_relation_max_depth", 1),
            ("path_finding_max_depth", 1),
            ("path_finding_high_intensity_max_depth", 1),
            ("subgraph_max_depth", 1),
            ("subgraph_high_intensity_max_depth", 1),
            ("clustering_max_depth", 1),
            ("default_max_depth", 1),
            ("default_high_intensity_max_depth", 1),
            ("entity_relation_max_nodes", 1),
            ("path_finding_max_nodes", 1),
            ("subgraph_max_nodes", 1),
            ("clustering_max_nodes", 1),
            ("default_max_nodes", 1),
            ("graph_query_max_depth_cap", 1),
            ("graph_query_fallback_name_chars", 1),
            ("adaptive_subgraph_max_depth", 1),
            ("adaptive_subgraph_max_nodes", 1),
            ("adaptive_multi_hop_max_depth", 1),
            ("adaptive_multi_hop_max_nodes", 1),
            ("adaptive_entity_relation_max_depth", 1),
            ("adaptive_entity_relation_max_nodes", 1),
        ):
            setattr(
                self,
                field_name,
                coerce_int(
                    getattr(self, field_name),
                    int(getattr(defaults, field_name)),
                    minimum=minimum,
                ),
            )

    @classmethod
    def from_config(cls, config) -> "QuerySemanticRuntimeSettings":
        semantics = config.query_understanding.semantics
        scoring = semantics.scoring
        extraction = semantics.extraction
        routing = semantics.routing
        traversal = semantics.traversal
        adaptive = semantics.adaptive_traversal
        return cls(
            relation_intensity_reference_ratio=scoring.relation_intensity_reference_ratio,
            complexity_relation_hit_weight=scoring.complexity_relation_hit_weight,
            complexity_constraint_hit_weight=scoring.complexity_constraint_hit_weight,
            complexity_structural_hit_weight=scoring.complexity_structural_hit_weight,
            complexity_length_weight=scoring.complexity_length_weight,
            complexity_length_norm_chars=scoring.complexity_length_norm_chars,
            reasoning_complexity_threshold=scoring.reasoning_complexity_threshold,
            reasoning_relationship_threshold=scoring.reasoning_relationship_threshold,
            high_relationship_routing_threshold=routing.high_relationship_routing_threshold,
            relation_hit_intensity_boost_base=scoring.relation_hit_intensity_boost_base,
            relation_hit_intensity_boost_step=scoring.relation_hit_intensity_boost_step,
            relation_hit_complexity_boost_base=scoring.relation_hit_complexity_boost_base,
            relation_hit_complexity_boost_step=scoring.relation_hit_complexity_boost_step,
            source_entity_limit=extraction.source_entity_limit,
            entity_keyword_limit=extraction.entity_keyword_limit,
            semantic_profile_entity_keyword_limit=extraction.semantic_profile_entity_keyword_limit,
            topic_keyword_limit=extraction.topic_keyword_limit,
            semantic_profile_topic_keyword_start=extraction.semantic_profile_topic_keyword_start,
            semantic_profile_topic_keyword_limit=extraction.semantic_profile_topic_keyword_limit,
            target_entity_limit=extraction.target_entity_limit,
            multi_hop_hint_entity_count=routing.multi_hop_hint_entity_count,
            multi_hop_hint_relationship_threshold=routing.multi_hop_hint_relationship_threshold,
            combined_strategy_relationship_threshold=routing.combined_strategy_relationship_threshold,
            combined_strategy_complexity_threshold=routing.combined_strategy_complexity_threshold,
            source_entity_seed_relationship_threshold=routing.source_entity_seed_relationship_threshold,
            source_entity_backfill_relationship_threshold=routing.source_entity_backfill_relationship_threshold,
            rule_fallback_confidence=routing.rule_fallback_confidence,
            entity_relation_max_depth=traversal.entity_relation_max_depth,
            path_finding_max_depth=traversal.path_finding_max_depth,
            path_finding_high_intensity_max_depth=traversal.path_finding_high_intensity_max_depth,
            path_finding_high_intensity_threshold=traversal.path_finding_high_intensity_threshold,
            subgraph_max_depth=traversal.subgraph_max_depth,
            subgraph_high_intensity_max_depth=traversal.subgraph_high_intensity_max_depth,
            subgraph_high_intensity_threshold=traversal.subgraph_high_intensity_threshold,
            clustering_max_depth=traversal.clustering_max_depth,
            default_max_depth=traversal.default_max_depth,
            default_high_intensity_max_depth=traversal.default_high_intensity_max_depth,
            default_high_intensity_threshold=traversal.default_high_intensity_threshold,
            entity_relation_max_nodes=traversal.entity_relation_max_nodes,
            path_finding_max_nodes=traversal.path_finding_max_nodes,
            subgraph_max_nodes=traversal.subgraph_max_nodes,
            clustering_max_nodes=traversal.clustering_max_nodes,
            default_max_nodes=traversal.default_max_nodes,
            graph_query_max_depth_cap=traversal.graph_query_max_depth_cap,
            graph_query_fallback_name_chars=traversal.graph_query_fallback_name_chars,
            adaptive_multi_hop_subgraph_threshold=adaptive.multi_hop_subgraph_threshold,
            adaptive_subgraph_multi_hop_threshold=adaptive.subgraph_multi_hop_threshold,
            adaptive_entity_relation_multi_hop_threshold=adaptive.entity_relation_multi_hop_threshold,
            adaptive_subgraph_max_depth=adaptive.subgraph_max_depth,
            adaptive_subgraph_max_nodes=adaptive.subgraph_max_nodes,
            adaptive_multi_hop_max_depth=adaptive.multi_hop_max_depth,
            adaptive_multi_hop_max_nodes=adaptive.multi_hop_max_nodes,
            adaptive_entity_relation_max_depth=adaptive.entity_relation_max_depth,
            adaptive_entity_relation_max_nodes=adaptive.entity_relation_max_nodes,
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            field.name: getattr(self, field.name) for field in self.__dataclass_fields__.values()
        }


__all__ = ["QueryPlannerRuntimeSettings", "QuerySemanticRuntimeSettings"]
