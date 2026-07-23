from __future__ import annotations

import inspect
import unittest
from dataclasses import fields
from types import SimpleNamespace

from rag_modules.contracts import (
    EvidenceDocument,
    QuerySemanticRuntimeSettings,
    RequestControl,
    RetrievalRequest,
)
from rag_modules.contracts.runtime.errors import ensure_runtime_error_detail
from rag_modules.contracts.runtime.graph import GraphRetrievalSnapshot
from rag_modules.graph import ports as graph_ports
from rag_modules.graph.query_executor import GraphQueryExecutor
from rag_modules.graph.retrieval_executor import (
    GraphRetrievalExecutor,
    GraphRetrievalExecutorServices,
)
from tests.configuration_test_helpers import build_test_config


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
    source_node_ids = []
    source_terms = ["tofu"]
    target_node_ids = []
    target_terms = []
    relation_types = []
    max_depth = 3
    max_nodes = 24

    @staticmethod
    def to_trace():
        return {"max_depth": 3, "max_nodes": 24}


class _RecordingNeo4jSession:
    def __init__(self) -> None:
        self.run_calls = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        del exc_type, exc, tb
        return None

    def run(self, query, parameters=None, **kwargs):
        self.run_calls.append({"query": query, "parameters": parameters, "kwargs": kwargs})
        return []


class _RecordingNeo4jDriver:
    def __init__(self) -> None:
        self.session_obj = _RecordingNeo4jSession()

    def session(self, **kwargs):
        del kwargs
        return self.session_obj


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


def _executor_services(
    runtime: _FakeGraphRuntime,
    docs: list[EvidenceDocument] | None = None,
    *,
    config=None,
    neo4j_manager=None,
    database_name: str = "neo4j",
) -> GraphRetrievalExecutorServices:
    return GraphRetrievalExecutorServices(
        config=config or build_test_config(),
        runtime=runtime,
        orchestrator=_FakeOrchestrator(docs),
        cache_warmup=SimpleNamespace(),
        graph_cache_stats_store=SimpleNamespace(path="storage/cache.json"),
        entity_linker=SimpleNamespace(driver=None),
        graph_executor=SimpleNamespace(driver=None),
        neo4j_manager=neo4j_manager,
        database_name=database_name,
    )


class GraphRetrievalExecutorTests(unittest.TestCase):
    def test_executor_services_owns_all_constructor_dependencies(self) -> None:
        self.assertEqual(
            [
                "config",
                "runtime",
                "orchestrator",
                "cache_warmup",
                "graph_cache_stats_store",
                "entity_linker",
                "graph_executor",
                "neo4j_manager",
                "database_name",
            ],
            [field.name for field in fields(GraphRetrievalExecutorServices)],
        )

    def test_constructor_accepts_only_executor_services(self) -> None:
        signature = inspect.signature(GraphRetrievalExecutor)

        self.assertEqual(["services"], list(signature.parameters))
        self.assertIs(
            signature.parameters["services"].kind,
            inspect.Parameter.KEYWORD_ONLY,
        )

        with self.assertRaisesRegex(TypeError, "unexpected keyword argument 'config'"):
            GraphRetrievalExecutor(
                config=build_test_config(),
                services=_executor_services(_FakeGraphRuntime()),
            )

    def test_constructor_rejects_legacy_service_keywords(self) -> None:
        signature = inspect.signature(GraphRetrievalExecutor)
        self.assertFalse(
            any(
                parameter.kind is inspect.Parameter.VAR_KEYWORD
                for parameter in signature.parameters.values()
            )
        )

        with self.assertRaisesRegex(TypeError, "unexpected keyword argument 'runtime'"):
            GraphRetrievalExecutor(
                services=_executor_services(_FakeGraphRuntime()),
                runtime=_FakeGraphRuntime(),
                orchestrator=_FakeOrchestrator([]),
                cache_warmup=SimpleNamespace(),
                graph_cache_stats_store=SimpleNamespace(path="storage/cache.json"),
                entity_linker=SimpleNamespace(driver=None),
                graph_executor=SimpleNamespace(driver=None),
            )

    def test_graph_ports_define_narrow_neo4j_result_and_record_protocols(self) -> None:
        record_port = getattr(graph_ports, "Neo4jRecordPort", None)
        result_port = getattr(graph_ports, "Neo4jResultPort", None)

        self.assertIsNotNone(record_port)
        self.assertIsNotNone(result_port)
        self.assertIn("__getitem__", record_port.__dict__)
        self.assertIn("__iter__", result_port.__dict__)
        self.assertEqual(
            "Neo4jResultPort",
            inspect.signature(graph_ports.Neo4jSessionPort.run).return_annotation,
        )

    def test_graph_query_executor_passes_control_timeout_to_neo4j(self) -> None:
        driver = _RecordingNeo4jDriver()
        executor = GraphQueryExecutor(driver, database="neo4j")
        plan = _FakeRetrievalPlan()
        request = RetrievalRequest.from_inputs(
            query="tofu",
            top_k=2,
            control=RequestControl.for_timeout(3.0, scope="graph"),
        )

        executor.multi_hop_paths(plan, control=request.control)

        timeout = driver.session_obj.run_calls[0]["kwargs"]["timeout"]
        self.assertGreater(timeout, 0)
        self.assertLessEqual(timeout, 3.0)

    def test_execute_stops_when_control_cancelled_before_retrieve(self) -> None:
        runtime = _FakeGraphRuntime()
        control = RequestControl.for_timeout(5.0, scope="graph")
        control.cancel("combined_branch_timeout")
        executor = GraphRetrievalExecutor(
            services=_executor_services(
                runtime,
                [EvidenceDocument(content="should not return", entity_name="late")],
            ),
        )
        executor.driver = object()
        request = RetrievalRequest.from_inputs(query="tofu", top_k=2, control=control)

        results, trace = executor.execute_with_trace(request)

        self.assertEqual(results, [])
        self.assertEqual(trace.error.detail, "combined_branch_timeout")
        self.assertIn(
            ("request_control_cancelled", "error", {"reason": "combined_branch_timeout"}),
            runtime.events,
        )

    def test_initialize_raises_when_driver_setup_fails(self) -> None:
        runtime = _FakeGraphRuntime()
        config = build_test_config(
            {
                "storage": {
                    "neo4j_uri": "bolt://unused",
                    "neo4j_user": "neo4j",
                    "neo4j_password": "pass",
                }
            }
        )
        executor = GraphRetrievalExecutor(
            services=_executor_services(
                runtime,
                config=config,
                neo4j_manager=_FailingNeo4jManager(),
            ),
        )

        with self.assertRaisesRegex(RuntimeError, "Graph retrieval initialization failed"):
            executor.initialize()

        self.assertIsNone(executor.driver)

    def test_execute_records_trace_and_returns_documents(self) -> None:
        docs = [
            EvidenceDocument(
                content="图证据",
                entity_name="水煮肉片",
                evidence_units=[{"claim": "豆瓣酱贡献麻辣鲜香"}],
            )
        ]
        runtime = _FakeGraphRuntime()
        config = build_test_config(
            {
                "storage": {
                    "neo4j_uri": "bolt://unused",
                    "neo4j_user": "neo4j",
                    "neo4j_password": "pass",
                }
            }
        )
        executor = GraphRetrievalExecutor(
            services=_executor_services(runtime, docs, config=config),
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
        config = build_test_config(
            {
                "storage": {
                    "neo4j_uri": "bolt://unused",
                    "neo4j_user": "neo4j",
                    "neo4j_password": "pass",
                }
            }
        )
        executor = GraphRetrievalExecutor(
            services=_executor_services(runtime, config=config),
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

        config = build_test_config()
        runtime = GraphRetrievalRuntime(
            GraphQueryFactory(semantic_settings=QuerySemanticRuntimeSettings.from_config(config))
        )
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


def test_graph_query_executor_guards_missing_driver_and_selects_target_filter() -> None:
    no_driver = GraphQueryExecutor(None, database="neo4j")
    plan = _FakeRetrievalPlan()

    assert no_driver.multi_hop_paths(plan) == []
    assert no_driver.entity_relation_paths(plan) == []
    assert no_driver.shortest_paths(plan) == []
    assert no_driver.subgraphs(plan) == []
    assert GraphQueryExecutor._target_filter_clause(plan) == ""

    plan.target_terms = ["pepper"]
    assert "target_terms" in GraphQueryExecutor._target_filter_clause(plan)


def test_graph_query_executor_params_include_linked_ids_and_terms() -> None:
    plan = _FakeRetrievalPlan()
    plan.source_node_ids = ["r1"]
    plan.target_node_ids = ["i1"]
    plan.source_terms = ["tofu"]
    plan.target_terms = ["pepper"]

    params = GraphQueryExecutor._params(plan)

    assert params["source_node_ids"] == ["r1"]
    assert params["target_node_ids"] == ["i1"]
    assert params["source_terms"] == ["tofu"]
    assert params["target_terms"] == ["pepper"]


def test_graph_query_executor_omits_timeout_without_control() -> None:
    assert GraphQueryExecutor._run_kwargs(None) == {}


def test_graph_query_executor_runs_all_query_families() -> None:
    driver = _RecordingNeo4jDriver()
    executor = GraphQueryExecutor(driver, database="neo4j")
    plan = _FakeRetrievalPlan()

    assert executor.multi_hop_paths(plan) == []
    assert executor.entity_relation_paths(plan) == []
    assert executor.shortest_paths(plan) == []
    assert executor.subgraphs(plan) == []
    assert len(driver.session_obj.run_calls) == 4


def test_customer_service_graph_queries_filter_every_traversed_node_by_domain() -> None:
    driver = _RecordingNeo4jDriver()
    executor = GraphQueryExecutor(
        driver,
        database="neo4j",
        domain_name="customer_service",
        primary_node_labels=("Order", "RefundPolicy"),
        semantic_relation_types=("GOVERNED_BY", "SUPERSEDES"),
        semantic_node_labels=(),
    )
    plan = _FakeRetrievalPlan()
    plan.target_terms = ["2026.07"]

    executor.multi_hop_paths(plan)
    executor.entity_relation_paths(plan)
    executor.shortest_paths(plan)
    executor.subgraphs(plan)

    queries = [str(call["query"]) for call in driver.session_obj.run_calls]
    assert all("$domain_name" in query for query in queries)
    assert all(
        "ALL(n IN nodes(path) WHERE n.domain = $domain_name)" in query for query in queries[:3]
    )
    assert "source.domain = $domain_name" in queries[3]
    assert "neighbor.domain = $domain_name" in queries[3]


def test_recipe_graph_queries_reject_explicit_other_domain_nodes() -> None:
    driver = _RecordingNeo4jDriver()
    executor = GraphQueryExecutor(driver, database="neo4j", domain_name="recipe")
    plan = _FakeRetrievalPlan()

    executor.multi_hop_paths(plan)
    executor.subgraphs(plan)

    path_query = str(driver.session_obj.run_calls[0]["query"])
    subgraph_query = str(driver.session_obj.run_calls[1]["query"])
    assert "n.domain = $domain_name" in path_query
    assert "n.domain IS NULL" in path_query
    assert "label IN $allowed_node_labels" in path_query
    assert "source.domain = $domain_name" in subgraph_query
    assert "neighbor.domain = $domain_name" in subgraph_query
