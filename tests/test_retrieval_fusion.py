import pytest

from rag_modules.contracts import EvidenceDocument
from rag_modules.retrieval.fusion import FusionRanker


def _doc(node_id: str, content: str, *, score: float = 0.0) -> EvidenceDocument:
    return EvidenceDocument(
        content=content,
        node_id=node_id,
        score=score,
        metadata={"original": content},
    )


def test_rrf_merge_returns_empty_for_empty_sources_and_non_positive_limit() -> None:
    ranker = FusionRanker()

    assert ranker.rrf_merge([], top_k=5) == []
    assert ranker.rrf_merge([("vector", [_doc("a", "a")])], top_k=0) == []


def test_rrf_merge_deduplicates_per_source_and_preserves_best_ranked_document() -> None:
    vector_a = _doc("a", "vector-a")
    graph_a = _doc("a", "graph-a")
    vector_b = _doc("b", "vector-b")
    graph_b = _doc("b", "graph-b")

    merged = FusionRanker(rrf_k=0).rrf_merge(
        [
            ("vector", [vector_a, vector_b, _doc("a", "late-duplicate")]),
            ("graph", [graph_b, graph_a]),
        ],
        top_k=2,
    )

    assert [doc.node_id for doc in merged] == ["a", "b"]
    assert merged[0].content == "vector-a"
    assert merged[0].metadata["rrf_ranks"] == {"vector": 1, "graph": 2}
    assert merged[0].metadata["rrf_chunk_hits"] == {"vector": 2, "graph": 1}
    assert merged[0].metadata["rrf_sources"] == ["vector", "graph"]
    assert merged[0].metadata["rrf_score"] == pytest.approx(1.5)
    assert merged[0].metadata["final_score"] == pytest.approx(1.5)
    assert merged[0].score == pytest.approx(1.5)
    assert merged[0].metadata["original"] == "vector-a"


def test_rrf_merge_uses_source_order_to_break_equal_rank_document_ties() -> None:
    vector_a = _doc("a", "vector-a", score=0.8)
    graph_a = _doc("a", "graph-a", score=0.9)

    merged = FusionRanker().rrf_merge(
        [("vector", [vector_a]), ("graph", [graph_a])],
        top_k=1,
    )

    assert merged[0].content == "vector-a"
    assert merged[0].metadata["rrf_ranks"] == {"vector": 1, "graph": 1}
    assert merged[0].metadata["rrf_sources"] == ["vector", "graph"]
    assert merged[0].score == pytest.approx(2 / 61)
    assert vector_a.metadata == {"original": "vector-a"}
