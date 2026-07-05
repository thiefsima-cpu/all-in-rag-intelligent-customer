"""Canonical query-understanding service."""

from __future__ import annotations

from ..contracts import QueryPlannerRuntimeSettings, QuerySemanticRuntimeSettings, RequestControl
from ..contracts.runtime import QueryAnalysis, QueryUnderstandingSnapshot
from ..query_policy.models import QueryPolicyBundle
from ..runtime_contracts import LLMClientPort
from .planning import QueryPlanner

QueryUnderstandingResult = QueryUnderstandingSnapshot


class QueryUnderstandingService:
    """Own the query-planning and query-analysis policy for retrieval routing."""

    def __init__(
        self,
        *,
        llm_client: LLMClientPort | None,
        config,
        planner_settings: QueryPlannerRuntimeSettings,
        semantic_settings: QuerySemanticRuntimeSettings,
        policy_bundle: QueryPolicyBundle | None = None,
    ) -> None:
        self.config = config
        self.llm_client = llm_client
        self.planner_settings = planner_settings
        self.semantic_settings = semantic_settings
        self.query_planner = QueryPlanner(
            llm_client,
            settings=self.planner_settings,
            semantic_settings=self.semantic_settings,
            policy_bundle=policy_bundle,
        )

    def understand(
        self,
        query: str,
        *,
        control: RequestControl | None = None,
    ) -> QueryUnderstandingResult:
        return QueryUnderstandingResult.from_plan(self.query_planner.plan(query, control=control))

    def analyze(self, query: str, *, control: RequestControl | None = None) -> QueryAnalysis:
        return self.understand(query, control=control).analysis

    def explain(self, query: str, *, control: RequestControl | None = None) -> str:
        return self.explain_result(self.understand(query, control=control))

    @staticmethod
    def explain_result(result: QueryUnderstandingResult) -> str:
        plan = result.query_plan
        analysis = result.analysis
        profile = result.semantic_profile
        relation_hits = ", ".join(profile.relation_hits[:4]) or "none"
        constraint_hits = ", ".join(profile.constraint_hits[:4]) or "none"
        structural_hits = ", ".join(profile.structural_hits[:4]) or "none"
        source_entities = ", ".join(plan.source_entities[:4]) or "none"
        target_entities = ", ".join(plan.target_entities[:4]) or "none"
        return (
            "[ROUTE]\n"
            f"Strategy: {analysis.strategy_name}\n"
            f"Complexity: {analysis.query_complexity:.2f}\n"
            f"Relationship intensity: {analysis.relationship_intensity:.2f}\n"
            f"Reasoning required: {'yes' if analysis.reasoning_required else 'no'}\n"
            f"Graph query type: {plan.graph_query_type_value}\n"
            f"Source entities: {source_entities}\n"
            f"Target entities: {target_entities}\n"
            f"Relation hits: {relation_hits}\n"
            f"Constraint hits: {constraint_hits}\n"
            f"Structural hits: {structural_hits}\n"
            f"Planner mode: {plan.planner_mode_value}\n"
            f"Reason: {analysis.reasoning or 'n/a'}"
        )


__all__ = ["QueryUnderstandingResult", "QueryUnderstandingService"]
