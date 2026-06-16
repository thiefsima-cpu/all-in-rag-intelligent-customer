"""Canonical query-understanding service."""

from __future__ import annotations

from ..retrieval.runtime_profile import RetrievalRuntimeProfile
from ..runtime import QueryAnalysis, QueryUnderstandingSnapshot
from .planner_service import QueryPlanner

QueryUnderstandingResult = QueryUnderstandingSnapshot


class QueryUnderstandingService:
    """Own the query-planning and query-analysis policy for retrieval routing."""

    def __init__(self, *, llm_client, config, retrieval_profile: RetrievalRuntimeProfile | None = None):
        self.config = config
        self.llm_client = llm_client
        self.retrieval_profile = retrieval_profile or RetrievalRuntimeProfile.from_config(config)
        self.query_planner = QueryPlanner(
            llm_client,
            settings=self.retrieval_profile.planner,
            semantic_settings=self.retrieval_profile.semantics,
        )

    def understand(self, query: str) -> QueryUnderstandingResult:
        return QueryUnderstandingResult.from_plan(self.query_planner.plan(query))

    def analyze(self, query: str) -> QueryAnalysis:
        return self.understand(query).analysis

    def explain(self, query: str) -> str:
        return self.explain_result(self.understand(query))

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
            f"Graph query type: {plan.graph_query_type}\n"
            f"Source entities: {source_entities}\n"
            f"Target entities: {target_entities}\n"
            f"Relation hits: {relation_hits}\n"
            f"Constraint hits: {constraint_hits}\n"
            f"Structural hits: {structural_hits}\n"
            f"Planner mode: {plan.planner_mode}\n"
            f"Reason: {analysis.reasoning or 'n/a'}"
        )


__all__ = ["QueryUnderstandingResult", "QueryUnderstandingService"]
