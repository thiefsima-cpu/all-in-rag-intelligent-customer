from __future__ import annotations

from types import SimpleNamespace

from rag_modules.configuration.testing import build_test_config
from rag_modules.kernel.documents import TextDocument
from rag_modules.retrieval.hybrid_index_service import HybridIndexService
from rag_modules.retrieval.parent_doc_enricher import ParentDocumentEnricher


class _BM25:
    def __init__(self, restore: bool = True) -> None:
        self.restore = restore
        self.bm25 = object()
        self.corpus_docs = [TextDocument(content="cached")]

    def from_cache_dict(self, payload: object) -> bool:
        return self.restore

    def to_cache_dict(self) -> dict[str, object]:
        return {"tokens": [["cached"]]}


class _Session:
    def __init__(self, records: object = (), error: Exception | None = None) -> None:
        self.records = list(records)
        self.error = error

    def __enter__(self) -> _Session:
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        return None

    def run(self, query: str) -> list[object]:
        if self.error:
            raise self.error
        return self.records


class _Driver:
    def __init__(self, session: _Session) -> None:
        self.session_obj = session

    def session(self, **kwargs: object) -> _Session:
        return self.session_obj


def _service(*, restore: bool = True) -> HybridIndexService:
    config = build_test_config()
    data_module = SimpleNamespace(documents=[], recipes=[], ingredients=[], cooking_steps=[])
    graph_indexing = SimpleNamespace(
        from_cache_dict=lambda payload: True,
        to_cache_dict=lambda: {"graph": True},
        create_entity_key_values=lambda *args: None,
        create_relation_key_values=lambda relationships: None,
        deduplicate_entities_and_relations=lambda: None,
        get_statistics=lambda: {},
    )
    return HybridIndexService(
        config=config,
        data_module=data_module,
        graph_indexing=graph_indexing,
        cache_store=SimpleNamespace(load=lambda chunks: None, save=lambda chunks, payload: None),
        bm25_retriever=_BM25(restore=restore),
        parent_enricher=ParentDocumentEnricher(config),
    )


def test_parent_document_cache_round_trip_filters_invalid_items() -> None:
    serialized = HybridIndexService._serialize_parent_documents(
        {"r1": TextDocument(content="parent", metadata={"node_id": "r1", "rank": 1})}
    )

    assert HybridIndexService._deserialize_parent_documents(serialized) == {
        "r1": TextDocument(content="parent", metadata={"node_id": "r1", "rank": 1})
    }
    assert HybridIndexService._deserialize_parent_documents("invalid") == {}
    assert HybridIndexService._deserialize_parent_documents(
        {"bad": "invalid", "r2": {"page_content": "ok", "metadata": "invalid"}}
    ) == {"r2": TextDocument(content="ok", metadata={})}


def test_restore_bm25_requires_mapping_and_successful_retriever_restore() -> None:
    assert _service().restore_bm25_retriever({}) is False
    assert _service().restore_bm25_retriever({"bm25_retriever": "invalid"}) is False
    assert _service(restore=False).restore_bm25_retriever({"bm25_retriever": {}}) is False
    assert _service().restore_bm25_retriever({"bm25_retriever": {}}) is True


def test_extract_relationships_handles_absent_successful_and_failed_driver() -> None:
    service = _service()
    assert service._extract_relationships_from_graph(None) == []

    driver = _Driver(
        _Session(
            [
                {"source_id": 1, "relation_type": "USES", "target_id": 2},
                {"source_id": "r1", "relation_type": "HAS", "target_id": "i1"},
            ]
        )
    )
    assert service._extract_relationships_from_graph(driver) == [
        ("1", "USES", "2"),
        ("r1", "HAS", "i1"),
    ]
    assert (
        service._extract_relationships_from_graph(
            _Driver(_Session(error=RuntimeError("neo4j down")))
        )
        == []
    )
