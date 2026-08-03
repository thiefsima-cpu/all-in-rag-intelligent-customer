"""Rule-based query planning fallback."""

from __future__ import annotations

from ...contracts import (
    QueryPlan,
    QueryPlannerMode,
    QuerySemanticProfile,
    QuerySemanticRuntimeSettings,
)
from ...contracts.query_constraints import QueryConstraints
from ...domains.contracts import DomainQueryConstraintSchema
from ...kernel.routing import SearchStrategy
from ...query_policy.models import QueryPolicyBundle
from ..features import fallback_keywords, normalize_graph_sources
from ..graph_intent import infer_graph_max_depth, infer_query_semantic_profile
from ..scoring import estimate_query_complexity, estimate_relationship_intensity
from .calibration import QueryPlanCalibrator


class RuleBasedPlanner:
    def __init__(
        self,
        settings: QuerySemanticRuntimeSettings,
        calibrator: QueryPlanCalibrator,
        policy_bundle: QueryPolicyBundle | None = None,
        constraint_schema: DomainQueryConstraintSchema | None = None,
    ) -> None:
        self.settings = settings
        self.calibrator = calibrator
        self.policy_bundle = policy_bundle
        self.constraint_schema = constraint_schema

    def _resolve_source_entities(
        self,
        *,
        query: str,
        profile: QuerySemanticProfile,
        strategy: str,
        relationship_intensity: float,
    ) -> list[str]:
        source_candidates = (
            profile.source_entities
            if relationship_intensity >= self.settings.source_entity_seed_relationship_threshold
            else []
        )
        if not source_candidates and (
            strategy != SearchStrategy.HYBRID_TRADITIONAL.value
            or relationship_intensity >= self.settings.source_entity_backfill_relationship_threshold
        ):
            source_candidates = (
                profile.source_entities or profile.entity_keywords or fallback_keywords(query)
            )
        source_entities = normalize_graph_sources(
            source_candidates[: self.settings.source_entity_limit]
        )
        if (
            strategy == SearchStrategy.HYBRID_TRADITIONAL.value
            and relationship_intensity < self.settings.source_entity_seed_relationship_threshold
        ):
            return []
        return source_entities

    def plan(self, query: str) -> QueryPlan:
        profile = infer_query_semantic_profile(
            query,
            settings=self.settings,
            policy_bundle=self.policy_bundle,
            constraint_schema=self.constraint_schema,
        )
        constraints = QueryConstraints.from_dict(profile.constraints)
        complexity = max(
            profile.complexity,
            estimate_query_complexity(
                query,
                settings=self.settings,
                policy_bundle=self.policy_bundle,
            ),
        )
        relationship_intensity = max(
            profile.relationship_intensity,
            estimate_relationship_intensity(
                query,
                settings=self.settings,
                policy_bundle=self.policy_bundle,
            ),
        )

        strategy = self.calibrator.resolve_strategy(
            current_strategy=SearchStrategy.HYBRID_TRADITIONAL.value,
            profile=profile,
            constraints=constraints,
            complexity=complexity,
            relationship_intensity=relationship_intensity,
        )

        source_entities = self._resolve_source_entities(
            query=query,
            profile=profile,
            strategy=strategy,
            relationship_intensity=relationship_intensity,
        )

        return QueryPlan(
            query=query,
            intent="recommendation" if profile.recommendation_required else "qa",
            complexity=complexity,
            relationship_intensity=relationship_intensity,
            reasoning_required=(
                profile.reasoning_required
                or relationship_intensity >= self.settings.source_entity_seed_relationship_threshold
            ),
            strategy=SearchStrategy(strategy),
            confidence=self.settings.rule_fallback_confidence,
            reasoning="LLM planning unavailable; used shared lexical fallback.",
            entity_keywords=profile.entity_keywords[: self.settings.entity_keyword_limit],
            topic_keywords=profile.topic_keywords[: self.settings.topic_keyword_limit],
            graph_query_type=profile.query_type,
            source_entities=source_entities[: self.settings.source_entity_limit],
            target_entities=profile.target_entities[: self.settings.target_entity_limit],
            relation_types=profile.relation_types,
            max_depth=infer_graph_max_depth(
                profile.query_type_value,
                relationship_intensity,
                settings=self.settings,
                policy_bundle=self.policy_bundle,
            ),
            constraints=constraints,
            recommendation_required=profile.recommendation_required,
            fallback_reason="rule_based",
            planner_mode=QueryPlannerMode.RULE_BASED,
            semantic_profile=profile,
        )


__all__ = ["RuleBasedPlanner"]
