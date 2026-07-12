from __future__ import annotations

from rag_modules.kernel.artifacts import ArtifactManifest
from rag_modules.kernel.documents import TextDocument
from rag_modules.runtime.artifact_adapters import DefaultRuntimeArtifactAccess, _string_mapping


class _ModernVectorIndex:
    def __init__(self) -> None:
        self.collection_name = "base"
        self.calls: list[tuple[str, object]] = []

    def use_manifest(self, manifest: ArtifactManifest) -> str:
        self.calls.append(("use_manifest", manifest))
        return "active-alias"

    def prepare_blue_green_build(self, active_collection_name: str = ""):
        self.calls.append(("prepare", active_collection_name))
        return {"collection_name": "candidate", "collection_slot": None}

    def publish_collection(self, collection_name: str) -> str:
        self.calls.append(("publish", collection_name))
        return "previous"

    def rollback_collection_publish(self, previous_collection_name: str = "") -> None:
        self.calls.append(("rollback", previous_collection_name))

    def discard_build_collection(self, collection_name: str) -> bool:
        self.calls.append(("discard", collection_name))
        return False

    def build_vector_index(self, chunks, **kwargs) -> bool:
        self.calls.append(("build", (list(chunks), dict(kwargs))))
        return True

    def has_collection(self) -> bool:
        return True

    def load_collection(self) -> bool:
        return True

    def delete_collection(self) -> bool:
        return True


class _LegacyEmptyIndex:
    collection_name = ""

    def build_vector_index(self, chunks, **kwargs) -> bool:
        self.built = (list(chunks), dict(kwargs))
        return True

    def has_collection(self) -> bool:
        return False

    def load_collection(self) -> bool:
        return False

    def delete_collection(self) -> bool:
        return False


def test_modern_artifact_access_uses_blue_green_lifecycle_protocols() -> None:
    access = DefaultRuntimeArtifactAccess()
    index = _ModernVectorIndex()
    manifest = ArtifactManifest(collection_name="physical")
    chunks = [TextDocument(content="chunk")]

    assert access.configure_vector_collection(index, manifest) == "active-alias"
    assert access.prepare_vector_index_build(index, "current") == {
        "collection_name": "candidate",
        "collection_slot": "",
    }
    assert access.build_vector_index(index, chunks) is True
    assert access.publish_vector_index(index, "candidate") == "previous"
    access.rollback_vector_index_publish(index, "previous")
    assert access.discard_vector_index(index, "candidate") is False
    assert ("prepare", "current") in index.calls
    assert ("rollback", "previous") in index.calls


def test_legacy_empty_collection_paths_and_graph_data_coercion() -> None:
    access = DefaultRuntimeArtifactAccess()
    index = _LegacyEmptyIndex()
    chunks = [TextDocument(content="chunk")]

    assert access.configure_vector_collection(index, ArtifactManifest()) == ""
    assert access.prepare_vector_index_build(index) == {
        "collection_name": "",
        "collection_base_name": "",
        "collection_slot": "",
    }
    assert access.build_vector_index(index, chunks) is True
    assert index.built == (chunks, {})
    assert access.publish_vector_index(index, "") == ""
    access.rollback_vector_index_publish(index, "ignored")
    assert access.discard_vector_index(index, "candidate") is True
    assert access.load_graph_data(
        type("Data", (), {"load_graph_data": lambda self: {"count": 1}})()
    ) == {"count": 1}
    assert _string_mapping({"value": 1, "empty": None}) == {"value": "1", "empty": ""}
