"""Manifest assembly helpers for document artifact cache state."""

from __future__ import annotations

from ...artifacts import ArtifactManifest, ArtifactManifestStore
from .models import DocumentArtifactSignatures, DocumentArtifactStats
from .settings import DocumentArtifactSettings


class DocumentArtifactManifestAssembler:
    """Assemble manifest payloads from signatures, stats, and settings."""

    def __init__(
        self,
        *,
        settings: DocumentArtifactSettings,
        manifest_store: ArtifactManifestStore,
    ) -> None:
        self.settings = settings
        self.manifest_store = manifest_store

    def base_manifest(self) -> ArtifactManifest:
        return ArtifactManifest.missing(
            documents_path=self.settings.documents_path,
            chunks_path=self.settings.chunks_path,
            manifest_path=self.manifest_store.manifest_path,
            collection_name=self.settings.collection_name,
            collection_base_name=self.settings.collection_name,
        )

    def assemble(
        self,
        *,
        signatures: DocumentArtifactSignatures,
        stats: DocumentArtifactStats,
        stage: str,
        cache_hit: bool,
        base_manifest: ArtifactManifest | None = None,
        build_metadata: dict | None = None,
    ) -> ArtifactManifest:
        return (base_manifest or self.base_manifest()).evolve(
            stage=stage,
            graph_signature=signatures.graph_signature,
            document_signature=signatures.document_signature,
            embedding_signature=signatures.embedding_signature,
            index_signature=signatures.index_signature,
            total_recipes=stats.total_recipes,
            total_ingredients=stats.total_ingredients,
            total_cooking_steps=stats.total_cooking_steps,
            total_documents=stats.total_documents,
            total_chunks=stats.total_chunks,
            cache_hit=cache_hit,
            last_error="",
            build_metadata=build_metadata or {},
        )
