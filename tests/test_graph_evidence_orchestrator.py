from __future__ import annotations

from types import SimpleNamespace

import pytest

from rag_modules.contracts import EvidenceDocument, GraphQueryType, RequestControl, RetrievalRequest
from rag_modules.contracts.graph import GraphQuery
from rag_modules.graph.evidence_orchestrator import GraphEvidenceOrchestrator
from rag_modules.graph.reasoning_strategy import GraphReasoningOutcome
from rag_modules.graph.retrieval_plan import GraphRetrievalPlan
from rag_modules.graph.retrieval_types import GraphPath, KnowledgeSubgraph


class _Executor:
    def __init__(self, *, driver=object(), error: Exception | None = None) -> None:
        self.driver = driver
        self.error = error
        self.calls: list[str] = []

    def _records(self, name: str):
        self.calls.append(name)
        if self.error:
            raise self.error
        return [{"kind": name}, None]

    def shortest_paths(self, plan, *, control=None):
        return self._records("shortest")

    def entity_relation_paths(self, plan, *, control=None):
        return self._records("entity")

    def multi_hop_paths(self, plan, *, control=None):
        return self._records("multi")

    def subgraphs(self, plan, *, control=None):
        return self._records("subgraph")


class _Postprocessor:
    def parse_neo4j_path(self, record, path_type="multi_hop"):
        if record is None:
            return None
        return GraphPath(path_type=path_type)

    def build_knowledge_subgraph(self, record):
        return KnowledgeSubgraph(graph_metrics={"density": 0.5})

    def merge_subgraphs(self, subgraphs):
        return subgraphs[0]

    def to_ranked_evidence_documents(self, documents, query):
        return list(reversed(documents))

    def paths_to_evidence_documents(self, paths, query):
        return [
            EvidenceDocument(content=path.path_type, evidence_units=[{"claim": query}])
            for path in paths
        ]

    def subgraph_to_evidence_documents(self, subgraph, reasoning_chains, query):
        return [EvidenceDocument(content=query, metadata={"chains": reasoning_chains})]

    def build_path_description(self, path):
        return path.path_type

    def build_subgraph_description(self, subgraph):
        return "subgraph"

    def summarize_subgraph_evidence(self, subgraph):
        return {"density": subgraph.graph_metrics.get("density", 0.0)}

    def relationship_lines(self, subgraph, limit=30):
        return [str(limit)]

    def empty_subgraph(self):
        return KnowledgeSubgraph()


class _Reasoner:
    def reason(self, subgraph, query):
        return GraphReasoningOutcome(patterns=["causal"], validated_chains=[query])

    def identify_reasoning_patterns(self, subgraph, query):
        return ["causal"]

    def build_reasoning_chains(self, pattern, subgraph, query):
        return [pattern] if pattern else []


class _PlanBuilder:
    def __init__(self) -> None:
        self.calls = []

    def build(self, query, *, evidence_goals):
        self.calls.append((query, list(evidence_goals)))
        return _plan(query.query_type)


def _orchestrator(executor=None) -> GraphEvidenceOrchestrator:
    return GraphEvidenceOrchestrator(
        graph_plan_builder=_PlanBuilder(),
        graph_executor=executor or _Executor(),
        postprocessor=_Postprocessor(),
        reasoning_strategy=_Reasoner(),
    )


def _plan(query_type: GraphQueryType) -> GraphRetrievalPlan:
    return GraphRetrievalPlan(query_type=query_type.value, source_entities=["tofu"])


@pytest.mark.parametrize(
    "query_type, expected_call, expected_path_type",
    [
        (GraphQueryType.PATH_FINDING, "shortest", "shortest_path"),
        (GraphQueryType.ENTITY_RELATION, "entity", "entity_relation"),
        (GraphQueryType.MULTI_HOP, "multi", "multi_hop"),
    ],
)
def test_execute_graph_plan_dispatches_and_skips_unparseable_records(
    query_type, expected_call, expected_path_type
) -> None:
    orchestrator = _orchestrator()

    [path] = orchestrator.execute_graph_plan(_plan(query_type))

    assert orchestrator.graph_executor.calls == [expected_call]
    assert path.path_type == expected_path_type


def test_build_plan_delegates_evidence_goals() -> None:
    orchestrator = _orchestrator()
    query = GraphQuery(query_type=GraphQueryType.SUBGRAPH, source_entities=["tofu"])

    plan = orchestrator.build_retrieval_plan(query, evidence_goals=["why"])

    assert plan.query_type == GraphQueryType.SUBGRAPH.value
    assert orchestrator.graph_plan_builder.calls == [(query, ["why"])]


def test_extract_subgraph_handles_disconnected_success_and_error() -> None:
    assert (
        _orchestrator(_Executor(driver=None)).extract_knowledge_subgraph(
            _plan(GraphQueryType.SUBGRAPH)
        )
        == KnowledgeSubgraph()
    )

    merged = _orchestrator().extract_knowledge_subgraph(_plan(GraphQueryType.SUBGRAPH))
    assert merged.graph_metrics == {"density": 0.5}

    failed = _orchestrator(_Executor(error=RuntimeError("down"))).extract_knowledge_subgraph(
        _plan(GraphQueryType.SUBGRAPH)
    )
    assert failed == KnowledgeSubgraph()


def test_extract_subgraph_builds_plan_from_graph_query() -> None:
    orchestrator = _orchestrator()
    query = GraphQuery(query_type=GraphQueryType.SUBGRAPH, source_entities=["tofu"])

    result = orchestrator.extract_knowledge_subgraph(query)

    assert result.graph_metrics == {"density": 0.5}


def test_reasoning_degrades_ordinary_errors_and_validates_unique_chains() -> None:
    orchestrator = _orchestrator()
    orchestrator.reasoning_strategy.reason = lambda subgraph, query: (_ for _ in ()).throw(
        RuntimeError("bad reasoning")
    )

    assert (
        orchestrator.reason_over_subgraph(KnowledgeSubgraph(), "query") == GraphReasoningOutcome()
    )
    assert orchestrator.validate_reasoning_chains([" a ", "", "a", "b", "c", "d"], "q") == [
        "a",
        "b",
        "c",
    ]


def _event_recorder(events):
    def record(trace, name, **kwargs):
        events.append((name, kwargs["details"]))

    return record


@pytest.mark.parametrize(
    "query_type",
    [GraphQueryType.MULTI_HOP, GraphQueryType.PATH_FINDING, GraphQueryType.ENTITY_RELATION],
)
def test_retrieve_path_queries_rank_truncate_and_record_counts(query_type) -> None:
    orchestrator = _orchestrator()
    events = []
    trace = SimpleNamespace(path_count=0)
    request = RetrievalRequest.from_inputs(query="why", top_k=1)

    result = orchestrator.retrieve(
        request=request,
        graph_query=GraphQuery(query_type=query_type, source_entities=["tofu"]),
        retrieval_plan=_plan(query_type),
        trace=trace,
        record_event=_event_recorder(events),
    )

    assert len(result.final_documents) == 1
    assert result.evidence_unit_count == 1
    assert trace.path_count == 1
    assert [name for name, _ in events] == [
        "execute_graph_paths",
        "rank_graph_evidence_documents",
    ]


@pytest.mark.parametrize("query_type", [GraphQueryType.SUBGRAPH, GraphQueryType.CLUSTERING])
def test_retrieve_subgraph_queries_record_reasoning(query_type) -> None:
    orchestrator = _orchestrator()
    events = []
    trace = SimpleNamespace(subgraph_count=0, reasoning_patterns=[], reasoning_chain_count=0)

    result = orchestrator.retrieve(
        request=RetrievalRequest.from_inputs(query="why", top_k=2),
        graph_query=GraphQuery(query_type=query_type, source_entities=["tofu"]),
        retrieval_plan=_plan(query_type),
        trace=trace,
        record_event=_event_recorder(events),
    )

    assert result.final_documents[0].metadata["chains"] == ["why"]
    assert trace.reasoning_patterns == ["causal"]
    assert trace.reasoning_chain_count == 1
    assert [name for name, _ in events] == [
        "extract_knowledge_subgraph",
        "graph_structure_reasoning",
        "rank_graph_evidence_documents",
    ]


def test_execute_graph_evidence_returns_empty_for_unknown_query_type() -> None:
    orchestrator = _orchestrator()

    assert (
        orchestrator._execute_graph_evidence(
            request=RetrievalRequest.from_inputs(query="query"),
            graph_query=SimpleNamespace(query_type="unknown"),
            retrieval_plan=_plan(GraphQueryType.MULTI_HOP),
            trace=SimpleNamespace(),
            record_event=lambda *args, **kwargs: None,
        )
        == []
    )


def test_compatibility_wrappers_delegate_to_collaborators() -> None:
    orchestrator = _orchestrator()
    path = GraphPath(path_type="multi")
    subgraph = KnowledgeSubgraph(graph_metrics={"density": 0.2})

    assert orchestrator.paths_to_evidence_documents([path], "q")[0].content == "multi"
    assert orchestrator.subgraph_to_evidence_documents(subgraph, ["chain"], "q")[0].metadata == {
        "chains": ["chain"]
    }
    assert orchestrator.build_path_description(path) == "multi"
    assert orchestrator.build_subgraph_description(subgraph) == "subgraph"
    assert orchestrator.summarize_subgraph_evidence(subgraph) == {"density": 0.2}
    assert orchestrator.relationship_lines(subgraph, limit=2) == ["2"]
    assert orchestrator.identify_reasoning_patterns(subgraph) == ["causal"]
    assert orchestrator.build_reasoning_chain("causal", subgraph) == "causal"
    assert orchestrator.build_reasoning_chain("", subgraph) is None
    assert orchestrator.empty_subgraph() == KnowledgeSubgraph()


def test_request_control_is_checked_across_path_subgraph_reasoning_and_ranking() -> None:
    orchestrator = _orchestrator()
    control = RequestControl.for_timeout(5.0, scope="graph")
    path_plan = _plan(GraphQueryType.MULTI_HOP)

    assert orchestrator.execute_graph_plan(path_plan, control=control)
    subgraph = orchestrator.extract_knowledge_subgraph(
        _plan(GraphQueryType.SUBGRAPH), control=control
    )
    assert orchestrator.reason_over_subgraph(subgraph, "why", control=control).validated_chains == [
        "why"
    ]

    result = orchestrator.retrieve(
        request=RetrievalRequest.from_inputs(query="why", top_k=1, control=control),
        graph_query=GraphQuery(
            query_type=GraphQueryType.MULTI_HOP,
            source_entities=["tofu"],
        ),
        retrieval_plan=path_plan,
        trace=SimpleNamespace(path_count=0),
        record_event=lambda *args, **kwargs: None,
    )
    assert result.final_documents
