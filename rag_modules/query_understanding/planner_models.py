"""Structured planning models for query understanding."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List

from ..query_constraints import QueryConstraints
from ..retrieval.runtime_profile import QuerySemanticRuntimeSettings
from ..semantic_schema import SEMANTIC_SCHEMA_VERSION
from .graph_intent import infer_query_semantic_profile
from .registry import (
    GRAPH_QUERY_TYPES,
    GRAPH_RELATION_TYPES,
    GRAPH_ROUTING_STRATEGIES,
    QuerySemanticProfile,
)

_VALID_STRATEGIES = set(GRAPH_ROUTING_STRATEGIES)
_VALID_GRAPH_QUERY_TYPES = set(GRAPH_QUERY_TYPES)
_SCHEMA_RELATION_TYPES = list(GRAPH_RELATION_TYPES)


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
        if isinstance(semantic_profile, QuerySemanticProfile):
            resolved_profile = semantic_profile
        else:
            resolved_profile = QuerySemanticProfile.from_dict(semantic_profile)
        if not resolved_profile.query:
            resolved_profile = infer_query_semantic_profile(query, settings=semantic_settings)

        validation_errors = []
        constraints = QueryConstraints.from_dict(
            data.get("constraints") or resolved_profile.constraints or {}
        )

        strategy = str(data.get("strategy") or "hybrid_traditional")
        if strategy not in _VALID_STRATEGIES:
            validation_errors.append(f"invalid_strategy:{strategy}")
            strategy = "combined" if constraints.has_constraints() else "hybrid_traditional"

        graph_query_type = str(data.get("graph_query_type") or resolved_profile.query_type or "subgraph")
        if graph_query_type not in _VALID_GRAPH_QUERY_TYPES:
            validation_errors.append(f"invalid_graph_query_type:{graph_query_type}")
            graph_query_type = (
                resolved_profile.query_type
                if resolved_profile.query_type in _VALID_GRAPH_QUERY_TYPES
                else "subgraph"
            )

        complexity = _clamp_float(data.get("complexity"), 0.5)
        relationship_intensity = _clamp_float(data.get("relationship_intensity"), 0.5)
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

        entity_keywords = _as_list(data.get("entity_keywords")) or list(resolved_profile.entity_keywords)
        topic_keywords = _as_list(data.get("topic_keywords")) or list(resolved_profile.topic_keywords)
        source_entities = _as_list(data.get("source_entities")) or list(resolved_profile.source_entities)
        target_entities = _as_list(data.get("target_entities")) or list(resolved_profile.target_entities)
        relation_types = [
            relation
            for relation in (_as_list(data.get("relation_types")) or list(resolved_profile.relation_types))
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


__all__ = ["QueryPlan"]

