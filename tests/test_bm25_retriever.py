from collections.abc import Sequence
from unittest.mock import Mock, patch

import pytest

from rag_modules.kernel.documents import TextDocument
from rag_modules.retrieval.adapters import bm25_retriever as module
from rag_modules.retrieval.adapters.bm25_retriever import BM25Retriever


class _FakeBM25:
    scores: Sequence[float] = (0.2, 0.0, 0.9)

    def __init__(self, corpus: list[list[str]]) -> None:
        self.corpus = corpus

    def get_scores(self, query: list[str]) -> Sequence[float]:
        assert query == ["tofu"]
        return self.scores


class _NonPositiveBM25(_FakeBM25):
    scores = (0.0, -0.1)


class _FailingScoreBM25(_FakeBM25):
    def get_scores(self, query: list[str]) -> Sequence[float]:
        del query
        raise RuntimeError("scoring failed")


def test_custom_dictionary_is_optional_and_loaded_once(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(module, "_CUSTOM_DICT_LOADED", False)
    load = Mock()
    monkeypatch.setattr(module.jieba, "load_userdict", load)
    missing = tmp_path / "missing.txt"

    module.load_custom_dict(str(missing))
    module.load_custom_dict(str(missing))

    load.assert_not_called()

    dictionary = tmp_path / "dict.txt"
    dictionary.write_text("tofu 10", encoding="utf-8")
    monkeypatch.setattr(module, "_CUSTOM_DICT_LOADED", False)

    module.load_custom_dict(str(dictionary))
    module.load_custom_dict(str(dictionary))

    load.assert_called_once_with(str(dictionary))


def test_custom_dictionary_propagates_loader_failure_and_remains_retryable(
    tmp_path, monkeypatch
) -> None:
    dictionary = tmp_path / "dict.txt"
    dictionary.write_text("tofu 10", encoding="utf-8")
    monkeypatch.setattr(module, "_CUSTOM_DICT_LOADED", False)
    monkeypatch.setattr(
        module.jieba,
        "load_userdict",
        Mock(side_effect=RuntimeError("dictionary failed")),
    )

    with pytest.raises(RuntimeError, match="dictionary failed"):
        module.load_custom_dict(str(dictionary))

    assert module._CUSTOM_DICT_LOADED is False


def test_tokenize_filters_blank_stopword_and_space_tokens() -> None:
    with patch.object(module.jieba, "lcut", return_value=["tofu", "的", " ", "", "soup"]):
        assert module.tokenize_chinese("query") == ["tofu", "soup"]

    assert module.tokenize_chinese("") == []


def test_empty_corpus_is_not_ready_and_returns_no_results() -> None:
    retriever = BM25Retriever()

    assert retriever.corpus_docs == []
    assert retriever.ready is False
    assert retriever.search("tofu") == []


def test_build_and_search_order_positive_scores_and_normalize_metadata(monkeypatch) -> None:
    load = Mock()
    monkeypatch.setattr(module, "BM25Okapi", _FakeBM25)
    monkeypatch.setattr(module, "load_custom_dict", load)
    monkeypatch.setattr(module, "tokenize_chinese", lambda text: ["tofu"] if text else [])
    retriever = BM25Retriever()
    chunks = [
        TextDocument(content="a", metadata={"name": "A", "node_id": "a"}),
        TextDocument(content="b", metadata={"recipe_name": "B", "recipe_id": "b"}),
        TextDocument(content="c", metadata={"recipe_name": "C", "parent_id": "c"}),
    ]

    assert retriever.search("tofu") == []
    retriever.build(chunks)
    documents = retriever.search("tofu", top_k=3)

    load.assert_called_once_with()
    assert retriever.ready is True
    assert [doc.content for doc in documents] == ["c", "a"]
    assert [doc.recipe_name for doc in documents] == ["C", "A"]
    assert [doc.node_id for doc in documents] == ["c", "a"]
    assert [doc.recipe_id for doc in documents] == ["c", "a"]
    assert [doc.score for doc in documents] == [0.9, 0.2]
    assert documents[0].search_method == "bm25"
    assert documents[0].search_type == "bm25"
    assert documents[0].retrieval_level == "chunk"
    assert documents[0].source == "bm25"
    assert documents[0].metadata == {
        "recipe_name": "C",
        "parent_id": "c",
        "search_method": "bm25",
        "search_type": "bm25",
        "bm25_score": 0.9,
        "score": 0.9,
        "source": "bm25",
    }
    assert "source" not in chunks[2].metadata
    assert retriever.search("") == []


def test_search_returns_empty_when_all_scores_are_non_positive(monkeypatch) -> None:
    monkeypatch.setattr(module, "tokenize_chinese", lambda _text: ["tofu"])
    retriever = BM25Retriever()
    retriever.bm25 = _NonPositiveBM25([["tofu"], ["soup"]])
    retriever.corpus_docs = [TextDocument("tofu"), TextDocument("soup")]

    assert retriever.search("tofu", top_k=2) == []


def test_build_propagates_setup_failure_without_replacing_corpus(monkeypatch) -> None:
    retriever = BM25Retriever()
    existing = TextDocument("existing")
    retriever.corpus_docs = [existing]
    monkeypatch.setattr(
        module,
        "load_custom_dict",
        Mock(side_effect=RuntimeError("setup failed")),
    )

    with pytest.raises(RuntimeError, match="setup failed"):
        retriever.build([TextDocument("replacement")])

    assert retriever.corpus_docs == [existing]
    assert retriever.bm25 is None


def test_search_propagates_scoring_dependency_failure(monkeypatch) -> None:
    monkeypatch.setattr(module, "tokenize_chinese", lambda _text: ["tofu"])
    retriever = BM25Retriever()
    retriever.bm25 = _FailingScoreBM25([["tofu"]])
    retriever.corpus_docs = [TextDocument("tofu")]

    with pytest.raises(RuntimeError, match="scoring failed"):
        retriever.search("tofu")


def test_cache_round_trip_preserves_duplicate_documents_and_metadata(monkeypatch) -> None:
    monkeypatch.setattr(module, "BM25Okapi", _FakeBM25)
    monkeypatch.setattr(module, "tokenize_chinese", lambda text: text.split())
    retriever = BM25Retriever()
    retriever.corpus_docs = [
        TextDocument(content="tofu soup", metadata={"node_id": "r1", "rank": 1}),
        TextDocument(content="tofu soup", metadata={"node_id": "r2", "rank": 2}),
    ]

    payload = retriever.to_cache_dict()
    restored = BM25Retriever()

    assert payload["tokenized_corpus"] == [["tofu", "soup"], ["tofu", "soup"]]
    assert restored.from_cache_dict(payload) is True
    assert restored.corpus_docs == retriever.corpus_docs
    assert restored.ready is True


@pytest.mark.parametrize(
    "payload",
    [
        {"tokenized_corpus": "bad", "corpus_docs": []},
        {"tokenized_corpus": [], "corpus_docs": "bad"},
        {"tokenized_corpus": [[]], "corpus_docs": []},
        {"tokenized_corpus": [], "corpus_docs": []},
        {"tokenized_corpus": ["bad"], "corpus_docs": [{"page_content": "x"}]},
        {"tokenized_corpus": [[]], "corpus_docs": [{}]},
    ],
    ids=[
        "token-corpus-not-list",
        "document-corpus-not-list",
        "length-mismatch",
        "empty-corpus",
        "token-row-not-list",
        "document-missing-content",
    ],
)
def test_cache_rejects_structurally_invalid_payloads(payload: dict) -> None:
    assert BM25Retriever().from_cache_dict(payload) is False


def test_cache_restore_preserves_valid_state_when_token_row_is_invalid() -> None:
    retriever = BM25Retriever()
    original_docs = [TextDocument("existing", {"node_id": "existing"})]
    original_index = _FakeBM25([["existing"]])
    retriever.corpus_docs = original_docs
    retriever.bm25 = original_index

    restored = retriever.from_cache_dict(
        {
            "tokenized_corpus": ["not-a-token-row"],
            "corpus_docs": [{"page_content": "replacement", "metadata": {"node_id": "new"}}],
        }
    )

    assert restored is False
    assert retriever.corpus_docs is original_docs
    assert retriever.bm25 is original_index


def test_cache_restore_preserves_valid_state_when_index_construction_fails(
    monkeypatch,
) -> None:
    def _reject_index(_tokens: list[list[str]]) -> None:
        raise ValueError("invalid index data")

    monkeypatch.setattr(module, "BM25Okapi", _reject_index)
    retriever = BM25Retriever()
    original_docs = [TextDocument("existing", {"node_id": "existing"})]
    original_index = _FakeBM25([["existing"]])
    retriever.corpus_docs = original_docs
    retriever.bm25 = original_index

    restored = retriever.from_cache_dict(
        {
            "tokenized_corpus": [["replacement"]],
            "corpus_docs": [{"page_content": "replacement", "metadata": {"node_id": "new"}}],
        }
    )

    assert restored is False
    assert retriever.corpus_docs is original_docs
    assert retriever.bm25 is original_index


def test_cache_restore_degrades_when_index_dependency_rejects_payload(monkeypatch) -> None:
    def _reject_index(_tokens: list[list[str]]) -> None:
        raise ValueError("invalid index data")

    monkeypatch.setattr(module, "BM25Okapi", _reject_index)
    retriever = BM25Retriever()

    restored = retriever.from_cache_dict(
        {
            "tokenized_corpus": [["tofu"]],
            "corpus_docs": [{"page_content": "tofu", "metadata": {"node_id": "r1"}}],
        }
    )

    assert restored is False
    assert retriever.bm25 is None
