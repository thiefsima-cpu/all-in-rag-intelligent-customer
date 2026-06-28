from __future__ import annotations

import unittest
from types import SimpleNamespace

from rag_modules.contracts import EvidenceDocument
from rag_modules.infra.milvus.module import MilvusIndexConstructionModule
from rag_modules.retrieval.post_processor import (
    RetrievalPostProcessContext,
    RetrievalPostProcessor,
)
from rag_modules.retrieval.runtime_profile import RetrievalPostProcessSettings


class _FakeEmbeddingClient:
    def __init__(self) -> None:
        self.document_calls: list[list[str]] = []
        self.query_calls: list[str] = []

    def embed_query(self, text: str) -> list[float]:
        self.query_calls.append(text)
        return [1.0, 0.0]

    def embed_documents(self, texts) -> list[list[float]]:
        self.document_calls.append([str(text) for text in texts])
        return [[float(index), 0.0] for index, _text in enumerate(texts)]


class _FakeRerankClient:
    def __init__(self, order: list[int]) -> None:
        self.order = order
        self.calls: list[dict[str, object]] = []

    def rerank(self, query: str, documents, top_n: int) -> list[int]:
        self.calls.append(
            {
                "query": query,
                "documents": list(documents),
                "top_n": top_n,
            }
        )
        return list(self.order)


class _MilvusModuleWithoutNetwork(MilvusIndexConstructionModule):
    def _setup_client(self):
        self.client = SimpleNamespace()


class ModelClientPortTests(unittest.TestCase):
    def test_milvus_module_accepts_injected_embedding_port(self) -> None:
        embedding_client = _FakeEmbeddingClient()

        module = _MilvusModuleWithoutNetwork(
            collection_name="recipes",
            dimension=2,
            embedding_client=embedding_client,
        )

        self.assertIs(module.embeddings, embedding_client)

    def test_retrieval_post_processor_accepts_injected_rerank_port(self) -> None:
        rerank_client = _FakeRerankClient(order=[1, 0])
        processor = RetrievalPostProcessor(
            settings=RetrievalPostProcessSettings(
                enable_rerank=True,
                rerank_model="fake-reranker",
            ),
            rerank_client=rerank_client,
        )
        docs = [
            EvidenceDocument(content="first", recipe_name="first"),
            EvidenceDocument(content="second", recipe_name="second"),
        ]

        result = processor.post_process(
            docs,
            top_k=2,
            context=RetrievalPostProcessContext(
                query="which one",
                strategy="hybrid_traditional",
                query_complexity=0.1,
                relationship_intensity=0.1,
                route_confidence=0.9,
            ),
        )

        self.assertEqual([doc.recipe_name for doc in result], ["second", "first"])
        self.assertEqual(rerank_client.calls[0]["query"], "which one")


if __name__ == "__main__":
    unittest.main()
