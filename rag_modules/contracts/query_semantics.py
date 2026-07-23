"""Semantic profile DTOs for query planning."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

from ..kernel.json_types import (
    JsonObject,
    as_string_list,
    coerce_float,
    coerce_int,
    coerce_json_object,
)
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
    def from_dict(cls, data: Mapping[str, object] | None) -> "QuerySemanticScoreBreakdown":
        payload = dict(data or {})
        return cls(
            relation_hit_count=coerce_int(payload.get("relation_hit_count")),
            constraint_hit_count=coerce_int(payload.get("constraint_hit_count")),
            structural_hit_count=coerce_int(payload.get("structural_hit_count")),
            fast_rule_hit_count=coerce_int(payload.get("fast_rule_hit_count")),
            length_factor=coerce_float(payload.get("length_factor")),
            lexical_relationship_intensity=coerce_float(
                payload.get("lexical_relationship_intensity")
            ),
            relation_hit_intensity_boost=coerce_float(payload.get("relation_hit_intensity_boost")),
            lexical_complexity=coerce_float(payload.get("lexical_complexity")),
            relation_hit_complexity_boost=coerce_float(
                payload.get("relation_hit_complexity_boost")
            ),
            relationship_intensity=coerce_float(payload.get("relationship_intensity")),
            complexity=coerce_float(payload.get("complexity")),
        )

    def to_dict(self) -> JsonObject:
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
    source_entities: list[str] = field(default_factory=list)
    target_entities: list[str] = field(default_factory=list)
    relation_types: list[str] = field(default_factory=list)
    entity_keywords: list[str] = field(default_factory=list)
    topic_keywords: list[str] = field(default_factory=list)
    constraints: JsonObject = field(default_factory=dict)
    complexity: float = 0.5
    relationship_intensity: float = 0.5
    reasoning_required: bool = False
    needs_recipe_recommendation: bool = False
    recommendation_hits: list[str] = field(default_factory=list)
    relation_hits: list[str] = field(default_factory=list)
    constraint_hits: list[str] = field(default_factory=list)
    structural_hits: list[str] = field(default_factory=list)
    fast_rule_hits: list[str] = field(default_factory=list)
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
    def from_dict(cls, data: Mapping[str, object] | None) -> "QuerySemanticProfile":
        payload = dict(data or {})
        score_breakdown = payload.get("score_breakdown") or {}
        return cls(
            query=str(payload.get("query") or ""),
            query_type=graph_query_type_or_default(
                payload.get("query_type"),
                GraphQueryType.ENTITY_RELATION,
            ),
            source_entities=as_string_list(payload.get("source_entities")),
            target_entities=as_string_list(payload.get("target_entities")),
            relation_types=as_string_list(payload.get("relation_types")),
            entity_keywords=as_string_list(payload.get("entity_keywords")),
            topic_keywords=as_string_list(payload.get("topic_keywords")),
            constraints=coerce_json_object(payload.get("constraints")),
            complexity=coerce_float(payload.get("complexity"), 0.5),
            relationship_intensity=coerce_float(payload.get("relationship_intensity"), 0.5),
            reasoning_required=bool(payload.get("reasoning_required")),
            needs_recipe_recommendation=bool(payload.get("needs_recipe_recommendation")),
            recommendation_hits=as_string_list(payload.get("recommendation_hits")),
            relation_hits=as_string_list(payload.get("relation_hits")),
            constraint_hits=as_string_list(payload.get("constraint_hits")),
            structural_hits=as_string_list(payload.get("structural_hits")),
            fast_rule_hits=as_string_list(payload.get("fast_rule_hits")),
            score_breakdown=(
                score_breakdown
                if isinstance(score_breakdown, QuerySemanticScoreBreakdown)
                else QuerySemanticScoreBreakdown.from_dict(
                    score_breakdown if isinstance(score_breakdown, Mapping) else None
                )
            ),
        )

    def to_dict(self) -> JsonObject:
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
