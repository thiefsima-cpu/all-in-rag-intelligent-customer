"""Semantic profile DTOs for query planning."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List

from ..kernel.json_types import dedupe_preserve_order
from .query_types import (
    GraphQueryType,
    graph_query_type_or_default,
    graph_query_type_value,
)


@dataclass(frozen=True)
class QuerySemanticScoreBreakdown:
    relation_hit_count: int = 0
    constraint_hit_count: int = 0
    structural_hit_count: int = 0
    fast_rule_hit_count: int = 0
    length_factor: float = 0.0
    lexical_relationship_intensity: float = 0.0
    relation_hit_intensity_boost: float = 0.0
    lexical_complexity: float = 0.0
    relation_hit_complexity_boost: float = 0.0
    relationship_intensity: float = 0.0
    complexity: float = 0.0

    @classmethod
    def from_dict(cls, data: Dict[str, Any] | None) -> "QuerySemanticScoreBreakdown":
        payload = dict(data or {})
        return cls(
            relation_hit_count=int(payload.get("relation_hit_count", 0) or 0),
            constraint_hit_count=int(payload.get("constraint_hit_count", 0) or 0),
            structural_hit_count=int(payload.get("structural_hit_count", 0) or 0),
            fast_rule_hit_count=int(payload.get("fast_rule_hit_count", 0) or 0),
            length_factor=float(payload.get("length_factor", 0.0) or 0.0),
            lexical_relationship_intensity=float(
                payload.get("lexical_relationship_intensity", 0.0) or 0.0
            ),
            relation_hit_intensity_boost=float(
                payload.get("relation_hit_intensity_boost", 0.0) or 0.0
            ),
            lexical_complexity=float(payload.get("lexical_complexity", 0.0) or 0.0),
            relation_hit_complexity_boost=float(
                payload.get("relation_hit_complexity_boost", 0.0) or 0.0
            ),
            relationship_intensity=float(payload.get("relationship_intensity", 0.0) or 0.0),
            complexity=float(payload.get("complexity", 0.0) or 0.0),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "relation_hit_count": self.relation_hit_count,
            "constraint_hit_count": self.constraint_hit_count,
            "structural_hit_count": self.structural_hit_count,
            "fast_rule_hit_count": self.fast_rule_hit_count,
            "length_factor": self.length_factor,
            "lexical_relationship_intensity": self.lexical_relationship_intensity,
            "relation_hit_intensity_boost": self.relation_hit_intensity_boost,
            "lexical_complexity": self.lexical_complexity,
            "relation_hit_complexity_boost": self.relation_hit_complexity_boost,
            "relationship_intensity": self.relationship_intensity,
            "complexity": self.complexity,
        }


@dataclass(frozen=True)
class QuerySemanticProfile:
    query: str = ""
    query_type: GraphQueryType | str = GraphQueryType.ENTITY_RELATION
    source_entities: List[str] = field(default_factory=list)
    target_entities: List[str] = field(default_factory=list)
    relation_types: List[str] = field(default_factory=list)
    entity_keywords: List[str] = field(default_factory=list)
    topic_keywords: List[str] = field(default_factory=list)
    constraints: Dict[str, Any] = field(default_factory=dict)
    complexity: float = 0.5
    relationship_intensity: float = 0.5
    reasoning_required: bool = False
    needs_recipe_recommendation: bool = False
    recommendation_hits: List[str] = field(default_factory=list)
    relation_hits: List[str] = field(default_factory=list)
    constraint_hits: List[str] = field(default_factory=list)
    structural_hits: List[str] = field(default_factory=list)
    fast_rule_hits: List[str] = field(default_factory=list)
    score_breakdown: QuerySemanticScoreBreakdown = field(
        default_factory=QuerySemanticScoreBreakdown
    )

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "query_type",
            graph_query_type_or_default(self.query_type, GraphQueryType.ENTITY_RELATION),
        )

    @property
    def query_type_value(self) -> str:
        return graph_query_type_value(self.query_type)

    @classmethod
    def from_dict(cls, data: Dict[str, Any] | None) -> "QuerySemanticProfile":
        payload = dict(data or {})
        score_breakdown = payload.get("score_breakdown") or {}
        return cls(
            query=str(payload.get("query") or ""),
            query_type=graph_query_type_or_default(
                payload.get("query_type"),
                GraphQueryType.ENTITY_RELATION,
            ),
            source_entities=dedupe_preserve_order(payload.get("source_entities") or []),
            target_entities=dedupe_preserve_order(payload.get("target_entities") or []),
            relation_types=dedupe_preserve_order(payload.get("relation_types") or []),
            entity_keywords=dedupe_preserve_order(payload.get("entity_keywords") or []),
            topic_keywords=dedupe_preserve_order(payload.get("topic_keywords") or []),
            constraints=dict(payload.get("constraints") or {}),
            complexity=float(payload.get("complexity", 0.5) or 0.5),
            relationship_intensity=float(payload.get("relationship_intensity", 0.5) or 0.5),
            reasoning_required=bool(payload.get("reasoning_required")),
            needs_recipe_recommendation=bool(payload.get("needs_recipe_recommendation")),
            recommendation_hits=dedupe_preserve_order(payload.get("recommendation_hits") or []),
            relation_hits=dedupe_preserve_order(payload.get("relation_hits") or []),
            constraint_hits=dedupe_preserve_order(payload.get("constraint_hits") or []),
            structural_hits=dedupe_preserve_order(payload.get("structural_hits") or []),
            fast_rule_hits=dedupe_preserve_order(payload.get("fast_rule_hits") or []),
            score_breakdown=(
                score_breakdown
                if isinstance(score_breakdown, QuerySemanticScoreBreakdown)
                else QuerySemanticScoreBreakdown.from_dict(score_breakdown)
            ),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "query": self.query,
            "query_type": self.query_type_value,
            "source_entities": list(self.source_entities),
            "target_entities": list(self.target_entities),
            "relation_types": list(self.relation_types),
            "entity_keywords": list(self.entity_keywords),
            "topic_keywords": list(self.topic_keywords),
            "constraints": dict(self.constraints or {}),
            "complexity": self.complexity,
            "relationship_intensity": self.relationship_intensity,
            "reasoning_required": self.reasoning_required,
            "needs_recipe_recommendation": self.needs_recipe_recommendation,
            "recommendation_hits": list(self.recommendation_hits),
            "relation_hits": list(self.relation_hits),
            "constraint_hits": list(self.constraint_hits),
            "structural_hits": list(self.structural_hits),
            "fast_rule_hits": list(self.fast_rule_hits),
            "score_breakdown": self.score_breakdown.to_dict(),
        }


__all__ = ["QuerySemanticProfile", "QuerySemanticScoreBreakdown"]
