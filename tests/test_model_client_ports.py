from __future__ import annotations

import inspect
import unittest
from pathlib import Path
from types import SimpleNamespace

from rag_modules.configuration.testing import build_test_config
from rag_modules.contracts import EvidenceDocument, RequestControl, RetrievalRequest
from rag_modules.infra.milvus.module import MilvusIndexConstructionModule
from rag_modules.retrieval.post_processor import (
    RetrievalPostProcessContext,
    RetrievalPostProcessor,
)
from rag_modules.retrieval.runtime_profile import RetrievalRuntimeProfileFactory


class _FakeEmbeddingClient:
    def __init__(self) -> None:
        self.document_calls: list[list[str]] = []
        self.query_calls: list[str] = []

    def embed_query(self, text: str, *, timeout_seconds=None) -> list[float]:
        self.query_calls.append(text)
        return [1.0, 0.0]

    def embed_documents(self, texts, *, timeout_seconds=None) -> list[list[float]]:
        self.document_calls.append([str(text) for text in texts])
        return [[float(index), 0.0] for index, _text in enumerate(texts)]


class _FakeRerankClient:
    def __init__(self, order: list[int]) -> None:
        self.order = order
        self.calls: list[dict[str, object]] = []

    def rerank(
        self, query: str, documents, top_n: int, *, control=None, timeout_seconds=None
    ) -> list[int]:
        self.calls.append(
            {
                "query": query,
                "documents": list(documents),
                "top_n": top_n,
                "control": control,
                "timeout_seconds": timeout_seconds,
            }
        )
        return list(self.order)


class _FakeMilvusSearchClient:
    def __init__(self) -> None:
        self.search_calls = []

    def search(self, **kwargs):
        self.search_calls.append(kwargs)
        return [[]]


class _TimeoutEmbeddingClient(_FakeEmbeddingClient):
    def __init__(self) -> None:
        super().__init__()
        self.timeouts = []

    def embed_query(self, text: str, *, timeout_seconds=None) -> list[float]:
        self.timeouts.append(timeout_seconds)
        return super().embed_query(text, timeout_seconds=timeout_seconds)


class _MilvusModuleWithoutNetwork(MilvusIndexConstructionModule):
    def _setup_client(self):
        self.client = SimpleNamespace()


class ModelClientPortTests(unittest.TestCase):
    def setUp(self) -> None:
        config = build_test_config(
            {"models": {"enable_rerank": True, "rerank_model": "fake-reranker"}}
        )
        self.postprocess_settings = RetrievalRuntimeProfileFactory().build(config).postprocess

    def test_milvus_module_accepts_injected_embedding_port(self) -> None:
        embedding_client = _FakeEmbeddingClient()

        module = _MilvusModuleWithoutNetwork(
            collection_name="recipes",
            dimension=2,
            embedding_client=embedding_client,
        )

        self.assertIs(module.embeddings, embedding_client)

    def test_dashscope_is_owned_by_infra_provider_package(self) -> None:
        from rag_modules.infra.providers.dashscope import (
            DashScopeEmbeddingClient,
            DashScopeRerankClient,
        )

        self.assertTrue(
            DashScopeEmbeddingClient.__module__.startswith("rag_modules.infra.providers.dashscope")
        )
        self.assertTrue(
            DashScopeRerankClient.__module__.startswith("rag_modules.infra.providers.dashscope")
        )
        self.assertFalse(Path("rag_modules/dashscope_clients.py").exists())

    def test_milvus_requires_an_embedding_port(self) -> None:
        parameter = inspect.signature(MilvusIndexConstructionModule.__init__).parameters[
            "embedding_client"
        ]
        self.assertIs(parameter.default, inspect.Parameter.empty)

    def test_milvus_does_not_import_dashscope(self) -> None:
        violations = []
        for path in Path("rag_modules/infra/milvus").glob("*.py"):
            text = path.read_text(encoding="utf-8-sig")
            if "dashscope" in text.lower():
                violations.append(str(path))
        self.assertEqual([], violations)

    def test_milvus_does_not_close_injected_embedding_provider(self) -> None:
        class CloseTrackingEmbedding:
            def __init__(self) -> None:
                self.close_calls = 0

            def close(self) -> None:
                self.close_calls += 1

        embedding = CloseTrackingEmbedding()
        module = object.__new__(MilvusIndexConstructionModule)
        module.embedding_client = embedding
        module.embeddings = embedding
        module.client = None

        module.close()

        self.assertEqual(0, embedding.close_calls)

    def test_retrieval_post_processor_accepts_injected_rerank_port(self) -> None:
        rerank_client = _FakeRerankClient(order=[1, 0])
        processor = RetrievalPostProcessor(
            settings=self.postprocess_settings,
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

    def test_retrieval_post_processor_passes_control_timeout_to_reranker(self) -> None:
        control = RequestControl.for_timeout(4.0, scope="post_process")
        rerank_client = _FakeRerankClient(order=[0])
        processor = RetrievalPostProcessor(
            settings=self.postprocess_settings,
            rerank_client=rerank_client,
        )

        processor.post_process(
            [EvidenceDocument(content="first", recipe_name="first")],
            top_k=1,
            context=RetrievalPostProcessContext(
                query="which one",
                strategy="hybrid_traditional",
                query_complexity=0.1,
                relationship_intensity=0.1,
                route_confidence=0.9,
                control=control,
            ),
        )

        self.assertIs(rerank_client.calls[0]["control"], control)
        self.assertGreater(rerank_client.calls[0]["timeout_seconds"], 0)
        self.assertLessEqual(rerank_client.calls[0]["timeout_seconds"], 4.0)

    def test_milvus_similarity_search_uses_request_control_timeout(self) -> None:
        embedding_client = _TimeoutEmbeddingClient()
        module = _MilvusModuleWithoutNetwork(
            collection_name="recipes",
            dimension=2,
            embedding_client=embedding_client,
        )
        module.collection_created = True
        module.client = _FakeMilvusSearchClient()
        control = RequestControl.for_timeout(3.0, scope="vector")
        request = RetrievalRequest.from_inputs(
            query="tofu",
            top_k=2,
            candidate_k=4,
            control=control,
        )

        module.similarity_search(request)

        self.assertGreater(embedding_client.timeouts[0], 0)
        self.assertLessEqual(embedding_client.timeouts[0], 3.0)
        self.assertGreater(module.client.search_calls[0]["timeout"], 0)
        self.assertLessEqual(module.client.search_calls[0]["timeout"], 3.0)


if __name__ == "__main__":
    unittest.main()
