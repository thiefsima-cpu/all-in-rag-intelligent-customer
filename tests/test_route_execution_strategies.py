from __future__ import annotations

import threading
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from rag_modules.contracts import EvidenceDocument, QueryPlan, RetrievalRequest
from rag_modules.domain.shared.query_constraints import QueryConstraints
from rag_modules.retrieval.hybrid_outcome import HybridRetrievalOutcome
from rag_modules.routing.execution_strategies import (
    CombinedRouteStrategy,
    GraphRouteStrategy,
    HybridRouteStrategy,
    RouteRetrievalServices,
    build_route_retrieval_request,
)
from rag_modules.runtime import QueryAnalysis, SearchStrategy


class _FakeTraditionalRetrieval:
    def __init__(self, hybrid_docs=None) -> None:
        self.hybrid_docs = list(hybrid_docs or [])
        self.hybrid_calls = []
        self.enrich_calls = []

    def hybrid_evidence_search(self, request):
        self.hybrid_calls.append(request)
        return HybridRetrievalOutcome(
            documents=list(self.hybrid_docs),
            candidate_counts={"vector": len(self.hybrid_docs)},
        )

    def enrich_to_parent_evidence_documents(self, docs, top_n=None):
        self.enrich_calls.append({"docs": list(docs), "top_n": top_n})
        return list(docs)


class _FakeGraphRetrieval:
    def __init__(self, graph_docs=None, *, trace=None) -> None:
        self.graph_docs = list(graph_docs or [])
        self.trace = trace or {"query_type": "multi_hop", "path_count": len(self.graph_docs)}
        self.last_trace = {"query_type": "stale", "path_count": 0}
        self.calls = []

    def graph_rag_evidence_search(self, query, top_k, constraints=None, query_plan=None):
        self.calls.append(
            {
                "query": query,
                "top_k": top_k,
                "constraints": constraints,
                "query_plan": query_plan,
            }
        )
        return list(self.graph_docs)

    def graph_rag_evidence_search_with_trace(
        self,
        query,
        top_k,
        constraints=None,
        query_plan=None,
    ):
        return (
            self.graph_rag_evidence_search(
                query,
                top_k,
                constraints=constraints,
                query_plan=query_plan,
            ),
            self.trace,
        )


class _FakeCandidates:
    def graph_supplement_candidate_k(self, top_k: int) -> int:
        return top_k + 1

    def combined_candidate_k(self, top_k: int) -> int:
        return top_k + 2


class _FakeRetrievalProfile:
    def __init__(self) -> None:
        self.candidates = _FakeCandidates()


class _ImmediateFuture:
    def __init__(self, result) -> None:
        self._result = result

    def result(self):
        return self._result


class _SynchronousExecutor:
    def __init__(self, *args, **kwargs) -> None:
        self.args = args
        self.kwargs = kwargs
        self.submit_calls = []
        self.shutdown_calls = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback) -> bool:
        self.shutdown(wait=True)
        return False

    def submit(self, fn, *args, **kwargs):
        self.submit_calls.append({"fn": fn, "args": args, "kwargs": kwargs})
        return _ImmediateFuture(fn(*args, **kwargs))

    def shutdown(self, wait=True, *, cancel_futures=False) -> None:
        self.shutdown_calls.append({"wait": wait, "cancel_futures": cancel_futures})


class _ParallelTraditionalRetrieval(_FakeTraditionalRetrieval):
    def __init__(self, hybrid_docs=None, *, own_started, other_started) -> None:
        super().__init__(hybrid_docs)
        self.own_started = own_started
        self.other_started = other_started
        self.observed_parallel_start = False

    def hybrid_evidence_search(self, request):
        self.own_started.set()
        self.observed_parallel_start = self.other_started.wait(timeout=0.2)
        return super().hybrid_evidence_search(request)


class _DegradedTraditionalRetrieval(_FakeTraditionalRetrieval):
    def hybrid_evidence_search(self, request):
        self.hybrid_calls.append(request)
        return HybridRetrievalOutcome(
            documents=list(self.hybrid_docs),
            candidate_counts={"vector": len(self.hybrid_docs), "bm25": 0},
            degraded_candidates=[
                {
                    "source": "bm25",
                    "rank_name": "bm25",
                    "reason": "circuit_open",
                    "error_type": "CircuitOpenError",
                    "message": "Circuit breaker open",
                    "circuit_state": "open",
                    "failure_count": 3,
                }
            ],
        )


class _ParallelGraphRetrieval(_FakeGraphRetrieval):
    def __init__(self, graph_docs=None, *, own_started, other_started, trace=None) -> None:
        super().__init__(graph_docs, trace=trace)
        self.own_started = own_started
        self.other_started = other_started
        self.observed_parallel_start = False

    def graph_rag_evidence_search(self, query, top_k, constraints=None, query_plan=None):
        self.own_started.set()
        self.observed_parallel_start = self.other_started.wait(timeout=0.2)
        return super().graph_rag_evidence_search(
            query,
            top_k,
            constraints=constraints,
            query_plan=query_plan,
        )


def _request(*, query: str, top_k: int, strategy: SearchStrategy) -> SimpleNamespace:
    plan = QueryPlan(query=query)
    return SimpleNamespace(
        query=query,
        top_k=top_k,
        analysis=QueryAnalysis(recommended_strategy=strategy),
        retrieval_request=RetrievalRequest.from_inputs(
            query=query,
            top_k=top_k,
            strategy=strategy.value,
            query_plan=plan,
        ),
        constraints=QueryConstraints(),
        query_plan=plan,
    )


class RouteExecutionStrategiesTests(unittest.TestCase):
    def test_hybrid_strategy_returns_hybrid_stage(self) -> None:
        services = RouteRetrievalServices(
            traditional_retrieval=_FakeTraditionalRetrieval(
                [EvidenceDocument(content="hybrid", recipe_name="Mapo Tofu")]
            ),
            graph_rag_retrieval=_FakeGraphRetrieval(),
            retrieval_profile=_FakeRetrievalProfile(),
        )

        outcome = HybridRouteStrategy().execute(
            _request(
                query="recommend tofu dishes",
                top_k=2,
                strategy=SearchStrategy.HYBRID_TRADITIONAL,
            ),
            services=services,
        )

        self.assertEqual([doc.recipe_name for doc in outcome.documents], ["Mapo Tofu"])
        self.assertEqual(outcome.stages[0].name, "hybrid")
        self.assertEqual(outcome.fallbacks, [])

    def test_hybrid_strategy_records_degradation_details_on_stage(self) -> None:
        services = RouteRetrievalServices(
            traditional_retrieval=_DegradedTraditionalRetrieval(
                [EvidenceDocument(content="hybrid", recipe_name="Mapo Tofu")]
            ),
            graph_rag_retrieval=_FakeGraphRetrieval(),
            retrieval_profile=_FakeRetrievalProfile(),
        )

        outcome = HybridRouteStrategy().execute(
            _request(
                query="recommend tofu dishes",
                top_k=2,
                strategy=SearchStrategy.HYBRID_TRADITIONAL,
            ),
            services=services,
        )

        self.assertEqual([doc.recipe_name for doc in outcome.documents], ["Mapo Tofu"])
        self.assertTrue(outcome.stages[0].details["retrieval_degraded"])
        self.assertEqual(outcome.stages[0].details["degraded_sources"], ["bm25"])
        self.assertTrue(outcome.stages[0].details["circuit_breaker_triggered"])
        self.assertFalse(outcome.stages[0].details["answer_impacted"])

    def test_graph_strategy_falls_back_to_hybrid_when_graph_is_empty(self) -> None:
        services = RouteRetrievalServices(
            traditional_retrieval=_FakeTraditionalRetrieval(
                [EvidenceDocument(content="fallback", recipe_name="Shui Zhu Pork")]
            ),
            graph_rag_retrieval=_FakeGraphRetrieval([]),
            retrieval_profile=_FakeRetrievalProfile(),
        )

        outcome = GraphRouteStrategy().execute(
            _request(
                query="why does shui zhu pork feel layered",
                top_k=2,
                strategy=SearchStrategy.GRAPH_RAG,
            ),
            services=services,
        )

        self.assertEqual([doc.recipe_name for doc in outcome.documents], ["Shui Zhu Pork"])
        self.assertEqual(outcome.fallbacks, ["graph_empty_to_hybrid"])
        self.assertEqual([stage.name for stage in outcome.stages], ["graph_rag", "hybrid_fallback"])

    def test_combined_strategy_interleaves_graph_and_traditional(self) -> None:
        services = RouteRetrievalServices(
            traditional_retrieval=_FakeTraditionalRetrieval(
                [
                    EvidenceDocument(content="traditional-1", recipe_name="A", node_id="1"),
                    EvidenceDocument(content="traditional-2", recipe_name="B", node_id="2"),
                ]
            ),
            graph_rag_retrieval=_FakeGraphRetrieval(
                [
                    EvidenceDocument(content="graph-1", recipe_name="C", node_id="3"),
                    EvidenceDocument(content="graph-2", recipe_name="D", node_id="4"),
                ]
            ),
            retrieval_profile=_FakeRetrievalProfile(),
        )

        outcome = CombinedRouteStrategy().execute(
            _request(
                query="recommend and explain flavor relations",
                top_k=2,
                strategy=SearchStrategy.COMBINED,
            ),
            services=services,
        )

        self.assertEqual([doc.recipe_name for doc in outcome.documents[:4]], ["C", "A", "D", "B"])
        self.assertEqual(outcome.stages[0].name, "combined")
        self.assertEqual(outcome.stages[0].details["traditional_doc_count"], 2)
        self.assertEqual(outcome.stages[0].details["graph_doc_count"], 2)
        self.assertEqual(outcome.stages[0].details["degraded_sources"], [])
        self.assertEqual(outcome.stages[0].details["candidate_k"], 4)

    def test_graph_strategy_uses_request_scoped_trace_when_available(self) -> None:
        services = RouteRetrievalServices(
            traditional_retrieval=_FakeTraditionalRetrieval(
                [EvidenceDocument(content="fallback", recipe_name="Fallback")]
            ),
            graph_rag_retrieval=_FakeGraphRetrieval(
                [EvidenceDocument(content="graph", recipe_name="Graph Dish")],
                trace={"query_type": "path_finding", "path_count": 3, "doc_count": 1},
            ),
            retrieval_profile=_FakeRetrievalProfile(),
        )

        outcome = GraphRouteStrategy().execute(
            _request(
                query="show the graph path",
                top_k=2,
                strategy=SearchStrategy.GRAPH_RAG,
            ),
            services=services,
        )

        self.assertEqual(outcome.stages[0].extra["query_type"], "path_finding")
        self.assertEqual(outcome.stages[0].extra["path_count"], 3)
        self.assertNotEqual(outcome.stages[0].extra["query_type"], "stale")

    def test_combined_strategy_executes_graph_and_traditional_in_parallel(self) -> None:
        traditional_started = threading.Event()
        graph_started = threading.Event()
        traditional = _ParallelTraditionalRetrieval(
            [EvidenceDocument(content="traditional", recipe_name="T", node_id="10")],
            own_started=traditional_started,
            other_started=graph_started,
        )
        graph = _ParallelGraphRetrieval(
            [EvidenceDocument(content="graph", recipe_name="G", node_id="20")],
            own_started=graph_started,
            other_started=traditional_started,
        )
        services = RouteRetrievalServices(
            traditional_retrieval=traditional,
            graph_rag_retrieval=graph,
            retrieval_profile=_FakeRetrievalProfile(),
        )

        outcome = CombinedRouteStrategy().execute(
            _request(
                query="parallel combined route",
                top_k=2,
                strategy=SearchStrategy.COMBINED,
            ),
            services=services,
        )

        self.assertTrue(traditional.observed_parallel_start)
        self.assertTrue(graph.observed_parallel_start)
        self.assertTrue(outcome.stages[0].details["parallel_execution"])
        self.assertIn("traditional_latency_ms", outcome.stages[0].details)
        self.assertIn("graph_latency_ms", outcome.stages[0].details)

    def test_combined_strategy_reuses_default_executor_across_executions(self) -> None:
        created_executors = []

        def build_executor(*args, **kwargs):
            executor = _SynchronousExecutor(*args, **kwargs)
            created_executors.append(executor)
            return executor

        services = RouteRetrievalServices(
            traditional_retrieval=_FakeTraditionalRetrieval(
                [EvidenceDocument(content="traditional", recipe_name="T", node_id="10")]
            ),
            graph_rag_retrieval=_FakeGraphRetrieval(
                [EvidenceDocument(content="graph", recipe_name="G", node_id="20")]
            ),
            retrieval_profile=_FakeRetrievalProfile(),
        )
        strategy = CombinedRouteStrategy()

        with patch(
            "rag_modules.routing.strategies.combined.ThreadPoolExecutor",
            side_effect=build_executor,
        ):
            for query in ("first combined route", "second combined route"):
                strategy.execute(
                    _request(
                        query=query,
                        top_k=2,
                        strategy=SearchStrategy.COMBINED,
                    ),
                    services=services,
                )

        self.assertEqual(len(created_executors), 1)
        self.assertEqual(len(created_executors[0].submit_calls), 4)
        self.assertEqual(created_executors[0].shutdown_calls, [])

    def test_combined_strategy_close_shuts_down_owned_default_executor(self) -> None:
        created_executors = []

        def build_executor(*args, **kwargs):
            executor = _SynchronousExecutor(*args, **kwargs)
            created_executors.append(executor)
            return executor

        services = RouteRetrievalServices(
            traditional_retrieval=_FakeTraditionalRetrieval(
                [EvidenceDocument(content="traditional", recipe_name="T", node_id="10")]
            ),
            graph_rag_retrieval=_FakeGraphRetrieval(
                [EvidenceDocument(content="graph", recipe_name="G", node_id="20")]
            ),
            retrieval_profile=_FakeRetrievalProfile(),
        )
        strategy = CombinedRouteStrategy()

        with patch(
            "rag_modules.routing.strategies.combined.ThreadPoolExecutor",
            side_effect=build_executor,
        ):
            strategy.execute(
                _request(
                    query="owned combined route",
                    top_k=2,
                    strategy=SearchStrategy.COMBINED,
                ),
                services=services,
            )
            strategy.close()
            strategy.close()
            strategy.execute(
                _request(
                    query="recreated combined route",
                    top_k=2,
                    strategy=SearchStrategy.COMBINED,
                ),
                services=services,
            )

        self.assertEqual(len(created_executors), 2)
        self.assertEqual(
            created_executors[0].shutdown_calls,
            [{"wait": False, "cancel_futures": True}],
        )
        self.assertEqual(created_executors[1].shutdown_calls, [])

    def test_combined_strategy_accepts_injected_executor(self) -> None:
        executor = _SynchronousExecutor()
        services = RouteRetrievalServices(
            traditional_retrieval=_FakeTraditionalRetrieval(
                [EvidenceDocument(content="traditional", recipe_name="T", node_id="10")]
            ),
            graph_rag_retrieval=_FakeGraphRetrieval(
                [EvidenceDocument(content="graph", recipe_name="G", node_id="20")]
            ),
            retrieval_profile=_FakeRetrievalProfile(),
        )

        with patch("rag_modules.routing.strategies.combined.ThreadPoolExecutor") as factory:
            CombinedRouteStrategy(executor=executor).execute(
                _request(
                    query="injected combined route",
                    top_k=2,
                    strategy=SearchStrategy.COMBINED,
                ),
                services=services,
            )

        self.assertFalse(factory.called)
        self.assertEqual(len(executor.submit_calls), 2)
        self.assertEqual(executor.shutdown_calls, [])

    def test_combined_strategy_close_does_not_shutdown_injected_executor(self) -> None:
        executor = _SynchronousExecutor()
        strategy = CombinedRouteStrategy(executor=executor)

        strategy.close()

        self.assertEqual(executor.shutdown_calls, [])

    def test_build_route_retrieval_request_keeps_query_plan_and_strategy(self) -> None:
        plan = QueryPlan(query="recommend tofu dishes")

        request = build_route_retrieval_request(
            query="recommend tofu dishes",
            top_k=3,
            candidate_k=5,
            constraints=QueryConstraints(max_cook_minutes=30),
            query_plan=plan,
            strategy="combined",
        )

        self.assertEqual(request.query, "recommend tofu dishes")
        self.assertEqual(request.candidate_k, 5)
        self.assertEqual(request.strategy, "combined")
        self.assertIs(request.query_plan, plan)
        self.assertEqual(request.constraints.max_cook_minutes, 30)


if __name__ == "__main__":
    unittest.main()
