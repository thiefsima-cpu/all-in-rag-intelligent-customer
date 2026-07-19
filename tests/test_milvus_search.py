from __future__ import annotations

import pytest

from rag_modules.contracts import RetrievalRequest
from rag_modules.infra.milvus.search import (
    _filter_expression,
    _format_hits,
    _metadata_filter,
    _MilvusSearchOperations,
)


class _Embeddings:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.calls = []

    def embed_query(self, query, *, timeout_seconds=None):
        if self.error:
            raise self.error
        self.calls.append((query, timeout_seconds))
        return [0.1, 0.2]


class _Client:
    def __init__(self, results=None, error: Exception | None = None) -> None:
        self.results = results
        self.error = error
        self.calls = []

    def search(self, **kwargs):
        if self.error:
            raise self.error
        self.calls.append(kwargs)
        return self.results


class _Search(_MilvusSearchOperations):
    def __init__(self, results=None) -> None:
        self.collection_created = True
        self.collection_name = "recipes"
        self.domain_name = "recipe"
        self.vector_search_max_k = 2
        self.vector_search_ef = 1
        self.embeddings = _Embeddings()
        self.client = _Client(results)


class _Control:
    def __init__(self) -> None:
        self.checks = 0

    def raise_if_cancelled(self) -> None:
        self.checks += 1

    def remaining_seconds(self) -> float:
        return 3.0


def _hit() -> dict[str, object]:
    return {
        "id": "c1",
        "distance": 0.8,
        "entity": {
            "text": "chunk",
            "node_id": "r1",
            "recipe_name": "Mapo tofu",
            "node_type": "Recipe",
            "category": "main",
            "cuisine_type": "Sichuan",
            "difficulty": 2,
            "doc_type": "chunk",
            "chunk_id": "c1",
            "parent_id": "r1",
        },
    }


def test_similarity_search_caps_k_filters_metadata_and_formats_hits() -> None:
    search = _Search([[_hit()]])
    control = _Control()
    request = RetrievalRequest.from_inputs(
        query="tofu",
        candidate_k=5,
        control=control,
        metadata={"milvus_filter": {"category": "main", "difficulty": 2}},
    )

    [result] = search.similarity_search(request)

    assert result["text"] == "chunk"
    assert result["score"] == 0.8
    assert result["metadata"]["node_id"] == "r1"
    assert search.client.calls[0]["limit"] == 2
    assert search.client.calls[0]["search_params"]["params"]["ef"] == 2
    assert search.client.calls[0]["filter"] == (
        'category == "main" and difficulty == 2 and domain == "recipe"'
    )
    assert search.client.calls[0]["timeout"] == 3.0
    assert control.checks == 3


def test_search_guards_collection_and_degrades_embedding_or_client_failures() -> None:
    search = _Search([])
    search.collection_created = False
    with pytest.raises(ValueError, match="built or loaded"):
        search.similarity_search(RetrievalRequest.from_inputs(query="x"))

    search.collection_created = True
    search.embeddings = _Embeddings(RuntimeError("embedding down"))
    assert search.similarity_search(RetrievalRequest.from_inputs(query="x")) == []

    search.embeddings = _Embeddings()
    search.client = _Client(error=RuntimeError("search down"))
    assert search.similarity_search(RetrievalRequest.from_inputs(query="x")) == []


def test_filter_helpers_handle_alias_lists_numbers_and_invalid_payloads() -> None:
    assert _metadata_filter({"filters": {"category": ["main", "side"]}}) == {
        "category": ["main", "side"]
    }
    assert _metadata_filter({"filters": "invalid"}) == {}
    assert (
        _filter_expression({"category": ["main", "side"], "difficulty": [1, 2], "ignored": None})
        == 'category in ["main", "side"] and difficulty in [1, 2]'
    )
    assert _format_hits([]) == []
    assert _format_hits(None) == []


def test_similarity_search_always_filters_domain_and_omits_timeout_without_control() -> None:
    search = _Search([[_hit()]])

    [result] = search.similarity_search(RetrievalRequest.from_inputs(query="tofu", candidate_k=1))

    assert result["id"] == "c1"
    assert search.client.calls[0]["filter"] == 'domain == "recipe"'
    assert "timeout" not in search.client.calls[0]


def test_customer_similarity_search_enforces_domain_filter() -> None:
    search = _Search([[_hit()]])
    search.domain_name = "customer_service"
    request = RetrievalRequest.from_inputs(
        query="order",
        metadata={"milvus_filter": {"domain": "recipe", "doc_type": "order"}},
    )

    search.similarity_search(request)

    assert search.client.calls[0]["filter"] == (
        'domain == "customer_service" and doc_type == "order"'
    )
