"""Compatibility adapter for the canonical routing workflow service."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..query_understanding.service import QueryUnderstandingService
    from ..retrieval.runtime_profile import RetrievalRuntimeProfile
    from ..runtime import (
        QueryAnalysis,
        QueryUnderstandingSnapshot,
        RetrievalOutcome,
        RouteResolution,
    )
    from .workflow_service import RoutingWorkflowService

INTELLIGENT_QUERY_ROUTER_REMOVAL_VERSION = "0.3.0"


class IntelligentQueryRouter:
    """Legacy router-shaped adapter over RoutingWorkflowService.

    Canonical replacement: RoutingWorkflowService.
    Deprecated compatibility adapter. Prefer RoutingWorkflowService for new code.
    Scheduled for removal in package version 0.3.0.
    """

    def __init__(
        self,
        traditional_retrieval,
        graph_rag_retrieval,
        llm_client,
        config,
        retrieval_profile: "RetrievalRuntimeProfile | None" = None,
        query_understanding_service: "QueryUnderstandingService | None" = None,
        workflow: "RoutingWorkflowService | None" = None,
    ) -> None:
        if workflow is None:
            from .workflow_service import RoutingWorkflowService

            workflow = RoutingWorkflowService(
                traditional_retrieval=traditional_retrieval,
                graph_rag_retrieval=graph_rag_retrieval,
                llm_client=llm_client,
                config=config,
                retrieval_profile=retrieval_profile,
                query_understanding_service=query_understanding_service,
            )
        self.workflow = workflow

    def analyze_query(self, query: str) -> "QueryAnalysis":
        return self.workflow.analyze_query(query)

    def understand_query(self, query: str) -> "QueryUnderstandingSnapshot":
        return self.workflow.understand_query(query)

    def explain_routing_decision(self, query: str) -> str:
        return self.workflow.explain_routing_decision(query)

    def route(self, query: str, top_k: int = 5) -> "RouteResolution":
        return self.workflow.route(query, top_k)

    def route_with_trace(self, query: str, top_k: int = 5):
        return self.workflow.route_with_trace(query, top_k)

    def route_query(self, query: str, top_k: int = 5) -> tuple["RetrievalOutcome", "QueryAnalysis"]:
        resolution = self.route(query, top_k)
        return resolution.retrieval, resolution.analysis


__all__ = ["INTELLIGENT_QUERY_ROUTER_REMOVAL_VERSION", "IntelligentQueryRouter"]
