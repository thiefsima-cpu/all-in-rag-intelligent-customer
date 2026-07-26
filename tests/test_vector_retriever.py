from __future__ import annotations

from rag_modules.contracts import RetrievalRequest
from rag_modules.retrieval.adapters.vector_retriever import VectorRetriever


class _Milvus:
    def __init__(self, results=None, error: Exception | None = None) -> None:
        self.results = list(results or [])
        self.error = error
        self.domain_name = "recipe"

    def similarity_search(self, request):
        if self.error:
            raise self.error
        return list(self.results)


class _Session:
    def __init__(self, records=None, error: Exception | None = None) -> None:
        self.records = list(records or [])
        self.error = error
        self.calls = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return None

    def run(self, query, parameters, **kwargs):
        self.calls.append((parameters, kwargs))
        if self.error:
            raise self.error
        return self.records


class _Driver:
    def __init__(self, session: _Session) -> None:
        self.session_obj = session

    def session(self, **kwargs):
        return self.session_obj


class _Control:
    def __init__(self) -> None:
        self.checks = 0

    def raise_if_cancelled(self) -> None:
        self.checks += 1

    def remaining_seconds(self) -> float:
        return 2.5


def test_search_enriches_neighbors_coerces_metadata_and_limits_candidates() -> None:
    session = _Session([{"nid": "r1", "names": ["Pepper", "", "Tofu", "Sauce", "Oil"]}])
    retriever = VectorRetriever(
        _Milvus(
            [
                {
                    "text": "chunk",
                    "score": "0.8",
                    "metadata": {"node_id": "r1", "name": "Mapo tofu"},
                },
                {"text": "second", "score": "bad", "metadata": "invalid"},
            ]
        ),
        _Driver(session),
    )
    control = _Control()
    request = RetrievalRequest.from_inputs(query="tofu", top_k=1, candidate_k=1, control=control)

    [document] = retriever.search(request)

    assert document.node_id == "r1"
    assert document.entity_name == "Mapo tofu"
    assert document.score == 0.8
    assert all(name in document.content for name in ("Pepper", "Tofu", "Sauce"))
    assert session.calls[0][1]["timeout"] == 2.5
    assert session.calls[0][0]["domain_name"] == "recipe"
    assert control.checks >= 3


def test_search_coerces_invalid_result_fields_without_node_ids() -> None:
    retriever = VectorRetriever(
        _Milvus([{"text": None, "score": "bad", "metadata": {"entity_type": "Recipe"}}])
    )

    [document] = retriever.search(RetrievalRequest.from_inputs(query="tofu"))

    assert document.content == ""
    assert document.score == 0.0
    assert document.node_type == "Recipe"


def test_search_returns_empty_for_provider_failure_or_no_results() -> None:
    request = RetrievalRequest.from_inputs(query="tofu")
    assert VectorRetriever(_Milvus(error=RuntimeError("down"))).search(request) == []
    assert VectorRetriever(_Milvus()).search(request) == []


def test_neighbor_enrichment_is_optional_and_degrades_query_failure() -> None:
    request = RetrievalRequest.from_inputs(query="tofu")
    result = [{"text": "chunk", "metadata": {"node_id": "r1"}}]

    assert VectorRetriever(_Milvus(result)).search(request)[0].content == "chunk"
    failing = VectorRetriever(_Milvus(result), _Driver(_Session(error=RuntimeError("down"))))
    assert failing.search(request)[0].content == "chunk"


def test_batch_neighbors_returns_empty_for_missing_driver_or_ids() -> None:
    retriever = VectorRetriever(_Milvus())
    request = RetrievalRequest.from_inputs(query="tofu")

    assert retriever._batch_get_neighbors(request, []) == {}
    assert retriever._batch_get_neighbors(request, ["r1"]) == {}
