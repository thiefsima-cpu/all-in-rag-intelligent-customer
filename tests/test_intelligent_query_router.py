from __future__ import annotations

import unittest

from rag_modules.intelligent_query_router import (
    IntelligentQueryRouter as LegacyIntelligentQueryRouter,
)
from rag_modules.routing import IntelligentQueryRouter
from rag_modules.runtime import QueryAnalysis, RetrievalOutcome, RouteResolution, RouteSnapshot


class _StubWorkflow:
    def __init__(self) -> None:
        self.route_calls: list[tuple[str, int]] = []
        self.resolution = RouteResolution(
            retrieval=RetrievalOutcome(
                query="stub-query",
                strategy="combined",
            )
        )

    def analyze_query(self, query: str) -> QueryAnalysis:
        return QueryAnalysis(reasoning=f"analysis:{query}")

    def understand_query(self, query: str):
        return self.resolution.understanding

    def explain_routing_decision(self, query: str) -> str:
        return f"explain:{query}"

    def route(self, query: str, top_k: int = 5) -> RouteResolution:
        self.route_calls.append((query, top_k))
        return self.resolution

    def route_with_trace(self, query: str, top_k: int = 5):
        self.route_calls.append((query, top_k))
        return self.resolution, RouteSnapshot(query=query, strategy="combined")


class IntelligentQueryRouterTests(unittest.TestCase):
    def test_legacy_facade_reexports_canonical_router(self) -> None:
        self.assertIs(LegacyIntelligentQueryRouter, IntelligentQueryRouter)

    def test_facade_delegates_to_workflow_service(self) -> None:
        workflow = _StubWorkflow()
        router = IntelligentQueryRouter(
            traditional_retrieval=None,
            graph_rag_retrieval=None,
            llm_client=None,
            config=None,
            workflow=workflow,
        )

        analysis = router.analyze_query("why")
        explanation = router.explain_routing_decision("why")
        resolution = router.route("why", 7)
        retrieval, routed_analysis = router.route_query("next", 3)

        self.assertEqual(analysis.reasoning, "analysis:why")
        self.assertEqual(explanation, "explain:why")
        self.assertIs(resolution, workflow.resolution)
        self.assertIs(retrieval, workflow.resolution.retrieval)
        self.assertEqual(routed_analysis.strategy_name, workflow.resolution.analysis.strategy_name)
        self.assertEqual(workflow.route_calls, [("why", 7), ("next", 3)])
        traced_resolution, trace = router.route_with_trace("traced", 4)
        self.assertIs(traced_resolution, workflow.resolution)
        self.assertEqual(trace.query, "traced")
        self.assertEqual(workflow.route_calls[-1], ("traced", 4))
        self.assertFalse(hasattr(router, "last_trace"))
        self.assertFalse(hasattr(router, "last_resolution"))


if __name__ == "__main__":
    unittest.main()
