"""Query planning and semantic profile DTOs."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List

from ..domain.shared.query_constraints import QueryConstraints
from ..domain.shared.semantic_schema import SEMANTIC_RELATION_TYPES, SEMANTIC_SCHEMA_VERSION
from ..query_policy import get_query_policy
from .query_settings import QuerySemanticRuntimeSettings

_POLICY = get_query_policy()
_VALID_STRATEGIES = set(_POLICY.graph_routing_strategies)
_VALID_GRAPH_QUERY_TYPES = set(_POLICY.graph_query_types)
_SCHEMA_RELATION_TYPES = tuple(
    dict.fromkeys([*_POLICY.graph_relation_types, *SEMANTIC_RELATION_TYPES])
)


def _dedupe_preserve_order(values: Iterable[Any]) -> List[str]:
    seen = set()
    result: List[str] = []
    for value in values or []:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def _as_list(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return [str(value).strip()] if str(value).strip() else []


def _clamp_float(value: Any, default: float = 0.5) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = default
    return max(0.0, min(1.0, number))


def _clamp_int(value: Any, default: int = 2, minimum: int = 1, maximum: int = 32) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = default
    return max(minimum, min(maximum, number))


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
    query_type: str = "entity_relation"
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

    @classmethod
    def from_dict(cls, data: Dict[str, Any] | None) -> "QuerySemanticProfile":
        payload = dict(data or {})
        score_breakdown = payload.get("score_breakdown") or {}
        return cls(
            query=str(payload.get("query") or ""),
            query_type=str(payload.get("query_type") or "entity_relation"),
            source_entities=_dedupe_preserve_order(payload.get("source_entities") or []),
            target_entities=_dedupe_preserve_order(payload.get("target_entities") or []),
            relation_types=_dedupe_preserve_order(payload.get("relation_types") or []),
            entity_keywords=_dedupe_preserve_order(payload.get("entity_keywords") or []),
            topic_keywords=_dedupe_preserve_order(payload.get("topic_keywords") or []),
            constraints=dict(payload.get("constraints") or {}),
            complexity=float(payload.get("complexity", 0.5) or 0.5),
            relationship_intensity=float(payload.get("relationship_intensity", 0.5) or 0.5),
            reasoning_required=bool(payload.get("reasoning_required")),
            needs_recipe_recommendation=bool(payload.get("needs_recipe_recommendation")),
            recommendation_hits=_dedupe_preserve_order(payload.get("recommendation_hits") or []),
            relation_hits=_dedupe_preserve_order(payload.get("relation_hits") or []),
            constraint_hits=_dedupe_preserve_order(payload.get("constraint_hits") or []),
            structural_hits=_dedupe_preserve_order(payload.get("structural_hits") or []),
            fast_rule_hits=_dedupe_preserve_order(payload.get("fast_rule_hits") or []),
            score_breakdown=(
                score_breakdown
                if isinstance(score_breakdown, QuerySemanticScoreBreakdown)
                else QuerySemanticScoreBreakdown.from_dict(score_breakdown)
            ),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "query": self.query,
            "query_type": self.query_type,
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


@dataclass
class QueryPlan:
    query: str
    intent: str = "qa"
    complexity: float = 0.5
    relationship_intensity: float = 0.5
    reasoning_required: bool = False
    strategy: str = "hybrid_traditional"
    confidence: float = 0.6
    reasoning: str = "rule-based fallback"
    entity_keywords: List[str] = field(default_factory=list)
    topic_keywords: List[str] = field(default_factory=list)
    graph_query_type: str = "subgraph"
    source_entities: List[str] = field(default_factory=list)
    target_entities: List[str] = field(default_factory=list)
    relation_types: List[str] = field(default_factory=list)
    max_depth: int = 2
    constraints: QueryConstraints = field(default_factory=QueryConstraints)
    needs_recipe_recommendation: bool = False
    answer_style: str = "concise"
    planner_version: str = f"query-planner-v3:{SEMANTIC_SCHEMA_VERSION}"
    used_cache: bool = False
    fallback_reason: str = ""
    planner_mode: str = "llm"
    semantic_profile: QuerySemanticProfile = field(default_factory=QuerySemanticProfile)
    raw_plan: Dict[str, Any] = field(default_factory=dict)
    validation_errors: List[str] = field(default_factory=list)

    @property
    def entity_count(self) -> int:
        return len(set(self.entity_keywords + self.source_entities + self.target_entities))

    @classmethod
    def from_dict(
        cls,
        query: str,
        data: Dict[str, Any],
        *,
        semantic_settings: QuerySemanticRuntimeSettings | None = None,
    ) -> "QueryPlan":
        semantic_settings = semantic_settings or QuerySemanticRuntimeSettings()
        semantic_profile = data.get("semantic_profile")
        resolved_profile = (
            semantic_profile
            if isinstance(semantic_profile, QuerySemanticProfile)
            else QuerySemanticProfile.from_dict(semantic_profile)
        )

        validation_errors = []
        constraints = QueryConstraints.from_dict(
            data.get("constraints") or resolved_profile.constraints or {}
        )

        strategy = str(data.get("strategy") or "hybrid_traditional")
        if strategy not in _VALID_STRATEGIES:
            validation_errors.append(f"invalid_strategy:{strategy}")
            strategy = "combined" if constraints.has_constraints() else "hybrid_traditional"

        graph_query_type = str(
            data.get("graph_query_type") or resolved_profile.query_type or "subgraph"
        )
        if graph_query_type not in _VALID_GRAPH_QUERY_TYPES:
            validation_errors.append(f"invalid_graph_query_type:{graph_query_type}")
            graph_query_type = (
                resolved_profile.query_type
                if resolved_profile.query_type in _VALID_GRAPH_QUERY_TYPES
                else "subgraph"
            )

        complexity = _clamp_float(data.get("complexity"), resolved_profile.complexity)
        relationship_intensity = _clamp_float(
            data.get("relationship_intensity"),
            resolved_profile.relationship_intensity,
        )
        reasoning_required = bool(data.get("reasoning_required"))
        if (
            complexity >= semantic_settings.reasoning_complexity_threshold
            or relationship_intensity >= semantic_settings.reasoning_relationship_threshold
            or resolved_profile.reasoning_required
        ):
            reasoning_required = True

        needs_recipe_recommendation = bool(
            data.get("needs_recipe_recommendation")
            or constraints.needs_recipe_recommendation
            or resolved_profile.needs_recipe_recommendation
        )
        constraints.needs_recipe_recommendation = needs_recipe_recommendation

        entity_keywords = _as_list(data.get("entity_keywords")) or list(
            resolved_profile.entity_keywords
        )
        topic_keywords = _as_list(data.get("topic_keywords")) or list(
            resolved_profile.topic_keywords
        )
        source_entities = _as_list(data.get("source_entities")) or list(
            resolved_profile.source_entities
        )
        target_entities = _as_list(data.get("target_entities")) or list(
            resolved_profile.target_entities
        )
        relation_types = [
            relation
            for relation in (
                _as_list(data.get("relation_types")) or list(resolved_profile.relation_types)
            )
            if relation in _SCHEMA_RELATION_TYPES
        ]

        return cls(
            query=query,
            intent=str(data.get("intent") or "qa"),
            complexity=complexity,
            relationship_intensity=relationship_intensity,
            reasoning_required=reasoning_required,
            strategy=strategy,
            confidence=_clamp_float(data.get("confidence"), 0.6),
            reasoning=str(data.get("reasoning") or ""),
            entity_keywords=entity_keywords[: semantic_settings.entity_keyword_limit],
            topic_keywords=topic_keywords[: semantic_settings.topic_keyword_limit],
            graph_query_type=graph_query_type,
            source_entities=source_entities[: semantic_settings.source_entity_limit],
            target_entities=target_entities[: semantic_settings.target_entity_limit],
            relation_types=relation_types,
            max_depth=_clamp_int(
                data.get("max_depth"),
                2,
                maximum=semantic_settings.graph_query_max_depth_cap,
            ),
            constraints=constraints,
            needs_recipe_recommendation=needs_recipe_recommendation,
            answer_style=str(data.get("answer_style") or "concise"),
            semantic_profile=resolved_profile,
            raw_plan=dict(data),
            validation_errors=validation_errors,
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "query": self.query,
            "intent": self.intent,
            "complexity": self.complexity,
            "relationship_intensity": self.relationship_intensity,
            "reasoning_required": self.reasoning_required,
            "strategy": self.strategy,
            "confidence": self.confidence,
            "reasoning": self.reasoning,
            "entity_keywords": self.entity_keywords,
            "topic_keywords": self.topic_keywords,
            "graph_query_type": self.graph_query_type,
            "source_entities": self.source_entities,
            "target_entities": self.target_entities,
            "relation_types": self.relation_types,
            "max_depth": self.max_depth,
            "constraints": self.constraints.to_dict(),
            "needs_recipe_recommendation": self.needs_recipe_recommendation,
            "answer_style": self.answer_style,
            "planner_version": self.planner_version,
            "used_cache": self.used_cache,
            "fallback_reason": self.fallback_reason,
            "planner_mode": self.planner_mode,
            "semantic_profile": self.semantic_profile.to_dict(),
            "validation_errors": self.validation_errors,
        }


__all__ = ["QueryPlan", "QuerySemanticProfile", "QuerySemanticScoreBreakdown"]
