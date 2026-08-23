from __future__ import annotations

import unittest
from types import SimpleNamespace

from rag_modules.contracts import (
    EvidenceDocument,
    RequestCancelled,
    RequestControl,
    RetrievalRequest,
)
from rag_modules.contracts.query_constraints import QueryConstraints
from rag_modules.contracts.runtime.retrieval import HybridRetrievalOutcome
from rag_modules.kernel.documents import TextDocument
from rag_modules.retrieval import HybridRetrievalService
from rag_modules.retrieval.hybrid_components import HybridRetrievalComponents
from tests.configuration_test_helpers import build_test_config


class _FakeRuntime:
    def __init__(self) -> None:
        self.driver = "driver"
        self.bm25 = "bm25"
        self.bm25_corpus_docs = []
        self.graph_indexed = True
        self.constraint_matcher = "matcher"
        self.vector_retriever = "vector"
        self.dual_level_service = "dual"
        self.calls = []

    def initialize(self, chunks):
        self.calls.append(("initialize", list(chunks)))

    def enrich_to_parent_documents(self, docs, top_n=None):
        self.calls.append(("enrich_to_parent_documents", top_n))
        return list(docs)

    def enrich_to_parent_evidence_documents(self, docs, top_n=None):
        self.calls.append(("enrich_to_parent_evidence_documents", top_n))
        return list(docs)

    def close(self):
        self.calls.append(("close", None))


class _FakeSearchService:
    def __init__(self) -> None:
        self.calls = []

    def dual_level_candidates(self, request):
        self.calls.append(("dual_level_candidates", request))
        return [EvidenceDocument(content="dual", entity_name="dual")]

    def vector_candidates(self, request):
        self.calls.append(("vector_candidates", request))
        return [EvidenceDocument(content="vector", entity_name="vector")]

    def bm25_candidates(self, request):
        self.calls.append(("bm25_candidates", request))
        return [EvidenceDocument(content="bm25", entity_name="bm25")]

    def constraint_candidates(self, request):
        self.calls.append(("constraint_candidates", request))
        return [EvidenceDocument(content="constraint", entity_name="constraint")]

    def hybrid_evidence_search(self, request):
        self.calls.append(("hybrid_evidence_search", request))
        return HybridRetrievalOutcome(
            documents=[EvidenceDocument(content="hybrid", entity_name="hybrid")],
            candidate_counts={"vector": 1},
        )


class _FakeKeywordExtractor:
    def extract(self, query):
        return [query], [f"topic::{query}"]


class _FakeComponentFactory:
    def __init__(self, runtime, search_service, keyword_extractor) -> None:
        self.components = HybridRetrievalComponents(
            runtime=runtime,
            search_service=search_service,
            keyword_extractor=keyword_extractor,
        )

    def build(self, **_kwargs):
        return self.components


class HybridRetrievalServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.runtime = _FakeRuntime()
        self.search_service = _FakeSearchService()
        factory = _FakeComponentFactory(
            self.runtime,
            self.search_service,
            _FakeKeywordExtractor(),
        )
        self.service = HybridRetrievalService(
            config=build_test_config(),
            milvus_module=SimpleNamespace(),
            data_module=SimpleNamespace(),
            llm_client=SimpleNamespace(),
            component_factory=factory,
        )

    def test_hybrid_evidence_search_uses_search_service_directly(self) -> None:
        request = RetrievalRequest.from_inputs(query="mapo tofu", top_k=3, candidate_k=3)

        outcome = self.service.hybrid_evidence_search(request)
        documents = self.service.hybrid_search(request)

        self.assertEqual([doc.entity_name for doc in outcome.documents], ["hybrid"])
        self.assertEqual([doc.entity_name for doc in documents], ["hybrid"])
        self.assertEqual(self.search_service.calls[-1][0], "hybrid_evidence_search")
        with self.assertRaises(AttributeError):
            _ = self.service.executor

    def test_search_entrypoints_build_evidence_native_requests(self) -> None:
        self.service.dual_level_retrieval("tofu", top_k=2)
        self.service.vector_search_enhanced("tofu", top_k=3)
        self.service.bm25_search("tofu", top_k=4)
        constraint_docs = self.service.constraint_search(
            QueryConstraints(temporal_filters={"max_duration_minutes": 30}),
            top_k=5,
        )

        self.assertEqual(
            [name for name, _request in self.search_service.calls],
            [
                "dual_level_candidates",
                "vector_candidates",
                "bm25_candidates",
                "constraint_candidates",
            ],
        )
        self.assertEqual(
            [request.candidate_k for _name, request in self.search_service.calls],
            [2, 3, 4, 5],
        )
        self.assertEqual(constraint_docs[0].entity_name, "constraint")

    def test_lifecycle_keyword_and_parent_operations_use_concrete_components(self) -> None:
        chunk = TextDocument(content="child")
        evidence = EvidenceDocument(content="evidence")
        request = RetrievalRequest.from_inputs(query="tofu")

        self.service.initialize([chunk])
        parent_docs = self.service.enrich_to_parent_documents([chunk], top_n=1)
        parent_evidence = self.service.enrich_to_parent_evidence_documents(
            request,
            [evidence],
            top_n=1,
        )
        self.service.close()

        self.assertEqual(self.service.bm25, "bm25")
        self.assertEqual(self.service.bm25_corpus_docs, [])
        self.assertTrue(self.service.graph_indexed)
        self.assertEqual(self.service.constraint_matcher, "matcher")
        self.assertEqual(self.service.vector_retriever, "vector")
        self.assertEqual(self.service.dual_level_service, "dual")
        self.assertEqual(self.service.extract_query_keywords("tofu"), (["tofu"], ["topic::tofu"]))
        self.assertEqual(parent_docs, [chunk])
        self.assertEqual(parent_evidence, [evidence])
        self.assertEqual(
            [call[0] for call in self.runtime.calls],
            [
                "initialize",
                "enrich_to_parent_documents",
                "enrich_to_parent_evidence_documents",
                "close",
            ],
        )

    def test_parent_evidence_enrichment_honors_request_cancellation(self) -> None:
        control = RequestControl.for_timeout(5.0, scope="hybrid-parent-enrichment")
        control.cancel("client_disconnect")
        request = RetrievalRequest.from_inputs(query="tofu", control=control)

        with self.assertRaises(RequestCancelled):
            self.service.enrich_to_parent_evidence_documents(
                request,
                [EvidenceDocument(content="evidence")],
            )

        self.assertEqual(self.runtime.calls, [])


if __name__ == "__main__":
    unittest.main()
