from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from rag_modules.infra.milvus.module import MilvusIndexConstructionModule


class _IndexParams:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def add_index(self, **kwargs: object) -> None:
        self.calls.append(dict(kwargs))


class _Client:
    def __init__(self) -> None:
        self.collections: set[str] = set()
        self.aliases: dict[str, str] = {}
        self.created: list[dict[str, object]] = []
        self.dropped: list[str] = []
        self.loaded: list[str] = []
        self.indexes: list[dict[str, object]] = []
        self.stats_requested: list[str] = []
        self.stats: dict[str, object] = {
            "row_count": 4,
            "index_building_progress": 100,
        }
        self.failure: RuntimeError | None = None

    def _raise(self) -> None:
        if self.failure:
            raise self.failure

    def list_collections(self) -> list[str]:
        self._raise()
        return sorted(self.collections)

    def has_collection(self, name: str) -> bool:
        self._raise()
        return name in self.collections

    def create_collection(self, **kwargs: object) -> None:
        self._raise()
        self.created.append(dict(kwargs))
        self.collections.add(str(kwargs["collection_name"]))

    def drop_collection(self, name: str) -> None:
        self._raise()
        self.dropped.append(name)
        self.collections.discard(name)

    def prepare_index_params(self) -> _IndexParams:
        self._raise()
        return _IndexParams()

    def create_index(self, **kwargs: object) -> None:
        self._raise()
        self.indexes.append(dict(kwargs))

    def get_collection_stats(self, name: str) -> dict[str, object]:
        self._raise()
        self.stats_requested.append(name)
        return dict(self.stats)

    def load_collection(self, name: str) -> None:
        self._raise()
        self.loaded.append(name)

    def describe_alias(self, *, alias: str) -> dict[str, str]:
        self._raise()
        if alias not in self.aliases:
            raise RuntimeError("alias missing")
        return {"collection": self.aliases[alias]}


def _module(client: _Client | None = None) -> MilvusIndexConstructionModule:
    module = MilvusIndexConstructionModule.__new__(MilvusIndexConstructionModule)
    module.client = client or _Client()
    module.host = "localhost"
    module.port = 19530
    module.dimension = 512
    module.base_collection_name = "recipes"
    module.collection_name = "recipes"
    module.collection_alias = "recipes__active"
    module.collection_created = False
    module.active_collection_name = ""
    module.active_collection_slot = ""
    module.blue_green_enabled = True
    module.embedding_client = SimpleNamespace(name="embedding")
    return module


def test_schema_contains_required_vector_and_metadata_fields() -> None:
    schema = _module()._create_collection_schema()
    fields = {field.name: field for field in schema.fields}

    assert set(fields) == {
        "id",
        "vector",
        "text",
        "entity_id",
        "entity_name",
        "entity_type",
        "domain",
        "attributes",
        "node_id",
        "recipe_name",
        "node_type",
        "category",
        "cuisine_type",
        "difficulty",
        "doc_type",
        "chunk_id",
        "parent_id",
    }
    assert fields["id"].is_primary is True
    assert fields["id"].params["max_length"] == 150
    assert fields["vector"].params["dim"] == 512
    assert fields["text"].params["max_length"] == 15000


def test_schema_propagates_invalid_sdk_field_options() -> None:
    module = _module()

    with (
        patch(
            "rag_modules.infra.milvus.schema.FieldSchema",
            side_effect=ValueError("invalid schema option"),
        ),
        pytest.raises(ValueError, match="invalid schema option"),
    ):
        module._create_collection_schema()


def test_create_collection_reuses_or_force_recreates_and_degrades_failures() -> None:
    client = _Client()
    client.collections.add("recipes")
    module = _module(client)

    assert module.create_collection() is True
    assert client.created == []
    assert module.collection_created is True

    module.collection_created = False
    assert module.create_collection(force_recreate=True, collection_name="recipes") is True
    assert client.dropped == ["recipes"]
    assert client.created[0]["collection_name"] == "recipes"
    assert client.created[0]["metric_type"] == "COSINE"
    assert client.created[0]["consistency_level"] == "Strong"
    assert module.collection_created is True

    client.failure = RuntimeError("milvus down")
    assert module.create_collection() is False


def test_create_collection_builds_an_absent_named_collection() -> None:
    client = _Client()
    module = _module(client)

    assert module.create_collection(collection_name="recipes__green") is True
    assert client.collections == {"recipes__green"}
    assert module.collection_name == "recipes__green"
    assert module.collection_created is True


def test_create_collection_forwards_constructed_schema_to_sdk_client() -> None:
    client = _Client()
    module = _module(client)
    constructed: list[SimpleNamespace] = []

    def _collection_schema(*, fields: list[object], description: str) -> SimpleNamespace:
        schema = SimpleNamespace(fields=fields, description=description)
        constructed.append(schema)
        return schema

    with patch(
        "rag_modules.infra.milvus.schema.CollectionSchema",
        side_effect=_collection_schema,
    ):
        assert module.create_collection(collection_name="recipes__green") is True

    [constructed_schema] = constructed
    assert client.created == [
        {
            "collection_name": "recipes__green",
            "schema": constructed_schema,
            "metric_type": "COSINE",
            "consistency_level": "Strong",
        }
    ]
    assert client.created[0]["schema"] is constructed_schema
    fields = {field.name: field for field in constructed_schema.fields}
    assert fields["id"].is_primary is True
    assert fields["vector"].params["dim"] == 512
    assert fields["difficulty"].dtype.name == "INT64"


def test_create_index_requires_collection_and_uses_hnsw() -> None:
    module = _module()

    assert module.create_index() is False

    module.collection_created = True
    assert module.create_index(collection_name="recipes") is True
    params = module.client.indexes[0]["index_params"]
    assert isinstance(params, _IndexParams)
    assert params.calls == [
        {
            "field_name": "vector",
            "index_type": "HNSW",
            "metric_type": "COSINE",
            "params": {"M": 16, "efConstruction": 200},
        }
    ]
    assert module.client.indexes[0]["collection_name"] == "recipes"

    assert module.create_index() is True
    assert module.client.indexes[1]["collection_name"] == module.collection_name


def test_setup_client_and_embeddings_use_injected_dependencies() -> None:
    fake = _Client()
    with patch("rag_modules.infra.milvus.client.MilvusClient", return_value=fake) as constructor:
        module = _module()
        module._setup_client()

    constructor.assert_called_once_with(uri="http://localhost:19530")
    assert module.client is fake
    module._setup_embeddings()
    assert module.embeddings is module.embedding_client


def test_setup_client_propagates_connection_failures() -> None:
    fake = _Client()
    fake.failure = RuntimeError("connection unavailable")
    module = _module()

    with (
        patch("rag_modules.infra.milvus.client.MilvusClient", return_value=fake),
        pytest.raises(RuntimeError, match="connection unavailable"),
    ):
        module._setup_client()


def test_stats_resolve_alias_and_degrade_when_unavailable() -> None:
    client = _Client()
    client.collections.add("recipes__blue")
    client.aliases["recipes__active"] = "recipes__blue"
    module = _module(client)
    module.collection_created = True
    module.collection_name = "recipes__active"
    module.active_collection_name = "recipes__blue"
    module.active_collection_slot = "blue"

    stats = module.get_collection_stats()
    assert stats == {
        "collection_name": "recipes__active",
        "active_collection_name": "recipes__blue",
        "collection_slot": "blue",
        "row_count": 4,
        "index_building_progress": 100,
        "stats": {"row_count": 4, "index_building_progress": 100},
    }
    direct_stats = module.get_collection_stats("missing")
    assert direct_stats["collection_name"] == "missing"
    assert direct_stats["row_count"] == 4
    assert client.stats_requested == ["recipes__blue", "missing"]

    client.failure = RuntimeError("stats down")
    assert module.get_collection_stats() == {"error": "MILVUS_STATS_UNAVAILABLE"}

    module.collection_created = False
    assert "error" in module.get_collection_stats()


def test_stats_default_missing_sdk_values_to_zero() -> None:
    client = _Client()
    client.stats = {}
    module = _module(client)
    module.collection_created = True

    stats = module.get_collection_stats()

    assert stats["row_count"] == 0
    assert stats["index_building_progress"] == 0
    assert stats["stats"] == {}


def test_has_delete_and_load_cover_alias_direct_absent_and_failure_paths() -> None:
    client = _Client()
    client.collections.update({"recipes", "recipes__blue"})
    client.aliases["recipes__active"] = "recipes__blue"
    module = _module(client)

    assert module.has_collection("recipes") is True
    assert module.has_collection("recipes__active") is True
    assert module.load_collection("recipes__active") is True
    assert client.loaded == ["recipes__blue"]
    assert module.collection_name == "recipes__active"
    assert module.delete_collection("recipes") is True
    assert module.collection_created is True
    assert client.dropped == ["recipes"]
    assert module.delete_collection("absent") is True
    assert module.load_collection("absent") is False

    client.failure = RuntimeError("milvus down")
    assert module.has_collection("recipes") is False
    assert module.delete_collection("recipes") is False
    assert module.load_collection("recipes") is False


def test_direct_delete_updates_collection_state() -> None:
    client = _Client()
    client.collections.add("recipes")
    module = _module(client)
    module.collection_created = True

    assert module.delete_collection() is True
    assert module.collection_created is False
    assert client.collections == set()


def test_close_and_destructor_tolerate_missing_or_present_client() -> None:
    module = _module()
    module.close()
    module.__del__()

    empty = MilvusIndexConstructionModule.__new__(MilvusIndexConstructionModule)
    empty.close()
    empty.__del__()
