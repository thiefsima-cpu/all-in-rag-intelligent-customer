from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock, patch

from rag_modules.kernel.documents import TextDocument
from rag_modules.retrieval.hybrid_index_service import HybridIndexArtifacts, HybridIndexService
from rag_modules.retrieval.parent_doc_enricher import ParentDocumentEnricher
from tests.configuration_test_helpers import build_test_config


class _BM25:
    def __init__(self, restore: bool = True) -> None:
        self.restore = restore
        self.bm25 = object()
        self.corpus_docs = [TextDocument(content="cached")]
        self.build_calls: list[list[TextDocument]] = []

    def build(self, chunks: list[TextDocument]) -> None:
        self.build_calls.append(list(chunks))

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

    def run(self, query: str, parameters: object | None = None) -> list[object]:
        del query, parameters
        if self.error:
            raise self.error
        return self.records


class _Driver:
    def __init__(self, session: _Session) -> None:
        self.session_obj = session

    def session(self, **kwargs: object) -> _Session:
        return self.session_obj


def _service(*, restore: bool = True) -> HybridIndexService:
    config = build_test_config({"domain": {"name": "recipe"}})
    data_module = SimpleNamespace(documents=[], entities=[])
    graph_indexing = SimpleNamespace(
        from_cache_dict=lambda payload: True,
        to_cache_dict=lambda: {"graph": True},
        create_domain_entity_key_values=lambda entities: None,
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


def test_initialize_prefers_valid_cache_and_builds_when_cache_is_unavailable() -> None:
    service = _service()
    cached = HybridIndexArtifacts(graph_indexed=True)
    with patch.object(service, "load_index_cache", return_value=cached) as load:
        assert service.initialize([TextDocument(content="chunk")], None) is cached
    load.assert_called_once()

    service = _service()
    chunks = [TextDocument(content="chunk")]
    built = HybridIndexArtifacts(graph_indexed=True)
    with (
        patch.object(service, "load_index_cache", return_value=None),
        patch.object(service, "_build_graph_index") as build_graph,
        patch.object(service, "_build_artifacts", return_value=built),
        patch.object(service, "save_index_cache") as save,
    ):
        assert service.initialize(chunks, None) is built
    assert service.bm25_retriever.build_calls == [chunks]
    build_graph.assert_called_once_with(None)
    save.assert_called_once_with(chunks, built)

    service.storage.enable_index_cache = False
    with (
        patch.object(service, "_build_graph_index"),
        patch.object(service, "_build_artifacts", return_value=built),
        patch.object(service, "save_index_cache") as save,
    ):
        assert service.initialize([], None) is built
    save.assert_not_called()


def test_load_cache_validates_payload_restore_and_artifact_readiness() -> None:
    service = _service()
    service.cache_store = SimpleNamespace(
        load=lambda chunks: {
            "graph": True,
            "bm25_retriever": {},
            "parent_documents": {"r1": {"page_content": "parent", "metadata": {"node_id": "r1"}}},
        }
    )

    artifacts = service.load_index_cache([])

    assert artifacts is not None
    assert artifacts.graph_indexed is True
    assert artifacts.parent_doc_map["r1"].content == "parent"
    assert service.parent_enricher.parent_doc_map == artifacts.parent_doc_map

    service.cache_store = SimpleNamespace(load=lambda chunks: None)
    assert service.load_index_cache([]) is None

    service = _service(restore=False)
    service.cache_store = SimpleNamespace(load=lambda chunks: {"bm25_retriever": {}})
    assert service.load_index_cache([]) is None

    service = _service()
    service.graph_indexing.from_cache_dict = Mock(side_effect=RuntimeError("cache corrupt"))
    service.cache_store = SimpleNamespace(load=lambda chunks: {"bm25_retriever": {}})
    assert service.load_index_cache([]) is None

    service = _service()
    service.graph_indexing.from_cache_dict = lambda payload: False
    service.cache_store = SimpleNamespace(load=lambda chunks: {"bm25_retriever": {}})
    assert service.load_index_cache([]) is None


def test_save_cache_and_build_artifacts_preserve_parent_documents() -> None:
    service = _service()
    saved: list[tuple[list[TextDocument], dict[str, object]]] = []
    service.cache_store = SimpleNamespace(
        save=lambda chunks, payload: saved.append((list(chunks), dict(payload)))
    )
    parent = TextDocument(content="parent", metadata={"node_id": "r1"})
    artifacts = HybridIndexArtifacts(parent_doc_map={"r1": parent})

    service.save_index_cache([TextDocument(content="chunk")], artifacts)

    assert saved[0][1]["bm25_retriever"] == {"tokens": [["cached"]]}
    assert saved[0][1]["parent_documents"]["r1"]["page_content"] == "parent"
    assert saved[0][1]["graph"] is True

    service.data_module.documents = [parent]
    built = service._build_artifacts()
    assert built.parent_doc_map["r1"].content == "parent"
    assert built.constraint_matcher is not None


def test_build_graph_index_is_idempotent_and_degrades_failures() -> None:
    service = _service()
    service.graph_indexed = True
    service.graph_indexing.create_domain_entity_key_values = Mock()
    service._build_graph_index(None)
    service.graph_indexing.create_domain_entity_key_values.assert_not_called()

    service.graph_indexed = False
    service.graph_indexing.create_domain_entity_key_values = Mock()
    service.graph_indexing.create_relation_key_values = Mock()
    service.graph_indexing.deduplicate_entities_and_relations = Mock()
    service._build_graph_index(None)
    assert service.graph_indexed is True
    service.graph_indexing.create_relation_key_values.assert_called_once_with([])

    service = _service()
    service.graph_indexing.create_domain_entity_key_values = Mock(
        side_effect=RuntimeError("index down")
    )
    service._build_graph_index(None)
    assert service.graph_indexed is False
