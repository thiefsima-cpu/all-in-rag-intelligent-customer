"""Calibration rules that align planner output with shared query semantics."""

from __future__ import annotations

from ...contracts import (
    GraphQueryType,
    QueryPlan,
    QuerySemanticProfile,
    QuerySemanticRuntimeSettings,
)
from ...contracts.query_constraints import QueryConstraints
from ...domains.contracts import DomainQueryConstraintSchema
from ...kernel.routing import SearchStrategy
from ...query_policy import get_query_policy
from ...query_policy.models import QueryPolicyBundle
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
    def __init__(
        self,
        settings: QuerySemanticRuntimeSettings,
        *,
        policy_bundle: QueryPolicyBundle | None = None,
        constraint_schema: DomainQueryConstraintSchema | None = None,
    ) -> None:
        self.settings = settings
        self.policy_bundle = policy_bundle or get_query_policy()
        self.constraint_schema = constraint_schema
        self.policy = self.policy_bundle.routing

    def has_meaningful_constraints(
        self,
        constraints: QueryConstraints,
        profile: QuerySemanticProfile,
    ) -> bool:
        meaningful_fields = set(self.policy.meaningful_constraint_fields)
        for field_name in meaningful_fields:
            value = constraints.field_value(field_name)
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

    def _strategy_from_policy_rule(self, profile: QuerySemanticProfile) -> str | None:
        relation_types = set(profile.relation_types)
        for rule in self.policy.strategy_rules:
            if rule.relation_types_all and not set(rule.relation_types_all) <= relation_types:
                continue
            if rule.relation_types_any and not set(rule.relation_types_any) & relation_types:
                continue
            if (
                rule.maximum_structural_hit_count is not None
                and len(profile.structural_hits) > rule.maximum_structural_hit_count
            ):
                continue
            return rule.strategy
        return None

    def resolve_strategy(
        self,
        *,
        current_strategy: SearchStrategy | str,
        profile: QuerySemanticProfile,
        constraints: QueryConstraints,
        complexity: float,
        relationship_intensity: float,
    ) -> str:
        policy_strategy = self._strategy_from_policy_rule(profile)
        if policy_strategy is not None:
            return policy_strategy

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

    def _apply_profile(self, plan: QueryPlan, profile: QuerySemanticProfile) -> None:
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
        plan.recommendation_required = bool(
            plan.recommendation_required or profile.recommendation_required
        )

    def _calibrate_strategy(self, plan: QueryPlan, profile: QuerySemanticProfile) -> None:
        resolved = self.resolve_strategy(
            current_strategy=plan.strategy,
            profile=profile,
            constraints=plan.constraints,
            complexity=plan.complexity,
            relationship_intensity=plan.relationship_intensity,
        )
        current = _strategy_value(plan.strategy)
        if resolved == current:
            return
        label = self.policy.validation_labels["strategy"]
        plan.validation_errors.append(f"{label}:{current}->{resolved}")
        plan.strategy = SearchStrategy(resolved)

    def _calibrate_graph_query_type(self, plan: QueryPlan, profile: QuerySemanticProfile) -> None:
        resolved = self.resolve_graph_query_type(plan.graph_query_type, profile)
        if resolved == plan.graph_query_type:
            return
        label = self.policy.validation_labels["graph_query_type"]
        plan.validation_errors.append(f"{label}:{plan.graph_query_type_value}->{resolved.value}")
        plan.graph_query_type = resolved

    def _fill_missing_terms(self, plan: QueryPlan, profile: QuerySemanticProfile) -> None:
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

    def _fill_graph_sources(self, plan: QueryPlan, profile: QuerySemanticProfile) -> None:
        if (
            _strategy_value(plan.strategy)
            not in {
                SearchStrategy.GRAPH_RAG.value,
                SearchStrategy.COMBINED.value,
            }
            or plan.source_entities
        ):
            return
        query = plan.query or ""
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

    def _clamp_max_depth(self, plan: QueryPlan) -> None:
        inferred = plan.max_depth or infer_graph_max_depth(
            plan.graph_query_type_value,
            plan.relationship_intensity,
            settings=self.settings,
            policy_bundle=self.policy_bundle,
        )
        plan.max_depth = max(
            1,
            min(int(inferred), self.settings.graph_query_max_depth_cap),
        )

    def calibrate(self, plan: QueryPlan) -> None:
        profile = infer_query_semantic_profile(
            plan.query or "",
            settings=self.settings,
            policy_bundle=self.policy_bundle,
            constraint_schema=self.constraint_schema,
        )
        self._apply_profile(plan, profile)
        self._calibrate_strategy(plan, profile)
        self._calibrate_graph_query_type(plan, profile)
        self._fill_missing_terms(plan, profile)
        self._fill_graph_sources(plan, profile)
        self._clamp_max_depth(plan)


__all__ = ["QueryPlanCalibrator"]
