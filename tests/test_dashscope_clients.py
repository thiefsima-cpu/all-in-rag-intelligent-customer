from __future__ import annotations

from typing import Any

import pytest

from rag_modules.contracts import RequestCancelled, RequestControl
from rag_modules.infra.providers.dashscope import (
    DashScopeEmbeddingClient,
    DashScopeRerankClient,
)


class FakeResponse:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, Any]:
        return self.payload


class FakeSession:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.response = FakeResponse(payload)
        self.posts: list[dict[str, Any]] = []

    def post(self, url: str, **kwargs: Any) -> FakeResponse:
        self.posts.append({"url": url, **kwargs})
        return self.response

    def close(self) -> None:
        self.closed = True


def test_qwen3_rerank_uses_compatible_request_and_response_contract() -> None:
    session = FakeSession(
        {
            "object": "list",
            "results": [
                {"index": 1, "relevance_score": 0.9},
                {"index": 0, "relevance_score": 0.5},
            ],
        }
    )
    client = DashScopeRerankClient(
        api_key="test-key",
        model_name="qwen3-rerank",
        base_url="https://dashscope.aliyuncs.com/compatible-api/v1/reranks",
        session=session,
    )

    order = client.rerank("query", ["first", "second"], top_n=2)

    assert order == [1, 0]
    assert session.posts[0]["json"] == {
        "model": "qwen3-rerank",
        "query": "query",
        "documents": ["first", "second"],
        "top_n": 2,
    }


def test_multimodal_reranker_keeps_legacy_dashscope_contract() -> None:
    session = FakeSession({"output": {"results": [{"index": 0}]}})
    client = DashScopeRerankClient(
        api_key="test-key",
        model_name="qwen3-vl-rerank",
        base_url="https://dashscope.aliyuncs.com/api/v1/services/rerank/text-rerank/text-rerank",
        session=session,
    )

    order = client.rerank("query", ["first"], top_n=1)

    assert order == [0]
    assert session.posts[0]["json"]["input"]["query"] == {"text": "query"}


def test_clients_require_api_keys() -> None:
    with pytest.raises(ValueError):
        DashScopeEmbeddingClient(api_key="", model_name="embed", base_url="https://example")
    with pytest.raises(ValueError):
        DashScopeRerankClient(api_key="", model_name="rerank", base_url="https://example")


def test_embedding_batches_documents_coerces_components_and_forwards_timeouts() -> None:
    session = FakeSession(
        {
            "output": {
                "embeddings": [
                    {"embedding": [1, "2.5"]},
                    {"embedding": [3.0, 4]},
                ]
            }
        }
    )
    client = DashScopeEmbeddingClient(
        api_key="key",
        model_name="embed",
        base_url="https://example/embeddings",
        batch_size=2,
        session=session,
    )

    assert client.embed_documents(["first", None], timeout_seconds=1.5) == [
        [1.0, 2.5],
        [3.0, 4.0],
    ]
    assert session.posts[0]["timeout"] == 1.5
    assert session.posts[0]["json"]["input"]["contents"] == [
        {"text": "first"},
        {"text": ""},
    ]
    client.close()
    assert session.closed is True


def test_embedding_query_and_response_validation_paths() -> None:
    session = FakeSession({"output": {"embeddings": [{"embedding": [0.1]}]}})
    client = DashScopeEmbeddingClient(
        api_key="key", model_name="embed", base_url="https://example", session=session
    )
    assert client.embed_query("query") == [0.1]
    assert session.posts[0]["timeout"] == client.timeout

    client.embed_documents = lambda texts, timeout_seconds=None: []
    assert client.embed_query("empty") == []

    mismatch = DashScopeEmbeddingClient(
        api_key="key",
        model_name="embed",
        base_url="https://example",
        session=FakeSession({"output": {"embeddings": []}}),
    )
    with pytest.raises(ValueError, match="count mismatch"):
        mismatch.embed_documents(["query"])

    missing = DashScopeEmbeddingClient(
        api_key="key",
        model_name="embed",
        base_url="https://example",
        session=FakeSession({"output": {"embeddings": [{}]}}),
    )
    with pytest.raises(ValueError, match="Missing embedding"):
        missing.embed_documents(["query"])

    invalid = DashScopeEmbeddingClient(
        api_key="key",
        model_name="embed",
        base_url="https://example",
        session=FakeSession({"output": {"embeddings": [{"embedding": [{"bad": True}]}]}}),
    )
    with pytest.raises(ValueError, match="Invalid embedding component"):
        invalid.embed_documents(["query"])


def test_rerank_guards_empty_cancelled_and_malformed_results() -> None:
    session = FakeSession({"results": []})
    client = DashScopeRerankClient(
        api_key="key", model_name="qwen3-rerank", base_url="https://example", session=session
    )
    assert client.rerank("query", [], top_n=3) == []

    control = RequestControl.for_timeout(5.0, scope="rerank")
    control.cancel("client_disconnect")
    with pytest.raises(RequestCancelled):
        client.rerank("query", ["doc"], top_n=1, control=control)

    missing_index = DashScopeRerankClient(
        api_key="key",
        model_name="qwen3-rerank",
        base_url="https://example",
        session=FakeSession({"results": [{"score": 0.5}, {"index": "2"}]}),
    )
    assert missing_index.rerank("query", ["a", "b", "c"], top_n=5) == [2]

    invalid = DashScopeRerankClient(
        api_key="key",
        model_name="qwen3-rerank",
        base_url="https://example",
        session=FakeSession({"results": [{"index": {"bad": True}}]}),
    )
    with pytest.raises(ValueError, match="Invalid rerank index"):
        invalid.rerank("query", ["doc"], top_n=1, timeout_seconds=2.0)
    invalid.close()
    assert invalid.session.closed is True
