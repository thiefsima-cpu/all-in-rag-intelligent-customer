from __future__ import annotations

from unittest.mock import patch

import pytest

from rag_modules.infra.milvus.writer import _MilvusWriterOperations
from rag_modules.kernel.documents import TextDocument


class _Embeddings:
    def __init__(
        self,
        *,
        error: Exception | None = None,
        operations: list[str] | None = None,
    ) -> None:
        self.error = error
        self.texts: list[str] = []
        self.operations = operations

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if self.error:
            raise self.error
        if self.operations is not None:
            self.operations.append("embed")
        self.texts = list(texts)
        return [[float(index)] for index, _ in enumerate(texts)]


class _Client:
    def __init__(
        self,
        *,
        insert_error: Exception | None = None,
        operations: list[str] | None = None,
    ) -> None:
        self.insert_error = insert_error
        self.operations = operations
        self.inserted: list[tuple[str, list[dict[str, object]]]] = []
        self.flushed: list[str] = []
        self.loaded: list[str] = []

    def insert(self, *, collection_name: str, data: list[dict[str, object]]) -> None:
        if self.insert_error:
            raise self.insert_error
        if self.operations is not None:
            self.operations.append("insert")
        self.inserted.append((collection_name, data))

    def flush(self, *, collection_name: str) -> None:
        if self.operations is not None:
            self.operations.append("flush")
        self.flushed.append(collection_name)

    def load_collection(self, collection_name: str) -> None:
        if self.operations is not None:
            self.operations.append("load")
        self.loaded.append(collection_name)


class _Writer(_MilvusWriterOperations):
    def __init__(self) -> None:
        self.collection_name = "recipes"
        self.domain_name = "recipe"
        self.build_collection_name = ""
        self.collection_created = True
        self.operations: list[str] = []
        self.client = _Client(operations=self.operations)
        self.embeddings = _Embeddings(operations=self.operations)
        self.create_collection_result = True
        self.create_index_result = True

    def create_collection(self, force_recreate=False, *, collection_name=None) -> bool:
        assert force_recreate is True
        self.operations.append("create")
        return self.create_collection_result

    def create_index(self, *, collection_name=None) -> bool:
        self.operations.append("index")
        return self.create_index_result


def _chunk(content: str = "content", **metadata: object) -> TextDocument:
    return TextDocument(content=content, metadata=dict(metadata))


def test_safe_truncate_handles_none_and_limits_text() -> None:
    writer = _Writer()

    assert writer._safe_truncate(None, 3) == ""
    assert writer._safe_truncate(12345, 3) == "123"


def test_build_vector_index_rejects_empty_chunks() -> None:
    with pytest.raises(ValueError):
        _Writer().build_vector_index([])


def test_build_vector_index_writes_sanitized_entities_to_explicit_collection() -> None:
    writer = _Writer()
    chunks = [
        _chunk(
            "x" * 15001,
            chunk_id="c" * 151,
            entity_id="entity-1",
            entity_name="Mapo tofu",
            difficulty="3",
        ),
        _chunk("second"),
    ]

    with patch("rag_modules.infra.milvus.writer.time.sleep") as sleep:
        assert writer.build_vector_index(chunks, collection_name="recipes__green") is True

    assert writer.collection_name == "recipes__green"
    assert writer.build_collection_name == "recipes__green"
    assert writer.embeddings.texts == [chunk.page_content for chunk in chunks]
    assert len(writer.client.inserted[0][1][0]["id"]) == 150
    assert len(writer.client.inserted[0][1][0]["text"]) == 15000
    assert writer.client.inserted[0][1][0]["attributes"]["difficulty"] == "3"
    assert writer.client.flushed == ["recipes__green"]
    assert writer.client.loaded == ["recipes__green"]
    sleep.assert_called_once_with(2)


def test_vector_writer_enforces_runtime_domain_over_document_metadata() -> None:
    writer = _Writer()
    writer.domain_name = "customer_service"

    entity = writer._vector_entity(
        _chunk("order", domain="recipe", entity_id="CS-1001"),
        [0.1],
        0,
    )

    assert entity["domain"] == "customer_service"


def test_build_vector_index_preserves_batch_entity_and_operation_order() -> None:
    writer = _Writer()
    chunks = [
        _chunk(
            f"content-{index}",
            chunk_id=f"chunk-{index:03d}",
            node_id=f"node-{index:03d}",
        )
        for index in range(205)
    ]

    with patch(
        "rag_modules.infra.milvus.writer.time.sleep",
        side_effect=lambda _seconds: writer.operations.append("wait"),
    ):
        assert writer.build_vector_index(chunks, collection_name="recipes__ordered") is True

    assert writer.operations == [
        "create",
        "embed",
        "insert",
        "insert",
        "insert",
        "flush",
        "index",
        "load",
        "wait",
    ]
    assert [len(batch) for _, batch in writer.client.inserted] == [100, 100, 5]
    assert [collection for collection, _ in writer.client.inserted] == [
        "recipes__ordered",
        "recipes__ordered",
        "recipes__ordered",
    ]
    entities = [entity for _, batch in writer.client.inserted for entity in batch]
    assert [entity["id"] for entity in entities] == [f"chunk-{index:03d}" for index in range(205)]
    assert [entity["vector"] for entity in entities] == [[float(index)] for index in range(205)]
    assert writer.embeddings.texts == [chunk.page_content for chunk in chunks]
    assert writer.client.flushed == ["recipes__ordered"]
    assert writer.client.loaded == ["recipes__ordered"]


@pytest.mark.parametrize("failed_stage", ["collection", "index"])
def test_build_vector_index_returns_false_for_setup_failures(failed_stage: str) -> None:
    writer = _Writer()
    if failed_stage == "collection":
        writer.create_collection_result = False
    else:
        writer.create_index_result = False

    with patch("rag_modules.infra.milvus.writer.time.sleep"):
        assert writer.build_vector_index([_chunk()]) is False


def test_build_vector_index_degrades_embedding_failure() -> None:
    writer = _Writer()
    writer.embeddings = _Embeddings(error=RuntimeError("provider failed"))

    assert writer.build_vector_index([_chunk()]) is False


def test_add_documents_requires_existing_collection_and_inserts_defaults() -> None:
    writer = _Writer()
    writer.collection_created = False
    with pytest.raises(ValueError):
        writer.add_documents([_chunk()])

    writer.collection_created = True
    with patch("rag_modules.infra.milvus.writer.time.time", return_value=123):
        assert writer.add_documents([_chunk()]) is True
    entity = writer.client.inserted[-1][1][0]
    assert entity["id"] == "new_chunk_0_123"
    assert entity["chunk_id"] == "new_chunk_0_123"


def test_add_documents_degrades_embedding_and_client_failures() -> None:
    writer = _Writer()
    writer.embeddings = _Embeddings(error=RuntimeError("provider failed"))
    assert writer.add_documents([_chunk()]) is False

    writer.embeddings = _Embeddings()
    writer.client = _Client(insert_error=RuntimeError("insert failed"))
    assert writer.add_documents([_chunk()]) is False
