"""Default artifact lifecycle adapters shared by runtime composition."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol, runtime_checkable

from ..kernel.artifacts import ArtifactManifest
from ..kernel.documents import TextDocument
from ..kernel.json_types import JsonObject, coerce_json_object
from .ports import GraphDataModulePort, VectorIndexModulePort


@runtime_checkable
class _ManifestBoundVectorIndexPort(Protocol):
    def use_manifest(self, manifest: ArtifactManifest) -> str: ...


@runtime_checkable
class _PreparedVectorIndexPort(Protocol):
    def prepare_blue_green_build(
        self,
        active_collection_name: str = "",
    ) -> Mapping[str, object]: ...


@runtime_checkable
class _PublishedVectorIndexPort(Protocol):
    def publish_collection(self, collection_name: str) -> str: ...


@runtime_checkable
class _RollbackVectorIndexPort(Protocol):
    def rollback_collection_publish(self, previous_collection_name: str = "") -> None: ...


@runtime_checkable
class _DiscardableVectorIndexPort(Protocol):
    def discard_build_collection(self, collection_name: str) -> bool: ...


class DefaultRuntimeArtifactAccess:
    """Default adapter over graph-data loading and vector-index readiness."""

    def load_graph_data(self, data_module: GraphDataModulePort) -> JsonObject:
        return coerce_json_object(data_module.load_graph_data())

    def configure_vector_collection(
        self,
        index_module: VectorIndexModulePort,
        manifest: ArtifactManifest,
    ) -> str:
        if isinstance(index_module, _ManifestBoundVectorIndexPort):
            return str(index_module.use_manifest(manifest))
        collection_name = str(getattr(manifest, "collection_name", "") or "")
        if collection_name:
            index_module.collection_name = collection_name
        return collection_name

    def has_vector_collection(self, index_module: VectorIndexModulePort) -> bool:
        return bool(index_module.has_collection())

    def load_vector_collection(self, index_module: VectorIndexModulePort) -> bool:
        return bool(index_module.load_collection())

    def prepare_vector_index_build(
        self,
        index_module: VectorIndexModulePort,
        active_collection_name: str = "",
    ) -> dict[str, str]:
        if isinstance(index_module, _PreparedVectorIndexPort):
            return _string_mapping(index_module.prepare_blue_green_build(active_collection_name))
        return {
            "collection_name": str(getattr(index_module, "collection_name", "") or ""),
            "collection_base_name": str(getattr(index_module, "collection_name", "") or ""),
            "collection_slot": "",
        }

    def build_vector_index(
        self,
        index_module: VectorIndexModulePort,
        chunks: list[TextDocument],
        *,
        collection_name: str = "",
    ) -> bool:
        if collection_name:
            return bool(
                index_module.build_vector_index(
                    chunks,
                    collection_name=collection_name,
                )
            )
        return bool(index_module.build_vector_index(chunks))

    def publish_vector_index(
        self,
        index_module: VectorIndexModulePort,
        collection_name: str,
    ) -> str:
        if isinstance(index_module, _PublishedVectorIndexPort):
            return str(index_module.publish_collection(collection_name) or "")
        if collection_name:
            index_module.collection_name = collection_name
        return ""

    def rollback_vector_index_publish(
        self,
        index_module: VectorIndexModulePort,
        previous_collection_name: str = "",
    ) -> None:
        if isinstance(index_module, _RollbackVectorIndexPort):
            index_module.rollback_collection_publish(previous_collection_name)

    def discard_vector_index(
        self,
        index_module: VectorIndexModulePort,
        collection_name: str,
    ) -> bool:
        if isinstance(index_module, _DiscardableVectorIndexPort):
            return bool(index_module.discard_build_collection(collection_name))
        return True

    def delete_vector_collection(self, index_module: VectorIndexModulePort) -> bool:
        return bool(index_module.delete_collection())


def _string_mapping(payload: Mapping[str, object]) -> dict[str, str]:
    return {str(key): str(value or "") for key, value in payload.items()}


__all__ = ["DefaultRuntimeArtifactAccess"]
