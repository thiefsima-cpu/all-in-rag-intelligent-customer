from __future__ import annotations

import unittest

from rag_modules.contracts import EvidenceDocument, RetrievalRequest
from rag_modules.domain.shared.query_constraints import QueryConstraints
from rag_modules.retrieval.hybrid_executor import HybridRetrievalExecutor
from rag_modules.retrieval.hybrid_outcome import HybridRetrievalOutcome


class _FakeDualLevelService:
    def entity_level_retrieval(self, entity_keywords, top_k=5):
        del entity_keywords, top_k
        return [EvidenceDocument(content="entity", recipe_name="A", score=0.9)]

    def topic_level_retrieval(self, topic_keywords, top_k=5):
        del topic_keywords, top_k
        return [EvidenceDocument(content="topic", recipe_name="B", score=0.8)]


class _FakeRuntime:
    def __init__(self) -> None:
        self.driver = "driver"
        self.bm25 = "bm25"
        self.bm25_corpus_docs = ["doc-1"]
        self.graph_indexed = True
        self.parent_doc_map = {"p": "doc"}
        self.recipe_matcher = "matcher"
        self.vector_retriever = "vector"
        self.dual_level_service = _FakeDualLevelService()
        self.calls = []

    def initialize(self, chunks):
        self.calls.append(("initialize", list(chunks)))

    def apply_index_artifacts(self, artifacts):
        self.calls.append(("apply_index_artifacts", artifacts))

    def get_recipe_matcher(self):
        return self.recipe_matcher

    def ensure_dual_level_service(self):
        return self.dual_level_service

    def entity_level_results(self, entity_keywords, *, top_k=5):
        self.calls.append(("entity_level_results", list(entity_keywords), top_k))
        return self.dual_level_service.entity_level_retrieval(entity_keywords, top_k=top_k)

    def topic_level_results(self, topic_keywords, *, top_k=5):
        self.calls.append(("topic_level_results", list(topic_keywords), top_k))
        return self.dual_level_service.topic_level_retrieval(topic_keywords, top_k=top_k)

    def attach_parent_documents(self, docs, top_n=None):
        self.calls.append(("attach_parent_documents", top_n))
        return list(docs)

    def enrich_to_parent_documents(self, docs, top_n=None):
        self.calls.append(("enrich_to_parent_documents", top_n))
        return list(docs)

    def attach_parent_evidence_documents(self, docs, top_n=None):
        self.calls.append(("attach_parent_evidence_documents", top_n))
        return list(docs)

    def enrich_to_parent_evidence_documents(self, docs, top_n=None):
        self.calls.append(("enrich_to_parent_evidence_documents", top_n))
        return list(docs)

    def restore_bm25_retriever(self, payload):
        self.calls.append(("restore_bm25_retriever", payload))

    def sync_bm25_state(self):
        self.calls.append(("sync_bm25_state", None))

    def build_graph_index(self):
        self.calls.append(("build_graph_index", None))

    def build_parent_doc_map(self):
        self.calls.append(("build_parent_doc_map", None))
        return dict(self.parent_doc_map)

    def close(self):
        self.calls.append(("close", None))


class _FakeSearchService:
    def __init__(self) -> None:
        self.calls = []

    def build_request(self, request_or_query, **kwargs):
        self.calls.append(("build_request", request_or_query, dict(kwargs)))
        if isinstance(request_or_query, RetrievalRequest):
            return request_or_query
        return RetrievalRequest.from_inputs(query=request_or_query, **kwargs)

    def prepare_hybrid_request(self, request_or_query, **kwargs):
        self.calls.append(("prepare_hybrid_request", request_or_query, dict(kwargs)))
        return self.build_request(request_or_query, **kwargs)

    def dual_level_candidates(self, request):
        self.calls.append(("dual_level_candidates", request.query))
        return [EvidenceDocument(content="dual", recipe_name="dual")]

    def vector_candidates(self, request):
        self.calls.append(("vector_candidates", request.query))
        return [EvidenceDocument(content="vector", recipe_name="vector")]

    def bm25_candidates(self, request):
        self.calls.append(("bm25_candidates", request.query))
        return [EvidenceDocument(content="bm25", recipe_name="bm25")]

    def constraint_candidates(self, request):
        self.calls.append(("constraint_candidates", request.effective_constraints.to_dict()))
        return [EvidenceDocument(content="constraint", recipe_name="constraint")]

    def hybrid_evidence_search(self, request_or_query, **kwargs):
        self.calls.append(("hybrid_evidence_search", request_or_query, dict(kwargs)))
        return HybridRetrievalOutcome(
            documents=[EvidenceDocument(content="hybrid", recipe_name="hybrid")],
            candidate_counts={"vector": 1},
        )


class _FakeKeywordExtractor:
    def extract(self, query):
        return [query], [f"topic::{query}"]


class _FakeCacheStore:
    @staticmethod
    def signature(chunks):
        return f"sig::{len(chunks)}"

    @staticmethod
    def path():
        return "storage/hybrid_cache.json"


class HybridRetrievalExecutorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.runtime = _FakeRuntime()
        self.search_service = _FakeSearchService()
        self.executor = HybridRetrievalExecutor(
            runtime=self.runtime,
            search_service=self.search_service,
            keyword_extractor=_FakeKeywordExtractor(),
            cache_store=_FakeCacheStore(),
            bm25_tokenizer=lambda text: text.split(),
        )

    def test_hybrid_evidence_search_delegates_to_search_service(self) -> None:
        outcome = self.executor.hybrid_evidence_search("mapo tofu", top_k=3)

        self.assertEqual([doc.recipe_name for doc in outcome.documents], ["hybrid"])
        self.assertEqual(self.search_service.calls[-1][0], "hybrid_evidence_search")

    def test_entity_and_topic_results_use_runtime_contract(self) -> None:
        entity_results = self.executor.entity_level_results(["tofu"], top_k=2)
        topic_results = self.executor.topic_level_results(["light"], top_k=2)

        self.assertEqual(entity_results[0].recipe_name, "A")
        self.assertEqual(topic_results[0].recipe_name, "B")
        self.assertEqual(self.runtime.calls[0][0], "entity_level_results")
        self.assertEqual(self.runtime.calls[1][0], "topic_level_results")

    def test_build_request_and_constraint_candidates_stay_evidence_native(self) -> None:
        request = self.executor.build_request(
            "recommend tofu dishes",
            top_k=2,
            constraints=QueryConstraints(max_cook_minutes=30),
        )
        docs = self.executor.constraint_candidates(request)

        self.assertEqual(request.query, "recommend tofu dishes")
        self.assertEqual(docs[0].recipe_name, "constraint")
        self.assertEqual(self.search_service.calls[-1][0], "constraint_candidates")


if __name__ == "__main__":
    unittest.main()
