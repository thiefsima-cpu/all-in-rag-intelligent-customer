from __future__ import annotations

import unittest
from types import SimpleNamespace

from langchain_core.documents import Document

from rag_modules.configuration.testing import build_test_config
from rag_modules.retrieval.contracts import EvidenceDocument
from rag_modules.retrieval.hybrid_index_service import HybridIndexArtifacts
from rag_modules.retrieval.hybrid_runtime import HybridRetrievalRuntime


class _StubVectorRetriever:
    def __init__(self) -> None:
        self.calls = []

    def search(self, query, *, top_k):
        self.calls.append((query, top_k))
        return [EvidenceDocument(content="vector", recipe_name=query)]


class _StubDualLevelService:
    def __init__(self) -> None:
        self.search_calls = []

    def search(self, request):
        self.search_calls.append(request.query)
        return [EvidenceDocument(content="dual", recipe_name=request.query)]

    def entity_level_retrieval(self, entity_keywords, top_k=5):
        return [
            EvidenceDocument(content="entity", recipe_name="|".join(entity_keywords), score=0.9)
        ]

    def topic_level_retrieval(self, topic_keywords, top_k=5):
        return [EvidenceDocument(content="topic", recipe_name="|".join(topic_keywords), score=0.8)]


class _StubAdapterFactory:
    def __init__(self) -> None:
        self.vector = _StubVectorRetriever()
        self.dual = _StubDualLevelService()
        self.vector_calls = []
        self.dual_calls = []

    def create_vector_retriever(self, *, milvus_module, driver, database):
        self.vector_calls.append(
            {"milvus_module": milvus_module, "driver": driver, "database": database}
        )
        return self.vector

    def create_dual_level_retriever(
        self,
        *,
        graph_indexing,
        graph_kv_retriever,
        keyword_extractor,
        driver,
        database,
    ):
        self.dual_calls.append(
            {
                "graph_indexing": graph_indexing,
                "graph_kv_retriever": graph_kv_retriever,
                "keyword_extractor": keyword_extractor,
                "driver": driver,
                "database": database,
            }
        )
        return self.dual


class _StubDriverService:
    def __init__(self) -> None:
        self.ensure_calls = 0
        self.close_calls = 0

    def ensure_driver(self, state):
        self.ensure_calls += 1
        state.driver = "driver"
        state.owns_driver = True
        return state.driver

    def close(self, state):
        self.close_calls += 1
        state.driver = None


class _StubParentDocumentService:
    def __init__(self) -> None:
        self.apply_calls = []
        self.build_calls = 0
        self.attach_evidence_calls = []

    def apply_parent_doc_map(self, state, parent_doc_map):
        state.parent_doc_map = dict(parent_doc_map or {})
        self.apply_calls.append(dict(parent_doc_map or {}))
        return state.parent_doc_map

    def build_parent_doc_map(self, state):
        self.build_calls += 1
        state.parent_doc_map = {"parent": Document(page_content="doc")}
        return state.parent_doc_map

    def attach_documents(self, state, docs, *, top_n=None):
        del state
        return list(docs)

    def enrich_documents(self, state, docs, *, top_n=None):
        del state, top_n
        return list(docs)

    def attach_evidence_documents(self, state, docs, *, top_n=None):
        del state
        self.attach_evidence_calls.append(top_n)
        return list(docs)

    def enrich_evidence_documents(self, state, docs, *, top_n=None):
        del state, top_n
        return list(docs)


class _StubIndexService:
    def __init__(self, *, artifacts=None) -> None:
        self.artifacts = artifacts or HybridIndexArtifacts()
        self.initialize_calls = []
        self.restore_calls = []
        self.graph_indexed = False

    def initialize(self, chunks, driver):
        self.initialize_calls.append({"chunks": list(chunks), "driver": driver})
        return self.artifacts

    def restore_bm25_retriever(self, payload):
        self.restore_calls.append(dict(payload))

    def _build_graph_index(self, driver):
        del driver
        self.graph_indexed = True

    def _build_parent_doc_map(self):
        return {"parent": Document(page_content="doc")}


class _StubBm25Retriever:
    def __init__(self, *, ready=False) -> None:
        self.ready = ready
        self.bm25 = "bm25" if ready else None
        self.corpus_docs = [Document(page_content="cached")] if ready else []
        self.calls = []

    def search(self, query, *, top_k):
        self.calls.append((query, top_k))
        return [EvidenceDocument(content="bm25", recipe_name=query)]

    def build(self, chunks):
        self.calls.append(("build", list(chunks)))
        self.ready = True
        self.bm25 = "rebuilt-bm25"
        self.corpus_docs = list(chunks)


class HybridRetrievalRuntimeTests(unittest.TestCase):
    def _build_runtime(
        self,
        *,
        index_service,
        bm25_retriever,
        adapter_factory=None,
        driver_service=None,
        parent_documents=None,
    ) -> HybridRetrievalRuntime:
        config = build_test_config({"storage": {"neo4j_database": "recipes"}})
        return HybridRetrievalRuntime(
            config=config,
            milvus_module=SimpleNamespace(name="milvus"),
            neo4j_manager=None,
            database="recipes",
            graph_indexing=SimpleNamespace(name="graph-index"),
            graph_kv_retriever=SimpleNamespace(name="graph-kv"),
            keyword_extractor=SimpleNamespace(name="keywords"),
            index_service=index_service,
            bm25_retriever=bm25_retriever,
            parent_enricher=SimpleNamespace(),
            adapter_factory=adapter_factory,
            driver_service=driver_service,
            parent_document_service=parent_documents,
        )

    def test_initialize_builds_driver_adapters_and_applies_artifacts(self) -> None:
        parent_doc = Document(page_content="parent")
        artifacts = HybridIndexArtifacts(
            bm25="bm25-cache",
            bm25_corpus_docs=[parent_doc],
            graph_indexed=True,
            parent_doc_map={"p": parent_doc},
            recipe_matcher="matcher",
        )
        adapter_factory = _StubAdapterFactory()
        driver_service = _StubDriverService()
        parent_documents = _StubParentDocumentService()
        index_service = _StubIndexService(artifacts=artifacts)
        runtime = self._build_runtime(
            index_service=index_service,
            bm25_retriever=_StubBm25Retriever(ready=True),
            adapter_factory=adapter_factory,
            driver_service=driver_service,
            parent_documents=parent_documents,
        )

        runtime.initialize([Document(page_content="chunk")])

        self.assertEqual(driver_service.ensure_calls, 1)
        self.assertEqual(index_service.initialize_calls[0]["driver"], "driver")
        self.assertEqual(adapter_factory.vector_calls[0]["database"], "recipes")
        self.assertEqual(adapter_factory.dual_calls[0]["driver"], "driver")
        self.assertEqual(runtime.bm25, "bm25-cache")
        self.assertTrue(runtime.graph_indexed)
        self.assertEqual(runtime.recipe_matcher, "matcher")
        self.assertEqual(parent_documents.apply_calls[0], {"p": parent_doc})

    def test_bm25_candidates_rebuild_from_data_only_cached_corpus(self) -> None:
        bm25_retriever = _StubBm25Retriever(ready=False)
        index_service = _StubIndexService()
        runtime = self._build_runtime(
            index_service=index_service,
            bm25_retriever=bm25_retriever,
            adapter_factory=_StubAdapterFactory(),
            driver_service=_StubDriverService(),
            parent_documents=_StubParentDocumentService(),
        )
        runtime.state.bm25 = "cached-bm25"
        runtime.state.bm25_corpus_docs = [Document(page_content="cached-doc")]

        docs = runtime.bm25_candidates("spicy tofu", top_k=4)

        self.assertEqual(docs[0].recipe_name, "spicy tofu")
        self.assertEqual(bm25_retriever.calls[0][0], "build")
        self.assertEqual(bm25_retriever.calls[1], ("spicy tofu", 4))

    def test_sync_legacy_bm25_fields_refreshes_runtime_state_from_retriever(self) -> None:
        cached_doc = Document(page_content="cached")
        bm25_retriever = _StubBm25Retriever(ready=True)
        bm25_retriever.bm25 = "restored-bm25"
        bm25_retriever.corpus_docs = [cached_doc]
        runtime = self._build_runtime(
            index_service=_StubIndexService(),
            bm25_retriever=bm25_retriever,
            adapter_factory=_StubAdapterFactory(),
            driver_service=_StubDriverService(),
            parent_documents=_StubParentDocumentService(),
        )
        runtime.state.bm25 = "stale-bm25"
        runtime.state.bm25_corpus_docs = []

        runtime.sync_legacy_bm25_fields()

        self.assertEqual(runtime.bm25, "restored-bm25")
        self.assertEqual(runtime.bm25_corpus_docs, [cached_doc])

    def test_attach_parent_evidence_documents_delegate_to_parent_document_service(self) -> None:
        parent_documents = _StubParentDocumentService()
        runtime = self._build_runtime(
            index_service=_StubIndexService(),
            bm25_retriever=_StubBm25Retriever(ready=True),
            adapter_factory=_StubAdapterFactory(),
            driver_service=_StubDriverService(),
            parent_documents=parent_documents,
        )
        docs = [EvidenceDocument(content="doc", recipe_name="recipe")]

        result = runtime.attach_parent_evidence_documents(docs, top_n=2)

        self.assertEqual(result, docs)
        self.assertEqual(parent_documents.attach_evidence_calls, [2])


if __name__ == "__main__":
    unittest.main()
