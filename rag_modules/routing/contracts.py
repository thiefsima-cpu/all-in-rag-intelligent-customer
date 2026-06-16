"""Canonical routing workflow contracts."""

from __future__ import annotations

from typing import Any, Protocol

from ..runtime import QueryAnalysis, QueryUnderstandingSnapshot, RouteResolution, RouteSnapshot


class RoutingWorkflowProtocol(Protocol):
    """Stable routing workflow surface consumed by the application layer."""

    graph_rag_retrieval: Any

    def analyze_query(self, query: str) -> QueryAnalysis: ...

    def understand_query(self, query: str) -> QueryUnderstandingSnapshot: ...

    def explain_routing_decision(self, query: str) -> str: ...

    def route(self, query: str, top_k: int = 5) -> RouteResolution: ...

    def route_with_trace(
        self,
        query: str,
        top_k: int = 5,
    ) -> tuple[RouteResolution, RouteSnapshot]: ...

    def get_route_statistics(self) -> dict[str, Any]: ...


__all__ = ["RoutingWorkflowProtocol"]
