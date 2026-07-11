from __future__ import annotations

from typing import Any

from rag_modules.infra.providers.dashscope import DashScopeRerankClient


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
        return None


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
