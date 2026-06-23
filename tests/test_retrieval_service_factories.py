from __future__ import annotations

import unittest
from types import SimpleNamespace

from rag_modules.configuration.testing import build_test_config
from rag_modules.graph.retrieval import GraphRAGRetrieval, GraphRetrievalComponents
from rag_modules.retrieval import HybridRetrievalService
from rag_modules.retrieval.contracts import EvidenceDocument, RetrievalRequest
from rag_modules.retrieval.hybrid_components import HybridRetrievalComponents
from rag_modules.retrieval.hybrid_outcome import HybridRetrievalOutcome


class _FakeHybridExecutor:
    def __init__(self) -> None:
        self.driver = "driver"
        self.bm25 = "bm25"
        self.bm25_corpus_docs = []
        self.graph_indexed = True
        self.parent_doc_map = {"p": "doc"}
        self.recipe_matcher = "matcher"
        self.vector_retriever = "vector"
        self.dual_level_service = "dual"
        self.calls = []

    def hybrid_evidence_search(self, request_or_query, **kwargs):
        self.calls.append(("hybrid_evidence_search", request_or_query, dict(kwargs)))
        return HybridRetrievalOutcome(
            documents=[EvidenceDocument(content="hybrid", recipe_name="HybridRecipe")],
            candidate_counts={"vector": 1},
        )

    @staticmethod
    def extract_query_keywords(query):
        return [query], [f"topic::{query}"]

    @staticmethod
    def build_request(request_or_query, **kwargs):
        if isinstance(request_or_query, RetrievalRequest):
            return request_or_query
        return RetrievalRequest.from_inputs(query=request_or_query, **kwargs)

    @staticmethod
    def close():
        return None


class _FakeHybridFactory:
    def __init__(self) -> None:
        self.calls = []
        self.executor = _FakeHybridExecutor()
        self.runtime = SimpleNamespace(name="hybrid-runtime")

    def build(self, **kwargs):
        self.calls.append(dict(kwargs))
        return HybridRetrievalComponents(
            graph_indexing=SimpleNamespace(),
            fusion_ranker=SimpleNamespace(rrf_k=kwargs["rrf_k"]),
            cache_store=SimpleNamespace(path=lambda: "cache.json", signature=lambda chunks: "sig"),
            parent_enricher=SimpleNamespace(),
            bm25_retriever=SimpleNamespace(),
            graph_kv_retriever=SimpleNamespace(),
            keyword_extractor=SimpleNamespace(),
            index_service=SimpleNamespace(),
            runtime=self.runtime,
            constraint_retriever=SimpleNamespace(),
            search_service=SimpleNamespace(),
            executor=self.executor,
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

    def build_request(self, request_or_query, **kwargs):
        self.calls.append((request_or_query, dict(kwargs)))
        if isinstance(request_or_query, RetrievalRequest):
            return request_or_query
        return RetrievalRequest.from_inputs(
            query=request_or_query,
            top_k=kwargs.get("top_k", 5),
            candidate_k=kwargs.get("top_k", 5),
            constraints=kwargs.get("constraints"),
            query_plan=kwargs.get("query_plan"),
            strategy="graph_rag",
        )


class _FakeGraphExecutor:
    def __init__(self) -> None:
        self.driver = "graph-driver"
        self.entity_cache = {}
        self.relation_cache = {}
        self.subgraph_cache = {}
        self.calls = []

    def execute(self, request):
        self.calls.append(request)
        return [EvidenceDocument(content="graph", recipe_name=request.query)]

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

        outcome = module.hybrid_evidence_search("mapo tofu", top_k=2)

        self.assertEqual(outcome.documents[0].recipe_name, "HybridRecipe")
        self.assertEqual(module.driver, "driver")
        self.assertEqual(
            module.extract_query_keywords("mapo tofu"),
            (["mapo tofu"], ["topic::mapo tofu"]),
        )
        self.assertIs(module.components.executor, factory.executor)
        with self.assertRaises(AttributeError):
            _ = module.runtime
        self.assertIs(module.components.runtime, factory.runtime)
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

        results = module.graph_rag_evidence_search("Explain the layered flavor path", top_k=3)
        module.entity_cache = {"entity": 1}

        self.assertEqual(results[0].recipe_name, "Explain the layered flavor path")
        self.assertEqual(module.understand_graph_query("query"), {"understood": "query"})
        self.assertEqual(module.entity_cache, {"entity": 1})
        self.assertIs(module.components.executor, factory.executor)
        with self.assertRaises(AttributeError):
            _ = module.orchestrator
        self.assertIs(module.components.orchestrator, factory.orchestrator)
        self.assertEqual(factory.calls[0]["database_name"], "recipes")


if __name__ == "__main__":
    unittest.main()
