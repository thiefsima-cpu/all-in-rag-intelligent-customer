from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from rag_modules.contracts import RetrievalRequest
from rag_modules.contracts.query_constraints import QueryConstraints
from rag_modules.retrieval.adapters.constraint_retriever import ConstraintRetriever


def test_constraint_search_returns_empty_without_active_constraints_or_matcher() -> None:
    matcher = Mock()

    assert ConstraintRetriever(lambda: matcher).search(RetrievalRequest(query="tofu")) == []
    matcher.filter_and_rank.assert_not_called()

    request = RetrievalRequest(
        query="tofu",
        constraints=QueryConstraints(entity_terms=["tofu"]),
    )
    assert ConstraintRetriever(lambda: None).search(request) == []


def test_constraint_search_converts_and_annotates_ranked_pages() -> None:
    matcher = Mock()
    matcher.filter_and_rank.return_value = [
        SimpleNamespace(
            page_content="recipe",
            metadata={"node_id": "r1", "constraint_score": 0.9, "source": "fixture"},
        )
    ]
    request = RetrievalRequest(
        query="tofu",
        candidate_k=7,
        constraints=QueryConstraints(entity_terms=["tofu"]),
    )

    documents = ConstraintRetriever(lambda: matcher).search(request)

    matcher.filter_and_rank.assert_called_once_with(
        constraints=request.constraints.to_dict(),
        min_score=0.0,
        limit=7,
    )
    assert len(documents) == 1
    assert documents[0].content == "recipe"
    assert documents[0].node_id == "r1"
    assert documents[0].score == pytest.approx(0.9)
    assert documents[0].search_method == "constraints"
    assert documents[0].search_type == "constraint_domain"
    assert documents[0].metadata == {
        "node_id": "r1",
        "constraint_score": 0.9,
        "source": "fixture",
        "search_method": "constraints",
        "search_type": "constraint_domain",
    }


def test_constraint_search_propagates_matcher_failure() -> None:
    matcher = Mock()
    matcher.filter_and_rank.side_effect = RuntimeError("constraint index unavailable")
    request = RetrievalRequest(
        query="tofu",
        constraints=QueryConstraints(entity_terms=["tofu"]),
    )

    with pytest.raises(RuntimeError, match="constraint index unavailable"):
        ConstraintRetriever(lambda: matcher).search(request)
