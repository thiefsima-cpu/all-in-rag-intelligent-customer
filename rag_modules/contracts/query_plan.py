"""Query plan DTO and parsing logic."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List

from ..kernel.json_types import as_string_list, clamp_float, clamp_int
from ..kernel.routing import SearchStrategy
from ..kernel.semantic_schema import SEMANTIC_SCHEMA_VERSION
from .query_constraints import QueryConstraints
from .query_semantics import QuerySemanticProfile
from .query_settings import QuerySemanticRuntimeSettings
from .query_types import (
    GraphQueryType,
    QueryPlannerMode,
    graph_query_type,
    graph_query_type_or_default,
    graph_query_type_value,
    query_planner_mode,
    search_strategy,
)


def _resolve_semantic_profile(data: Dict[str, Any]) -> QuerySemanticProfile:
    profile = data.get("semantic_profile")
    if isinstance(profile, QuerySemanticProfile):
        return profile
    return QuerySemanticProfile.from_dict(profile)


def _resolve_plan_strategy(
    data: Dict[str, Any],
    constraints: QueryConstraints,
    validation_errors: List[str],
) -> SearchStrategy:
    raw_strategy = str(data.get("strategy") or SearchStrategy.HYBRID_TRADITIONAL.value)
    try:
        return SearchStrategy(raw_strategy)
    except ValueError:
        validation_errors.append(f"invalid_strategy:{raw_strategy}")
        if constraints.has_constraints() or constraints.needs_recipe_recommendation:
            return SearchStrategy.COMBINED
        return SearchStrategy.HYBRID_TRADITIONAL


def _resolve_plan_graph_query_type(
    data: Dict[str, Any],
    profile: QuerySemanticProfile,
    validation_errors: List[str],
) -> GraphQueryType:
    raw_type = str(
        data.get("graph_query_type") or profile.query_type_value or GraphQueryType.SUBGRAPH.value
    )
    try:
        return GraphQueryType(raw_type)
    except ValueError:
        validation_errors.append(f"invalid_graph_query_type:{raw_type}")
        return graph_query_type_or_default(profile.query_type, GraphQueryType.SUBGRAPH)


def _profile_values(data: Dict[str, Any], key: str, fallback: Iterable[str]) -> List[str]:
    return as_string_list(data.get(key)) or list(fallback)


@dataclass
class QueryPlan:
    query: str
    intent: str = "qa"
    complexity: float = 0.5
    relationship_intensity: float = 0.5
    reasoning_required: bool = False
    strategy: SearchStrategy | str = "hybrid_traditional"
    confidence: float = 0.6
    reasoning: str = "rule-based fallback"
    entity_keywords: List[str] = field(default_factory=list)
    topic_keywords: List[str] = field(default_factory=list)
    graph_query_type: GraphQueryType | str = GraphQueryType.SUBGRAPH
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
    planner_mode: QueryPlannerMode | str = QueryPlannerMode.LLM
    semantic_profile: QuerySemanticProfile = field(default_factory=QuerySemanticProfile)
    raw_plan: Dict[str, Any] = field(default_factory=dict)
    validation_errors: List[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.strategy = search_strategy(self.strategy)
        self.graph_query_type = graph_query_type(self.graph_query_type)
        self.planner_mode = query_planner_mode(self.planner_mode)

    @property
    def entity_count(self) -> int:
        return len(set(self.entity_keywords + self.source_entities + self.target_entities))

    @property
    def strategy_value(self) -> str:
        return search_strategy(self.strategy).value

    @property
    def planner_mode_value(self) -> str:
        return query_planner_mode(self.planner_mode).value

    @property
    def graph_query_type_value(self) -> str:
        return graph_query_type_value(self.graph_query_type)

    @classmethod
    def from_dict(
        cls,
        query: str,
        data: Dict[str, Any],
        *,
        semantic_settings: QuerySemanticRuntimeSettings,
        schema_relation_types: Iterable[str] | None = None,
    ) -> "QueryPlan":
        allowed_relation_types = (
            frozenset(str(item) for item in schema_relation_types)
            if schema_relation_types is not None
            else None
        )
        resolved_profile = _resolve_semantic_profile(data)
        validation_errors: List[str] = []
        constraints = QueryConstraints.from_dict(
            data.get("constraints") or resolved_profile.constraints or {}
        )
        strategy = _resolve_plan_strategy(data, constraints, validation_errors)
        resolved_graph_query_type = _resolve_plan_graph_query_type(
            data, resolved_profile, validation_errors
        )
        complexity = clamp_float(data.get("complexity"), resolved_profile.complexity)
        relationship_intensity = clamp_float(
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

        entity_keywords = _profile_values(data, "entity_keywords", resolved_profile.entity_keywords)
        topic_keywords = _profile_values(data, "topic_keywords", resolved_profile.topic_keywords)
        source_entities = _profile_values(data, "source_entities", resolved_profile.source_entities)
        target_entities = _profile_values(data, "target_entities", resolved_profile.target_entities)
        relation_types = [
            relation
            for relation in _profile_values(data, "relation_types", resolved_profile.relation_types)
            if allowed_relation_types is None or relation in allowed_relation_types
        ]
        return cls(
            query=query,
            intent=str(data.get("intent") or "qa"),
            complexity=complexity,
            relationship_intensity=relationship_intensity,
            reasoning_required=reasoning_required,
            strategy=strategy,
            confidence=clamp_float(data.get("confidence"), 0.6),
            reasoning=str(data.get("reasoning") or ""),
            entity_keywords=entity_keywords[: semantic_settings.entity_keyword_limit],
            topic_keywords=topic_keywords[: semantic_settings.topic_keyword_limit],
            graph_query_type=resolved_graph_query_type,
            source_entities=source_entities[: semantic_settings.source_entity_limit],
            target_entities=target_entities[: semantic_settings.target_entity_limit],
            relation_types=relation_types,
            max_depth=clamp_int(
                data.get("max_depth"),
                2,
                maximum=semantic_settings.graph_query_max_depth_cap,
            ),
            constraints=constraints,
            needs_recipe_recommendation=needs_recipe_recommendation,
            answer_style=str(data.get("answer_style") or "concise"),
            planner_mode=query_planner_mode(data.get("planner_mode")),
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
            "strategy": self.strategy_value,
            "confidence": self.confidence,
            "reasoning": self.reasoning,
            "entity_keywords": self.entity_keywords,
            "topic_keywords": self.topic_keywords,
            "graph_query_type": self.graph_query_type_value,
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
            "planner_mode": self.planner_mode_value,
            "semantic_profile": self.semantic_profile.to_dict(),
            "validation_errors": self.validation_errors,
        }


__all__ = ["QueryPlan"]
