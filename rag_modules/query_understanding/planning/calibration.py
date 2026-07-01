"""Calibration rules that align planner output with shared query semantics."""

from __future__ import annotations

from ...contracts import (
    GraphQueryType,
    QueryPlan,
    QuerySemanticProfile,
    QuerySemanticRuntimeSettings,
)
from ...domain.shared.query_constraints import QueryConstraints
from ...query_policy import get_query_policy
from ...runtime import SearchStrategy
from ..features import fallback_entity_phrases, fallback_keywords, normalize_graph_sources
from ..graph_intent import infer_graph_max_depth, infer_query_semantic_profile

_VALID_STRATEGIES = {strategy.value for strategy in SearchStrategy}
_VALID_GRAPH_QUERY_TYPES = {query_type.value for query_type in GraphQueryType}


def _strategy_value(strategy: SearchStrategy | str) -> str:
    if isinstance(strategy, SearchStrategy):
        return strategy.value
    return str(strategy or SearchStrategy.HYBRID_TRADITIONAL.value)


def _graph_query_type_value(query_type: GraphQueryType | str) -> str:
    if isinstance(query_type, GraphQueryType):
        return query_type.value
    return str(query_type or "")


def _graph_query_type_enum(
    query_type: GraphQueryType | str,
    default: GraphQueryType = GraphQueryType.ENTITY_RELATION,
) -> GraphQueryType:
    if isinstance(query_type, GraphQueryType):
        return query_type
    try:
        return GraphQueryType(str(query_type or default.value))
    except ValueError:
        return default


class QueryPlanCalibrator:
    def __init__(self, settings: QuerySemanticRuntimeSettings) -> None:
        self.settings = settings
        self.policy = get_query_policy().routing

    def has_meaningful_constraints(
        self,
        constraints: QueryConstraints,
        profile: QuerySemanticProfile,
    ) -> bool:
        meaningful_fields = set(self.policy.meaningful_constraint_fields)
        if (
            profile.needs_recipe_recommendation
            and "needs_recipe_recommendation" in meaningful_fields
        ):
            return True
        for field_name in meaningful_fields:
            value = getattr(constraints, field_name, None)
            if isinstance(value, bool):
                if value:
                    return True
                continue
            if value is not None and bool(value):
                return True
        return False

    def is_graph_first_profile(self, profile: QuerySemanticProfile) -> bool:
        query_type = _graph_query_type_enum(profile.query_type)
        if query_type.value in set(self.policy.graph_first_query_types):
            return True
        if query_type is not GraphQueryType.MULTI_HOP:
            return False
        required_relation_hits = self.policy.multi_hop_graph_first_relation_hits
        return bool(
            len(profile.relation_hits or []) >= required_relation_hits
            or len(profile.structural_hits or []) >= required_relation_hits
            or profile.relationship_intensity >= self.settings.multi_hop_hint_relationship_threshold
        )

    def resolve_strategy(
        self,
        *,
        current_strategy: SearchStrategy | str,
        profile: QuerySemanticProfile,
        constraints: QueryConstraints,
        complexity: float,
        relationship_intensity: float,
    ) -> str:
        meaningful_constraints = self.has_meaningful_constraints(constraints, profile)
        graph_first = self.is_graph_first_profile(profile)

        if graph_first:
            return (
                SearchStrategy.COMBINED.value
                if meaningful_constraints
                else SearchStrategy.GRAPH_RAG.value
            )

        if relationship_intensity >= self.settings.high_relationship_routing_threshold:
            if meaningful_constraints and (
                relationship_intensity >= self.settings.combined_strategy_relationship_threshold
                or complexity >= self.settings.combined_strategy_complexity_threshold
            ):
                return SearchStrategy.COMBINED.value
            return SearchStrategy.GRAPH_RAG.value

        current_strategy_value = _strategy_value(current_strategy)
        if current_strategy_value == SearchStrategy.COMBINED.value and not meaningful_constraints:
            return SearchStrategy.HYBRID_TRADITIONAL.value

        if current_strategy_value in _VALID_STRATEGIES:
            return current_strategy_value
        return (
            SearchStrategy.COMBINED.value
            if meaningful_constraints
            else SearchStrategy.HYBRID_TRADITIONAL.value
        )

    def resolve_graph_query_type(
        self,
        current_type: GraphQueryType | str,
        profile: QuerySemanticProfile,
    ) -> GraphQueryType:
        current_type_value = _graph_query_type_value(current_type)
        profile_query_type = _graph_query_type_enum(profile.query_type)
        if profile_query_type in {
            GraphQueryType.PATH_FINDING,
            GraphQueryType.SUBGRAPH,
            GraphQueryType.CLUSTERING,
        }:
            return profile_query_type
        if (
            profile_query_type is GraphQueryType.MULTI_HOP
            and current_type_value == GraphQueryType.SUBGRAPH.value
            and profile.relationship_intensity
            >= self.settings.multi_hop_hint_relationship_threshold
        ):
            return GraphQueryType.MULTI_HOP
        if current_type_value in _VALID_GRAPH_QUERY_TYPES:
            return GraphQueryType(current_type_value)
        return profile_query_type

    def calibrate(self, plan: QueryPlan) -> None:
        query = plan.query or ""
        profile = infer_query_semantic_profile(query, settings=self.settings)
        plan.semantic_profile = profile

        plan.complexity = max(plan.complexity, profile.complexity)
        plan.relationship_intensity = max(
            plan.relationship_intensity, profile.relationship_intensity
        )
        plan.reasoning_required = bool(
            plan.reasoning_required
            or profile.reasoning_required
            or plan.complexity >= self.settings.reasoning_complexity_threshold
            or plan.relationship_intensity >= self.settings.reasoning_relationship_threshold
        )
        plan.constraints.needs_recipe_recommendation = bool(
            plan.constraints.needs_recipe_recommendation or profile.needs_recipe_recommendation
        )

        resolved_strategy = self.resolve_strategy(
            current_strategy=plan.strategy,
            profile=profile,
            constraints=plan.constraints,
            complexity=plan.complexity,
            relationship_intensity=plan.relationship_intensity,
        )
        current_strategy = _strategy_value(plan.strategy)
        if resolved_strategy != current_strategy:
            strategy_label = self.policy.validation_labels["strategy"]
            plan.validation_errors.append(
                f"{strategy_label}:{current_strategy}->{resolved_strategy}"
            )
            plan.strategy = SearchStrategy(resolved_strategy)

        resolved_query_type = self.resolve_graph_query_type(plan.graph_query_type, profile)
        if resolved_query_type != plan.graph_query_type:
            graph_query_type_label = self.policy.validation_labels["graph_query_type"]
            plan.validation_errors.append(
                f"{graph_query_type_label}:"
                f"{plan.graph_query_type_value}->{resolved_query_type.value}"
            )
            plan.graph_query_type = resolved_query_type

        for relation_type in profile.relation_types:
            if relation_type not in plan.relation_types:
                plan.relation_types.append(relation_type)

        if not plan.entity_keywords:
            plan.entity_keywords = list(
                profile.entity_keywords[: self.settings.entity_keyword_limit]
            )
        if not plan.topic_keywords:
            plan.topic_keywords = list(profile.topic_keywords[: self.settings.topic_keyword_limit])
        if not plan.target_entities:
            plan.target_entities = list(
                profile.target_entities[: self.settings.target_entity_limit]
            )

        if (
            _strategy_value(plan.strategy)
            in {SearchStrategy.GRAPH_RAG.value, SearchStrategy.COMBINED.value}
            and not plan.source_entities
        ):
            fallback_candidates = (
                profile.source_entities
                or fallback_entity_phrases(query)
                or profile.entity_keywords
                or fallback_keywords(query)
            )
            plan.source_entities = normalize_graph_sources(
                fallback_candidates[: self.settings.source_entity_limit]
            )
            if plan.source_entities:
                plan.validation_errors.append(self.policy.validation_labels["source_entities"])

        plan.max_depth = max(
            1,
            min(
                int(
                    plan.max_depth
                    or infer_graph_max_depth(
                        plan.graph_query_type_value,
                        plan.relationship_intensity,
                        settings=self.settings,
                    )
                ),
                self.settings.graph_query_max_depth_cap,
            ),
        )


__all__ = ["QueryPlanCalibrator"]
