from __future__ import annotations

import unittest
from dataclasses import replace
from types import SimpleNamespace

from rag_modules.contracts import (
    EvidenceDocument,
    QueryPlan,
    QuerySemanticRuntimeSettings,
    RequestControl,
)
from rag_modules.contracts.query_constraints import QueryConstraints
from rag_modules.contracts.runtime import QueryAnalysis
from rag_modules.contracts.runtime.retrieval import HybridRetrievalOutcome
from rag_modules.kernel.routing import SearchStrategy
from rag_modules.retrieval.candidate_generator import SKIP_CANDIDATE_SOURCES_METADATA_KEY
from rag_modules.retrieval.post_processor import RetrievalPostProcessResult
from rag_modules.routing import (
    RouteExecutionRequest,
    RouteSearchOrchestrator,
    RouteTraceRecorder,
)
from rag_modules.routing.execution_strategies import (
    RouteExecutionOutcome,
    RouteExecutionStageResult,
)
from tests.configuration_test_helpers import build_test_config


class _FakeTraditionalRetrieval:
    def __init__(self, hybrid_docs=None) -> None:
        self.hybrid_docs = list(hybrid_docs or [])
        self.hybrid_requests = []

    def hybrid_evidence_search(self, request):
        self.hybrid_requests.append(request)
        return HybridRetrievalOutcome(
            documents=list(self.hybrid_docs),
            candidate_counts={"vector": len(self.hybrid_docs)},
        )

    def enrich_to_parent_evidence_documents(self, request, docs, top_n=None):
        del request, top_n
        return list(docs)


class _FakeGraphRetrieval:
    def graph_rag_evidence_search_with_trace(self, request):
        del request
        return [], {}


class _FakePostProcessor:
    def __init__(
        self,
        *,
        rerank_attempted: bool = False,
        rerank_succeeded: bool = False,
        rerank_latency_ms: float | None = None,
    ) -> None:
        self.contexts = []
        self.rerank_attempted = rerank_attempted
        self.rerank_succeeded = rerank_succeeded
        self.rerank_latency_ms = rerank_latency_ms

    def post_process_with_trace(self, evidence_documents, top_k, context):
        self.contexts.append(context)
        return RetrievalPostProcessResult(
            documents=tuple(list(evidence_documents)[:top_k]),
            rerank_attempted=self.rerank_attempted,
            rerank_succeeded=self.rerank_succeeded,
            rerank_latency_ms=self.rerank_latency_ms,
        )


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


class _ClosableStrategy(_StubStrategy):
    def __init__(self) -> None:
        super().__init__()
        self.closed = False

    def close(self) -> None:
        self.closed = True


class RouteSearchOrchestratorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.semantic_settings = QuerySemanticRuntimeSettings.from_config(build_test_config())

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
        trace = RouteTraceRecorder(
            query=request.query,
            requested_top_k=request.top_k,
            semantic_settings=self.semantic_settings,
        )

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
        trace = RouteTraceRecorder(
            query=request.query,
            requested_top_k=request.top_k,
            semantic_settings=self.semantic_settings,
        )

        docs = orchestrator.execute_exception_fallback(
            request,
            trace=trace,
            error=RuntimeError("boom"),
        )

        self.assertEqual([doc.recipe_name for doc in docs], ["Mapo Tofu"])
        self.assertEqual(trace.snapshot.fallbacks, ["router_exception_to_hybrid"])
        self.assertIn("hybrid_exception_fallback", trace.snapshot.stages)

    def test_execute_exception_fallback_skips_already_degraded_candidate_sources(self) -> None:
        traditional = _FakeTraditionalRetrieval(
            [EvidenceDocument(content="fallback", recipe_name="Mapo Tofu")]
        )
        orchestrator = RouteSearchOrchestrator(
            traditional_retrieval=traditional,
            graph_rag_retrieval=_FakeGraphRetrieval(),
            retrieval_profile=SimpleNamespace(candidates=SimpleNamespace()),
            post_processor=_FakePostProcessor(),
        )
        plan = QueryPlan(query="recommend tofu dishes")
        retrieval_request = RouteSearchOrchestrator.build_retrieval_request(
            query="recommend tofu dishes",
            top_k=2,
            strategy="combined",
            query_plan=plan,
        )
        retrieval_request = replace(
            retrieval_request,
            metadata={SKIP_CANDIDATE_SOURCES_METADATA_KEY: ["bm25"]},
        )
        request = RouteExecutionRequest(
            query="recommend tofu dishes",
            top_k=2,
            analysis=QueryAnalysis(recommended_strategy=SearchStrategy.COMBINED),
            retrieval_request=retrieval_request,
            constraints=QueryConstraints(),
            query_plan=plan,
        )
        trace = RouteTraceRecorder(
            query=request.query,
            requested_top_k=request.top_k,
            semantic_settings=self.semantic_settings,
        )
        trace.record_execution_outcome(
            RouteExecutionOutcome(
                stages=[
                    RouteExecutionStageResult(
                        name="combined",
                        documents=[],
                        details={
                            "degraded_candidates": [
                                {
                                    "source": "vector",
                                    "error": {
                                        "code": "CANDIDATE_SOURCE_CIRCUIT_OPEN",
                                        "detail": "candidate_source_circuit_open",
                                    },
                                },
                                {
                                    "source": "bm25",
                                    "error": {
                                        "code": "CANDIDATE_SOURCE_REQUEST_SKIPPED",
                                        "detail": "candidate_source_request_skipped",
                                    },
                                },
                            ],
                        },
                    )
                ],
            )
        )

        orchestrator.execute_exception_fallback(
            request,
            trace=trace,
            error=RuntimeError("boom"),
        )

        fallback_request = traditional.hybrid_requests[0]
        self.assertEqual(
            fallback_request.metadata[SKIP_CANDIDATE_SOURCES_METADATA_KEY],
            ["bm25", "vector"],
        )
        self.assertEqual(
            request.retrieval_request.metadata[SKIP_CANDIDATE_SOURCES_METADATA_KEY],
            ["bm25"],
        )

    def test_close_closes_owned_route_strategies(self) -> None:
        strategy = _ClosableStrategy()
        orchestrator = RouteSearchOrchestrator(
            traditional_retrieval=_FakeTraditionalRetrieval(),
            graph_rag_retrieval=_FakeGraphRetrieval(),
            retrieval_profile=SimpleNamespace(candidates=SimpleNamespace()),
            post_processor=_FakePostProcessor(),
            strategies=[strategy],
        )

        orchestrator.close()

        self.assertTrue(strategy.closed)

    def test_post_process_receives_request_control(self) -> None:
        control = RequestControl.for_timeout(5.0, scope="route")
        post_processor = _FakePostProcessor()
        orchestrator = RouteSearchOrchestrator(
            traditional_retrieval=_FakeTraditionalRetrieval(),
            graph_rag_retrieval=_FakeGraphRetrieval(),
            retrieval_profile=SimpleNamespace(candidates=SimpleNamespace()),
            post_processor=post_processor,
            strategies=[_StubStrategy()],
        )
        plan = QueryPlan(query="recommend tofu dishes")
        request = RouteExecutionRequest(
            query="recommend tofu dishes",
            top_k=2,
            analysis=QueryAnalysis(recommended_strategy=SearchStrategy.HYBRID_TRADITIONAL),
            retrieval_request=RouteSearchOrchestrator.build_retrieval_request(
                query="recommend tofu dishes",
                top_k=2,
                strategy="hybrid_traditional",
                query_plan=plan,
                control=control,
            ),
            constraints=QueryConstraints(),
            query_plan=plan,
        )

        orchestrator.post_process(
            request,
            [EvidenceDocument(content="hybrid", recipe_name="Mapo Tofu")],
            trace=RouteTraceRecorder(
                query=request.query,
                requested_top_k=request.top_k,
                semantic_settings=self.semantic_settings,
            ),
        )

        self.assertIs(post_processor.contexts[0].control, control)

    def test_post_process_records_failed_rerank_as_retrieval_degradation(self) -> None:
        post_processor = _FakePostProcessor(
            rerank_attempted=True,
            rerank_succeeded=False,
            rerank_latency_ms=75.0,
        )
        orchestrator = RouteSearchOrchestrator(
            traditional_retrieval=_FakeTraditionalRetrieval(),
            graph_rag_retrieval=_FakeGraphRetrieval(),
            retrieval_profile=SimpleNamespace(candidates=SimpleNamespace()),
            post_processor=post_processor,
        )
        request = RouteExecutionRequest(
            query="recommend tofu dishes",
            top_k=2,
            analysis=QueryAnalysis(recommended_strategy=SearchStrategy.HYBRID_TRADITIONAL),
            retrieval_request=RouteSearchOrchestrator.build_retrieval_request(
                query="recommend tofu dishes",
                top_k=2,
                strategy="hybrid_traditional",
            ),
            constraints=QueryConstraints(),
        )
        trace = RouteTraceRecorder(
            query=request.query,
            requested_top_k=request.top_k,
            semantic_settings=self.semantic_settings,
        )

        orchestrator.post_process(
            request,
            [EvidenceDocument(content="hybrid", recipe_name="Mapo Tofu")],
            trace=trace,
        )

        stage = trace.snapshot.stages["post_process"]
        self.assertEqual(stage.details["rerank_latency_ms"], 75.0)
        self.assertTrue(stage.details["rerank_attempted"])
        self.assertFalse(stage.details["rerank_succeeded"])
        self.assertTrue(stage.details["retrieval_degraded"])
        self.assertEqual(stage.details["degraded_sources"], ["rerank"])
        self.assertTrue(trace.snapshot.diagnostics.retrieval_degraded)


if __name__ == "__main__":
    unittest.main()
