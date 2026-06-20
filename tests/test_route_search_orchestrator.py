from __future__ import annotations

import unittest
from types import SimpleNamespace

from rag_modules.query_constraints import QueryConstraints
from rag_modules.query_understanding import QueryPlan
from rag_modules.retrieval.contracts import EvidenceDocument
from rag_modules.retrieval.hybrid_outcome import HybridRetrievalOutcome
from rag_modules.routing import (
    RouteExecutionRequest,
    RouteSearchOrchestrator,
    RouteTraceRecorder,
)
from rag_modules.routing.execution_strategies import (
    RouteExecutionOutcome,
    RouteExecutionStageResult,
)
from rag_modules.runtime import QueryAnalysis, SearchStrategy


class _FakeTraditionalRetrieval:
    def __init__(self, hybrid_docs=None) -> None:
        self.hybrid_docs = list(hybrid_docs or [])

    def hybrid_evidence_search(self, request):
        del request
        return HybridRetrievalOutcome(
            documents=list(self.hybrid_docs),
            candidate_counts={"vector": len(self.hybrid_docs)},
        )

    def enrich_to_parent_evidence_documents(self, docs, top_n=None):
        del top_n
        return list(docs)


class _FakeGraphRetrieval:
    def graph_rag_evidence_search(self, query, top_k, constraints=None, query_plan=None):
        del query, top_k, constraints, query_plan
        return []


class _FakePostProcessor:
    def post_process(self, evidence_documents, top_k, context):
        del context
        return list(evidence_documents)[:top_k]


class _StubStrategy:
    strategy = SearchStrategy.GRAPH_RAG

    def __init__(self) -> None:
        self.calls = []

    def execute(self, request, *, services):
        self.calls.append({"request": request, "services": services})
        return RouteExecutionOutcome(
            documents=[EvidenceDocument(content="graph", recipe_name="Fish-Fragrant Pork")],
            fallbacks=["graph_empty_to_hybrid"],
            stages=[
                RouteExecutionStageResult(
                    name="graph_rag",
                    documents=[EvidenceDocument(content="graph", recipe_name="Fish-Fragrant Pork")],
                    latency_ms=12.5,
                    details={"path_count": 2},
                )
            ],
        )


class RouteSearchOrchestratorTests(unittest.TestCase):
    def test_execute_delegates_to_strategy_registry_and_records_trace(self) -> None:
        strategy = _StubStrategy()
        orchestrator = RouteSearchOrchestrator(
            traditional_retrieval=_FakeTraditionalRetrieval(),
            graph_rag_retrieval=_FakeGraphRetrieval(),
            retrieval_profile=SimpleNamespace(candidates=SimpleNamespace()),
            post_processor=_FakePostProcessor(),
            strategies=[strategy],
        )
        plan = QueryPlan(query="why is fish-fragrant pork layered")
        request = RouteExecutionRequest(
            query="why is fish-fragrant pork layered",
            top_k=2,
            analysis=QueryAnalysis(recommended_strategy=SearchStrategy.GRAPH_RAG),
            retrieval_request=RouteSearchOrchestrator.build_retrieval_request(
                query="why is fish-fragrant pork layered",
                top_k=2,
                strategy="graph_rag",
                query_plan=plan,
            ),
            constraints=QueryConstraints(),
            query_plan=plan,
        )
        trace = RouteTraceRecorder(query=request.query, requested_top_k=request.top_k)

        docs = orchestrator.execute(request, trace=trace)

        self.assertEqual([doc.recipe_name for doc in docs], ["Fish-Fragrant Pork"])
        self.assertEqual(len(strategy.calls), 1)
        self.assertEqual(trace.snapshot.fallbacks, ["graph_empty_to_hybrid"])
        self.assertIn("graph_rag", trace.snapshot.stages)
        self.assertEqual(trace.snapshot.stages["graph_rag"].details["path_count"], 2)

    def test_execute_exception_fallback_records_hybrid_stage(self) -> None:
        orchestrator = RouteSearchOrchestrator(
            traditional_retrieval=_FakeTraditionalRetrieval(
                [EvidenceDocument(content="fallback", recipe_name="Mapo Tofu")]
            ),
            graph_rag_retrieval=_FakeGraphRetrieval(),
            retrieval_profile=SimpleNamespace(candidates=SimpleNamespace()),
            post_processor=_FakePostProcessor(),
        )
        plan = QueryPlan(query="recommend tofu dishes")
        request = RouteExecutionRequest(
            query="recommend tofu dishes",
            top_k=2,
            analysis=QueryAnalysis(recommended_strategy=SearchStrategy.COMBINED),
            retrieval_request=RouteSearchOrchestrator.build_retrieval_request(
                query="recommend tofu dishes",
                top_k=2,
                strategy="combined",
                query_plan=plan,
            ),
            constraints=QueryConstraints(),
            query_plan=plan,
        )
        trace = RouteTraceRecorder(query=request.query, requested_top_k=request.top_k)

        docs = orchestrator.execute_exception_fallback(
            request,
            trace=trace,
            error=RuntimeError("boom"),
        )

        self.assertEqual([doc.recipe_name for doc in docs], ["Mapo Tofu"])
        self.assertEqual(trace.snapshot.fallbacks, ["router_exception_to_hybrid"])
        self.assertIn("hybrid_exception_fallback", trace.snapshot.stages)


if __name__ == "__main__":
    unittest.main()
