"""Artifact lifecycle contracts shared by build and serving runtimes."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol

from .artifacts import ArtifactManifest

if TYPE_CHECKING:
    from ..build_pipeline.document_artifacts.models import DocumentArtifactResult


class ArtifactManifestStorePort(Protocol):
    """Stable manifest repository boundary for build and serving lifecycles."""

    manifest_path: str

    def load(self) -> ArtifactManifest: ...

    def save(self, manifest: ArtifactManifest) -> ArtifactManifest: ...

    def load_candidate(self) -> ArtifactManifest | None: ...

    def save_candidate(self, manifest: ArtifactManifest) -> ArtifactManifest: ...

    def clear_candidate(self) -> None: ...


class DocumentArtifactCachePort(Protocol):
    """Document/chunk artifact cache boundary for serving warmup and builds."""

    def load(self, data_module: Any) -> DocumentArtifactResult | None: ...

    def save(
        self,
        data_module: Any,
        *,
        stage: str = "documents_ready",
        cache_hit: bool = False,
        base_manifest: ArtifactManifest | None = None,
        build_metadata: dict[str, Any] | None = None,
    ) -> ArtifactManifest: ...


class RuntimeArtifactAccessPort(Protocol):
    """Lifecycle boundary for graph-data loading and vector-index readiness."""

    def load_graph_data(self, data_module: Any) -> Any: ...

    def configure_vector_collection(
        self,
        index_module: Any,
        manifest: ArtifactManifest,
    ) -> str: ...

    def has_vector_collection(self, index_module: Any) -> bool: ...

    def load_vector_collection(self, index_module: Any) -> bool: ...

    def prepare_vector_index_build(
        self,
        index_module: Any,
        active_collection_name: str = "",
    ) -> dict[str, str]: ...

    def build_vector_index(
        self,
        index_module: Any,
        chunks: Any,
        *,
        collection_name: str = "",
    ) -> bool: ...

    def publish_vector_index(self, index_module: Any, collection_name: str) -> str: ...

    def rollback_vector_index_publish(
        self,
        index_module: Any,
        previous_collection_name: str = "",
    ) -> None: ...

    def discard_vector_index(self, index_module: Any, collection_name: str) -> bool: ...

    def delete_vector_collection(self, index_module: Any) -> bool: ...


__all__ = [
    "ArtifactManifestStorePort",
    "DocumentArtifactCachePort",
    "RuntimeArtifactAccessPort",
]
