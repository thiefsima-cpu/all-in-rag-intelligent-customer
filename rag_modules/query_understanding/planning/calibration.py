"""Calibration rules that align planner output with shared query semantics."""

from __future__ import annotations

from ...contracts import QueryPlan, QuerySemanticProfile, QuerySemanticRuntimeSettings
from ...domain.shared.query_constraints import QueryConstraints
from ..features import fallback_entity_phrases, fallback_keywords, normalize_graph_sources
from ..graph_intent import infer_graph_max_depth, infer_query_semantic_profile
from ..registry import GRAPH_QUERY_TYPES, GRAPH_ROUTING_STRATEGIES

_VALID_STRATEGIES = set(GRAPH_ROUTING_STRATEGIES)
_VALID_GRAPH_QUERY_TYPES = set(GRAPH_QUERY_TYPES)


class QueryPlanCalibrator:
    def __init__(self, settings: QuerySemanticRuntimeSettings) -> None:
        self.settings = settings

    def has_meaningful_constraints(
        self,
        constraints: QueryConstraints,
        profile: QuerySemanticProfile,
    ) -> bool:
        return bool(
            profile.needs_recipe_recommendation
            or constraints.needs_recipe_recommendation
            or constraints.ingredients
            or constraints.excluded_ingredients
            or constraints.include_terms
            or constraints.exclude_terms
            or constraints.cuisine_terms
            or constraints.excluded_cuisine_terms
            or constraints.category_terms
            or constraints.health_terms
            or constraints.preference_terms
            or constraints.max_total_minutes is not None
            or constraints.max_prep_minutes is not None
            or constraints.max_cook_minutes is not None
        )

    def is_graph_first_profile(self, profile: QuerySemanticProfile) -> bool:
        if profile.query_type in {"path_finding", "subgraph", "clustering"}:
            return True
        if profile.query_type != "multi_hop":
            return False
        return bool(
            len(profile.relation_hits or []) >= 2
            or len(profile.structural_hits or []) >= 2
            or profile.relationship_intensity >= self.settings.multi_hop_hint_relationship_threshold
        )

    def resolve_strategy(
        self,
        *,
        current_strategy: str,
        profile: QuerySemanticProfile,
        constraints: QueryConstraints,
        complexity: float,
        relationship_intensity: float,
    ) -> str:
        meaningful_constraints = self.has_meaningful_constraints(constraints, profile)
        graph_first = self.is_graph_first_profile(profile)

        if graph_first:
            return "combined" if meaningful_constraints else "graph_rag"

        if relationship_intensity >= self.settings.high_relationship_routing_threshold:
            if meaningful_constraints and (
                relationship_intensity >= self.settings.combined_strategy_relationship_threshold
                or complexity >= self.settings.combined_strategy_complexity_threshold
            ):
                return "combined"
            return "graph_rag"

        if current_strategy == "combined" and not meaningful_constraints:
            return "hybrid_traditional"

        if current_strategy in _VALID_STRATEGIES:
            return current_strategy
        return "combined" if meaningful_constraints else "hybrid_traditional"

    def resolve_graph_query_type(
        self,
        current_type: str,
        profile: QuerySemanticProfile,
    ) -> str:
        if profile.query_type in {"path_finding", "subgraph", "clustering"}:
            return profile.query_type
        if (
            profile.query_type == "multi_hop"
            and current_type == "subgraph"
            and profile.relationship_intensity
            >= self.settings.multi_hop_hint_relationship_threshold
        ):
            return "multi_hop"
        if current_type in _VALID_GRAPH_QUERY_TYPES:
            return current_type
        return profile.query_type if profile.query_type in _VALID_GRAPH_QUERY_TYPES else "subgraph"

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
        if resolved_strategy != plan.strategy:
            plan.validation_errors.append(
                f"calibrated_strategy:{plan.strategy}->{resolved_strategy}"
            )
            plan.strategy = resolved_strategy

        resolved_query_type = self.resolve_graph_query_type(plan.graph_query_type, profile)
        if resolved_query_type != plan.graph_query_type:
            plan.validation_errors.append(
                f"calibrated_graph_query_type:{plan.graph_query_type}->{resolved_query_type}"
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

        if plan.strategy in {"graph_rag", "combined"} and not plan.source_entities:
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
                plan.validation_errors.append("calibrated_source_entities")

        plan.max_depth = max(
            1,
            min(
                int(
                    plan.max_depth
                    or infer_graph_max_depth(
                        plan.graph_query_type,
                        plan.relationship_intensity,
                        settings=self.settings,
                    )
                ),
                self.settings.graph_query_max_depth_cap,
            ),
        )


__all__ = ["QueryPlanCalibrator"]
