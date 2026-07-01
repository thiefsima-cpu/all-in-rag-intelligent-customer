from __future__ import annotations

import unittest
from types import SimpleNamespace

from rag_modules.configuration.testing import build_test_config
from rag_modules.contracts import EvidenceDocument, RetrievalRequest
from rag_modules.graph.retrieval import GraphRetrievalExecutor
from rag_modules.runtime.error_models import ensure_runtime_error_detail
from rag_modules.runtime.graph_models import GraphRetrievalSnapshot


class _FakeGraphRuntime:
    def __init__(self) -> None:
        self.events = []

    @staticmethod
    def start_trace(query, *, requested_top_k=0, retrieval_request=None):
        return GraphRetrievalSnapshot(
            query=query,
            requested_top_k=requested_top_k,
            retrieval_request=retrieval_request,
        )

    @staticmethod
    def populate_trace_context(trace, *, graph_query, evidence_goals):
        trace.query_type = graph_query.query_type.value
        trace.source_entities = list(graph_query.source_entities or [])
        trace.target_entities = list(graph_query.target_entities or [])
        trace.relation_types = list(graph_query.relation_types or [])
        trace.sub_questions = list(evidence_goals or [])

    @staticmethod
    def finalize_trace(trace, *, start_time, doc_count=0, evidence_unit_count=0, error=""):
        del start_time
        trace.doc_count = doc_count
        trace.evidence_unit_count = evidence_unit_count
        trace.error = ensure_runtime_error_detail(error)
        return trace

    def record_event(
        self, trace, name, *, start_time=None, latency_ms=None, status="ok", details=None
    ):
        del start_time, latency_ms
        self.events.append((name, status, details or {}))
        trace.add_event(name, status=status, latency_ms=0.0, details=details or {})

    @staticmethod
    def resolve_request_context(request):
        graph_query = SimpleNamespace(
            query_type=SimpleNamespace(value="multi_hop"),
            source_entities=["水煮肉片"],
            target_entities=["麻辣鲜香"],
            relation_types=["CONTRIBUTES_TO"],
        )
        return graph_query, [f"explain::{request.query}"]


class _FakeRetrievalPlan:
    linked_sources = [SimpleNamespace(resolved_value="水煮肉片")]
    linked_targets = [SimpleNamespace(resolved_value="麻辣鲜香")]
    max_depth = 3
    max_nodes = 24

    @staticmethod
    def to_trace():
        return {"max_depth": 3, "max_nodes": 24}


class _FakeOrchestrator:
    def __init__(self, docs=None) -> None:
        self.docs = list(docs or [])
        self.calls = []

    def build_retrieval_plan(self, graph_query, *, evidence_goals):
        self.calls.append(("build_retrieval_plan", graph_query, tuple(evidence_goals)))
        return _FakeRetrievalPlan()

    def retrieve(self, *, request, graph_query, retrieval_plan, trace, record_event):
        self.calls.append(("retrieve", request.query, graph_query.query_type.value))
        record_event(
            trace,
            "executor_retrieve",
            details={"retrieval_plan": retrieval_plan.to_trace()},
        )
        return SimpleNamespace(
            final_documents=list(self.docs),
            evidence_unit_count=sum(len(doc.evidence_units or []) for doc in self.docs),
        )


class _FailingNeo4jManager:
    @property
    def driver(self):
        raise RuntimeError("boom")


class GraphRetrievalExecutorTests(unittest.TestCase):
    def test_initialize_raises_when_driver_setup_fails(self) -> None:
        runtime = _FakeGraphRuntime()
        executor = GraphRetrievalExecutor(
            config=build_test_config(
                {
                    "storage": {
                        "neo4j_uri": "bolt://unused",
                        "neo4j_user": "neo4j",
                        "neo4j_password": "pass",
                    }
                }
            ),
            runtime=runtime,
            orchestrator=_FakeOrchestrator([]),
            cache_warmup=SimpleNamespace(),
            graph_cache_stats_store=SimpleNamespace(path="storage/cache.json"),
            entity_linker=SimpleNamespace(driver=None),
            graph_executor=SimpleNamespace(driver=None),
            neo4j_manager=_FailingNeo4jManager(),
            database_name="neo4j",
        )

        with self.assertRaisesRegex(RuntimeError, "Graph retrieval initialization failed"):
            executor.initialize()

        self.assertIsNone(executor.driver)

    def test_execute_records_trace_and_returns_documents(self) -> None:
        docs = [
            EvidenceDocument(
                content="图证据",
                recipe_name="水煮肉片",
                evidence_units=[{"claim": "豆瓣酱贡献麻辣鲜香"}],
            )
        ]
        runtime = _FakeGraphRuntime()
        executor = GraphRetrievalExecutor(
            config=build_test_config(
                {
                    "storage": {
                        "neo4j_uri": "bolt://unused",
                        "neo4j_user": "neo4j",
                        "neo4j_password": "pass",
                    }
                }
            ),
            runtime=runtime,
            orchestrator=_FakeOrchestrator(docs),
            cache_warmup=SimpleNamespace(),
            graph_cache_stats_store=SimpleNamespace(path="storage/cache.json"),
            entity_linker=SimpleNamespace(driver=None),
            graph_executor=SimpleNamespace(driver=None),
            database_name="neo4j",
        )
        executor.driver = object()

        request = RetrievalRequest.from_inputs(query="为什么水煮肉片会麻辣鲜香？", top_k=2)
        results, trace = executor.execute_with_trace(request)

        self.assertEqual(results, docs)
        self.assertEqual(trace.query, request.query)
        self.assertEqual(trace.doc_count, 1)
        self.assertEqual(trace.evidence_unit_count, 1)
        self.assertIn("build_retrieval_plan", [event.name for event in trace.events])
        self.assertIn("executor_retrieve", [event.name for event in trace.events])
        self.assertFalse(hasattr(executor, "last_trace"))

    def test_execute_without_driver_marks_trace_error(self) -> None:
        runtime = _FakeGraphRuntime()
        executor = GraphRetrievalExecutor(
            config=build_test_config(
                {
                    "storage": {
                        "neo4j_uri": "bolt://unused",
                        "neo4j_user": "neo4j",
                        "neo4j_password": "pass",
                    }
                }
            ),
            runtime=runtime,
            orchestrator=_FakeOrchestrator([]),
            cache_warmup=SimpleNamespace(),
            graph_cache_stats_store=SimpleNamespace(path="storage/cache.json"),
            entity_linker=SimpleNamespace(driver=None),
            graph_executor=SimpleNamespace(driver=None),
            database_name="neo4j",
        )

        request = RetrievalRequest.from_inputs(query="测试问题", top_k=1)
        results, trace = executor.execute_with_trace(request)

        self.assertEqual(results, [])
        self.assertEqual(
            trace.error.to_dict(),
            {"code": "GRAPH_OPERATION_FAILED", "detail": "neo4j_not_connected"},
        )
        self.assertIn("validate_driver", [event.name for event in trace.events])

    def test_graph_runtime_records_policy_metadata_and_policy_sub_questions(self) -> None:
        from rag_modules.graph.query_resolution import GraphQueryFactory
        from rag_modules.graph.retrieval_runtime import GraphRetrievalRuntime

        runtime = GraphRetrievalRuntime(GraphQueryFactory())
        request = RetrievalRequest.from_inputs(
            query="why does sauce affect texture",
            top_k=2,
            strategy="graph_rag",
        )

        graph_query, goals = runtime.resolve_request_context(request)
        trace = runtime.start_trace(request.query, requested_top_k=2, retrieval_request=request)
        runtime.populate_trace_context(trace, graph_query=graph_query, evidence_goals=goals)

        self.assertTrue(trace.policy.is_recorded())
        self.assertTrue(trace.sub_questions)
        self.assertIn(trace.policy.policy_version, trace.to_dict()["policy"]["policy_version"])


if __name__ == "__main__":
    unittest.main()
