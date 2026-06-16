"""Semantic runtime profile settings."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict

from .shared import _SEMANTIC_DEFAULTS, _as_float, _as_int


@dataclass
class QuerySemanticRuntimeSettings:
    relation_intensity_reference_ratio: float = float(_SEMANTIC_DEFAULTS.get("relation_intensity_reference_ratio", 0.5))
    complexity_relation_hit_weight: float = float(_SEMANTIC_DEFAULTS.get("complexity_relation_hit_weight", 0.14))
    complexity_constraint_hit_weight: float = float(_SEMANTIC_DEFAULTS.get("complexity_constraint_hit_weight", 0.1))
    complexity_structural_hit_weight: float = float(_SEMANTIC_DEFAULTS.get("complexity_structural_hit_weight", 0.12))
    complexity_length_weight: float = float(_SEMANTIC_DEFAULTS.get("complexity_length_weight", 0.28))
    complexity_length_norm_chars: int = int(_SEMANTIC_DEFAULTS.get("complexity_length_norm_chars", 140))
    reasoning_complexity_threshold: float = float(_SEMANTIC_DEFAULTS.get("reasoning_complexity_threshold", 0.7))
    reasoning_relationship_threshold: float = float(_SEMANTIC_DEFAULTS.get("reasoning_relationship_threshold", 0.4))
    high_relationship_routing_threshold: float = float(_SEMANTIC_DEFAULTS.get("high_relationship_routing_threshold", 0.7))
    relation_hit_intensity_boost_base: float = float(_SEMANTIC_DEFAULTS.get("relation_hit_intensity_boost_base", 0.45))
    relation_hit_intensity_boost_step: float = float(_SEMANTIC_DEFAULTS.get("relation_hit_intensity_boost_step", 0.12))
    relation_hit_complexity_boost_base: float = float(_SEMANTIC_DEFAULTS.get("relation_hit_complexity_boost_base", 0.55))
    relation_hit_complexity_boost_step: float = float(_SEMANTIC_DEFAULTS.get("relation_hit_complexity_boost_step", 0.08))
    source_entity_limit: int = int(_SEMANTIC_DEFAULTS.get("source_entity_limit", 3))
    entity_keyword_limit: int = int(_SEMANTIC_DEFAULTS.get("entity_keyword_limit", 4))
    semantic_profile_entity_keyword_limit: int = int(_SEMANTIC_DEFAULTS.get("semantic_profile_entity_keyword_limit", 6))
    topic_keyword_limit: int = int(_SEMANTIC_DEFAULTS.get("topic_keyword_limit", 4))
    semantic_profile_topic_keyword_start: int = int(_SEMANTIC_DEFAULTS.get("semantic_profile_topic_keyword_start", 4))
    semantic_profile_topic_keyword_limit: int = int(_SEMANTIC_DEFAULTS.get("semantic_profile_topic_keyword_limit", 6))
    target_entity_limit: int = int(_SEMANTIC_DEFAULTS.get("target_entity_limit", 2))
    multi_hop_hint_entity_count: int = int(_SEMANTIC_DEFAULTS.get("multi_hop_hint_entity_count", 2))
    multi_hop_hint_relationship_threshold: float = float(_SEMANTIC_DEFAULTS.get("multi_hop_hint_relationship_threshold", 0.55))
    combined_strategy_relationship_threshold: float = float(_SEMANTIC_DEFAULTS.get("combined_strategy_relationship_threshold", 0.4))
    combined_strategy_complexity_threshold: float = float(_SEMANTIC_DEFAULTS.get("combined_strategy_complexity_threshold", 0.6))
    source_entity_seed_relationship_threshold: float = float(_SEMANTIC_DEFAULTS.get("source_entity_seed_relationship_threshold", 0.4))
    source_entity_backfill_relationship_threshold: float = float(_SEMANTIC_DEFAULTS.get("source_entity_backfill_relationship_threshold", 0.55))
    rule_fallback_confidence: float = float(_SEMANTIC_DEFAULTS.get("rule_fallback_confidence", 0.45))
    entity_relation_max_depth: int = int(_SEMANTIC_DEFAULTS.get("entity_relation_max_depth", 1))
    path_finding_max_depth: int = int(_SEMANTIC_DEFAULTS.get("path_finding_max_depth", 3))
    path_finding_high_intensity_max_depth: int = int(_SEMANTIC_DEFAULTS.get("path_finding_high_intensity_max_depth", 4))
    path_finding_high_intensity_threshold: float = float(_SEMANTIC_DEFAULTS.get("path_finding_high_intensity_threshold", 0.6))
    subgraph_max_depth: int = int(_SEMANTIC_DEFAULTS.get("subgraph_max_depth", 2))
    subgraph_high_intensity_max_depth: int = int(_SEMANTIC_DEFAULTS.get("subgraph_high_intensity_max_depth", 3))
    subgraph_high_intensity_threshold: float = float(_SEMANTIC_DEFAULTS.get("subgraph_high_intensity_threshold", 0.5))
    clustering_max_depth: int = int(_SEMANTIC_DEFAULTS.get("clustering_max_depth", 3))
    default_max_depth: int = int(_SEMANTIC_DEFAULTS.get("default_max_depth", 2))
    default_high_intensity_max_depth: int = int(_SEMANTIC_DEFAULTS.get("default_high_intensity_max_depth", 3))
    default_high_intensity_threshold: float = float(_SEMANTIC_DEFAULTS.get("default_high_intensity_threshold", 0.7))
    entity_relation_max_nodes: int = int(_SEMANTIC_DEFAULTS.get("entity_relation_max_nodes", 20))
    path_finding_max_nodes: int = int(_SEMANTIC_DEFAULTS.get("path_finding_max_nodes", 40))
    subgraph_max_nodes: int = int(_SEMANTIC_DEFAULTS.get("subgraph_max_nodes", 80))
    clustering_max_nodes: int = int(_SEMANTIC_DEFAULTS.get("clustering_max_nodes", 60))
    default_max_nodes: int = int(_SEMANTIC_DEFAULTS.get("default_max_nodes", 50))
    graph_query_max_depth_cap: int = int(_SEMANTIC_DEFAULTS.get("graph_query_max_depth_cap", 4))
    graph_query_fallback_name_chars: int = int(_SEMANTIC_DEFAULTS.get("graph_query_fallback_name_chars", 16))
    adaptive_multi_hop_subgraph_threshold: float = float(_SEMANTIC_DEFAULTS.get("adaptive_multi_hop_subgraph_threshold", 0.7))
    adaptive_subgraph_multi_hop_threshold: float = float(_SEMANTIC_DEFAULTS.get("adaptive_subgraph_multi_hop_threshold", 0.45))
    adaptive_entity_relation_multi_hop_threshold: float = float(_SEMANTIC_DEFAULTS.get("adaptive_entity_relation_multi_hop_threshold", 0.5))
    adaptive_subgraph_max_depth: int = int(_SEMANTIC_DEFAULTS.get("adaptive_subgraph_max_depth", 3))
    adaptive_subgraph_max_nodes: int = int(_SEMANTIC_DEFAULTS.get("adaptive_subgraph_max_nodes", 100))
    adaptive_multi_hop_max_depth: int = int(_SEMANTIC_DEFAULTS.get("adaptive_multi_hop_max_depth", 3))
    adaptive_multi_hop_max_nodes: int = int(_SEMANTIC_DEFAULTS.get("adaptive_multi_hop_max_nodes", 50))
    adaptive_entity_relation_max_depth: int = int(_SEMANTIC_DEFAULTS.get("adaptive_entity_relation_max_depth", 2))
    adaptive_entity_relation_max_nodes: int = int(_SEMANTIC_DEFAULTS.get("adaptive_entity_relation_max_nodes", 40))

    def __post_init__(self) -> None:
        defaults = _SEMANTIC_DEFAULTS
        self.relation_intensity_reference_ratio = _as_float(
            self.relation_intensity_reference_ratio,
            float(defaults.get("relation_intensity_reference_ratio", 0.5)),
        )
        self.complexity_relation_hit_weight = _as_float(
            self.complexity_relation_hit_weight,
            float(defaults.get("complexity_relation_hit_weight", 0.14)),
            maximum=5.0,
        )
        self.complexity_constraint_hit_weight = _as_float(
            self.complexity_constraint_hit_weight,
            float(defaults.get("complexity_constraint_hit_weight", 0.1)),
            maximum=5.0,
        )
        self.complexity_structural_hit_weight = _as_float(
            self.complexity_structural_hit_weight,
            float(defaults.get("complexity_structural_hit_weight", 0.12)),
            maximum=5.0,
        )
        self.complexity_length_weight = _as_float(
            self.complexity_length_weight,
            float(defaults.get("complexity_length_weight", 0.28)),
            maximum=5.0,
        )
        self.complexity_length_norm_chars = _as_int(
            self.complexity_length_norm_chars,
            int(defaults.get("complexity_length_norm_chars", 140)),
            minimum=1,
        )
        self.reasoning_complexity_threshold = _as_float(
            self.reasoning_complexity_threshold,
            float(defaults.get("reasoning_complexity_threshold", 0.7)),
        )
        self.reasoning_relationship_threshold = _as_float(
            self.reasoning_relationship_threshold,
            float(defaults.get("reasoning_relationship_threshold", 0.4)),
        )
        self.high_relationship_routing_threshold = _as_float(
            self.high_relationship_routing_threshold,
            float(defaults.get("high_relationship_routing_threshold", 0.7)),
        )
        self.relation_hit_intensity_boost_base = _as_float(
            self.relation_hit_intensity_boost_base,
            float(defaults.get("relation_hit_intensity_boost_base", 0.45)),
        )
        self.relation_hit_intensity_boost_step = _as_float(
            self.relation_hit_intensity_boost_step,
            float(defaults.get("relation_hit_intensity_boost_step", 0.12)),
            maximum=5.0,
        )
        self.relation_hit_complexity_boost_base = _as_float(
            self.relation_hit_complexity_boost_base,
            float(defaults.get("relation_hit_complexity_boost_base", 0.55)),
        )
        self.relation_hit_complexity_boost_step = _as_float(
            self.relation_hit_complexity_boost_step,
            float(defaults.get("relation_hit_complexity_boost_step", 0.08)),
            maximum=5.0,
        )
        for field_name, minimum in (
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
                _as_int(getattr(self, field_name), int(defaults.get(field_name, getattr(self, field_name))), minimum=minimum),
            )
        for field_name in (
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
                _as_float(getattr(self, field_name), float(defaults.get(field_name, getattr(self, field_name)))),
            )

    @classmethod
    def from_config(cls, config) -> "QuerySemanticRuntimeSettings":
        defaults = _SEMANTIC_DEFAULTS
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
        return {field.name: getattr(self, field.name) for field in self.__dataclass_fields__.values()}


__all__ = ["QuerySemanticRuntimeSettings"]
