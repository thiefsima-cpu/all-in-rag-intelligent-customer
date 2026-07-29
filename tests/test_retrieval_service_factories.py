from __future__ import annotations

import unittest
from types import SimpleNamespace

from rag_modules.contracts import EvidenceDocument, RetrievalRequest
from rag_modules.contracts.runtime import GraphRetrievalSnapshot
from rag_modules.contracts.runtime.retrieval import HybridRetrievalOutcome
from rag_modules.graph.rag_retrieval import GraphRAGRetrieval
from rag_modules.graph.retrieval_components import GraphRetrievalComponents
from rag_modules.retrieval import HybridRetrievalService
from rag_modules.retrieval.hybrid_components import (
    DefaultHybridRetrievalComponentFactory,
    HybridRetrievalComponents,
)
from rag_modules.retrieval.hybrid_runtime import HybridRetrievalRuntime
from rag_modules.retrieval.hybrid_search_service import HybridSearchService
from rag_modules.retrieval.keyword_service import QueryKeywordExtractor
from rag_modules.retrieval.runtime_profile import RetrievalRuntimeProfile
from tests.configuration_test_helpers import build_test_config


class _FakeHybridRuntime:
    def __init__(self) -> None:
        self.driver = "driver"
        self.bm25 = "bm25"
        self.bm25_corpus_docs = []
        self.graph_indexed = True
        self.parent_doc_map = {"p": "doc"}
        self.recipe_matcher = "matcher"
        self.vector_retriever = "vector"
        self.dual_level_service = "dual"

    @staticmethod
    def close():
        return None


class _FakeHybridSearchService:
    def __init__(self) -> None:
        self.calls = []

    def hybrid_evidence_search(self, request):
        self.calls.append(("hybrid_evidence_search", request))
        return HybridRetrievalOutcome(
            documents=[EvidenceDocument(content="hybrid", entity_name="HybridRecipe")],
            candidate_counts={"vector": 1},
        )


class _FakeKeywordExtractor:
    @staticmethod
    def extract(query):
        return [query], [f"topic::{query}"]


class _FakeHybridFactory:
    def __init__(self) -> None:
        self.calls = []
        self.runtime = _FakeHybridRuntime()
        self.search_service = _FakeHybridSearchService()
        self.keyword_extractor = _FakeKeywordExtractor()

    def build(self, **kwargs):
        self.calls.append(dict(kwargs))
        return HybridRetrievalComponents(
            keyword_extractor=self.keyword_extractor,
            runtime=self.runtime,
            search_service=self.search_service,
        )


class _FakeGraphQueryFactory:
    @staticmethod
    def understand_graph_query(query):
        return {"understood": query}

    @staticmethod
    def graph_query_from_plan(plan):
        return {"plan": getattr(plan, "strategy", "")}

    @staticmethod
    def graph_query_from_intent(intent, query):
        return {"intent": str(intent), "query": query}

    @staticmethod
    def adaptive_query_planning(query):
        return [{"query": query, "mode": "adaptive"}]

    @staticmethod
    def analyze_query_complexity(query):
        return 0.9 if query else 0.0


class _FakeGraphRuntime:
    def __init__(self) -> None:
        self.calls = []

    def build_request(self, request: RetrievalRequest):
        self.calls.append(request)
        return request


class _FakeGraphExecutor:
    def __init__(self) -> None:
        self.driver = "graph-driver"
        self.entity_cache = {}
        self.relation_cache = {}
        self.subgraph_cache = {}
        self.calls = []

    def execute_with_trace(self, request):
        self.calls.append(request)
        return (
            [EvidenceDocument(content="graph", entity_name=request.query)],
            GraphRetrievalSnapshot(requested_top_k=request.top_k),
        )

    @staticmethod
    def initialize():
        return None

    @staticmethod
    def build_graph_index():
        return None

    @staticmethod
    def close():
        return None


class _FakeGraphOrchestrator:
    @staticmethod
    def graph_structure_reasoning(subgraph, query):
        return [f"{subgraph}:{query}"]

    @staticmethod
    def build_retrieval_plan(graph_query, *, evidence_goals):
        return {"graph_query": graph_query, "evidence_goals": evidence_goals}

    @staticmethod
    def execute_graph_plan(retrieval_plan):
        return [retrieval_plan]

    @staticmethod
    def extract_knowledge_subgraph(graph_query):
        return {"subgraph": graph_query}

    @staticmethod
    def paths_to_evidence_documents(paths, query):
        del query
        return list(paths)

    @staticmethod
    def subgraph_to_evidence_documents(subgraph, reasoning_chains, query):
        return [{"subgraph": subgraph, "reasoning_chains": reasoning_chains, "query": query}]

    @staticmethod
    def build_path_description(path):
        return str(path)

    @staticmethod
    def build_subgraph_description(subgraph):
        return str(subgraph)

    @staticmethod
    def summarize_subgraph_evidence(subgraph):
        return subgraph

    @staticmethod
    def relationship_lines(subgraph, limit=30):
        return [str(subgraph), str(limit)]

    @staticmethod
    def identify_reasoning_patterns(subgraph):
        return [str(subgraph)]

    @staticmethod
    def build_reasoning_chain(pattern, subgraph):
        return f"{pattern}:{subgraph}"

    @staticmethod
    def validate_reasoning_chains(chains, query):
        return [f"{query}:{chain}" for chain in chains]

    @staticmethod
    def reason_over_subgraph(subgraph, query):
        return {"subgraph": subgraph, "query": query}

    @staticmethod
    def empty_subgraph():
        return {}


class _FakeGraphFactory:
    def __init__(self) -> None:
        self.calls = []
        self.runtime = _FakeGraphRuntime()
        self.executor = _FakeGraphExecutor()
        self.query_factory = _FakeGraphQueryFactory()
        self.orchestrator = _FakeGraphOrchestrator()

    def build(self, **kwargs):
        self.calls.append(dict(kwargs))
        return GraphRetrievalComponents(
            query_factory=self.query_factory,
            runtime=self.runtime,
            entity_linker=SimpleNamespace(),
            graph_plan_builder=SimpleNamespace(),
            graph_executor=SimpleNamespace(),
            postprocessor=SimpleNamespace(),
            reasoning_strategy=SimpleNamespace(),
            orchestrator=self.orchestrator,
            graph_cache_stats_store=SimpleNamespace(),
            cache_warmup=SimpleNamespace(),
            executor=self.executor,
        )


class RetrievalFacadeFactoryTests(unittest.TestCase):
    def test_default_hybrid_factory_builds_direct_service_collaborators(self) -> None:
        config = build_test_config()
        retrieval_profile = RetrievalRuntimeProfile.from_config(config)
        adapter_factory = SimpleNamespace(name="adapter-factory")

        components = DefaultHybridRetrievalComponentFactory().build(
            config=config,
            milvus_module=SimpleNamespace(),
            data_module=SimpleNamespace(),
            llm_client=SimpleNamespace(),
            neo4j_manager=None,
            retrieval_profile=retrieval_profile,
            database=config.storage.neo4j_database,
            rrf_k=71,
            adapter_factory=adapter_factory,
        )

        self.assertIsInstance(components.runtime, HybridRetrievalRuntime)
        self.assertIsInstance(components.search_service, HybridSearchService)
        self.assertIsInstance(components.keyword_extractor, QueryKeywordExtractor)
        self.assertIs(components.search_service.runtime, components.runtime)
        self.assertIs(components.runtime.adapter_factory, adapter_factory)
        self.assertEqual(components.search_service.fusion_ranker.rrf_k, 71)

    def test_hybrid_retrieval_uses_component_factory_seam(self) -> None:
        factory = _FakeHybridFactory()
        adapter_factory = SimpleNamespace(name="adapter-factory")
        config = build_test_config(
            {
                "storage": {"neo4j_database": "recipes"},
                "retrieval": {"rrf_k": 88},
            }
        )
        retrieval_profile = SimpleNamespace(semantics=SimpleNamespace())

        module = HybridRetrievalService(
            config=config,
            milvus_module=SimpleNamespace(),
            data_module=SimpleNamespace(),
            llm_client=SimpleNamespace(),
            neo4j_manager=SimpleNamespace(),
            retrieval_profile=retrieval_profile,
            component_factory=factory,
            adapter_factory=adapter_factory,
        )

        request = RetrievalRequest.from_inputs(query="mapo tofu", top_k=2, candidate_k=2)

        outcome = module.hybrid_evidence_search(request)

        self.assertEqual(outcome.documents[0].entity_name, "HybridRecipe")
        self.assertEqual(module.driver, "driver")
        self.assertEqual(
            module.extract_query_keywords("mapo tofu"),
            (["mapo tofu"], ["topic::mapo tofu"]),
        )
        with self.assertRaises(AttributeError):
            _ = module.executor
        with self.assertRaises(AttributeError):
            _ = module.runtime
        self.assertIs(module.components.runtime, factory.runtime)
        self.assertIs(module.components.search_service, factory.search_service)
        self.assertEqual(factory.calls[0]["database"], "recipes")
        self.assertEqual(factory.calls[0]["rrf_k"], 88)
        self.assertIs(factory.calls[0]["adapter_factory"], adapter_factory)

    def test_graph_rag_retrieval_uses_component_factory_seam(self) -> None:
        factory = _FakeGraphFactory()
        config = build_test_config({"storage": {"neo4j_database": "recipes"}})
        retrieval_profile = SimpleNamespace(semantics=SimpleNamespace())

        module = GraphRAGRetrieval(
            config=config,
            llm_client=SimpleNamespace(),
            neo4j_manager=SimpleNamespace(),
            retrieval_profile=retrieval_profile,
            component_factory=factory,
        )

        request = RetrievalRequest.from_inputs(
            query="Explain the layered flavor path",
            top_k=3,
            candidate_k=3,
        )

        results, trace = module.graph_rag_evidence_search_with_trace(request)

        self.assertEqual(results[0].entity_name, "Explain the layered flavor path")
        self.assertEqual(trace.requested_top_k, 3)
        with self.assertRaises(AttributeError):
            _ = module.understand_graph_query
        with self.assertRaises(AttributeError):
            _ = module.components
        self.assertEqual(factory.executor.calls[0].query, "Explain the layered flavor path")
        self.assertEqual(factory.calls[0]["database_name"], "recipes")

    def test_graph_rag_retrieval_keeps_only_service_api_and_lifecycle(self) -> None:
        defined_surface = {
            name
            for name, value in vars(GraphRAGRetrieval).items()
            if not name.startswith("__") and (callable(value) or isinstance(value, property))
        }

        self.assertEqual(
            defined_surface,
            {
                "close",
                "graph_query_from_plan",
                "graph_rag_evidence_search_with_trace",
                "initialize",
            },
        )


if __name__ == "__main__":
    unittest.main()
