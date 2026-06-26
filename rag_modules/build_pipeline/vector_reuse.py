"""Vector collection reuse decisions for knowledge-base build workflow."""

from __future__ import annotations

from ..runtime.artifact_validation import vector_artifact_mismatch_reason
from ..runtime.artifacts import ArtifactManifest
from .stats_presenter import ProgressCallback


class _KnowledgeBaseVectorReuseMixin:
    """Own active collection and manifest reuse decisions."""

    def _can_reuse_existing_vector_collection(
        self,
        document_manifest: ArtifactManifest,
        *,
        progress: ProgressCallback = None,
    ) -> bool:
        mismatch_reason = vector_artifact_mismatch_reason(
            persisted_manifest=self.artifact_manifest,
            current_manifest=document_manifest,
        )
        if mismatch_reason:
            self._emit(progress, f"[WARN] {mismatch_reason}")
            return False
        return True

    def _configure_active_collection(self, manifest: ArtifactManifest) -> None:
        configure = getattr(
            self.runtime_artifact_access,
            "configure_vector_collection",
            None,
        )
        if callable(configure):
            configure(self.index_module, manifest)
            return
        collection_name = str(manifest.collection_name or "")
        if collection_name and hasattr(self.index_module, "collection_name"):
            self.index_module.collection_name = collection_name

    @staticmethod
    def _reuse_manifest(
        document_manifest: ArtifactManifest,
        *,
        active_manifest: ArtifactManifest,
    ) -> ArtifactManifest:
        return document_manifest.evolve(
            collection_name=active_manifest.collection_name or document_manifest.collection_name,
            collection_base_name=active_manifest.collection_base_name
            or document_manifest.collection_base_name
            or document_manifest.collection_name,
            collection_slot=active_manifest.collection_slot,
            previous_collection_name=active_manifest.previous_collection_name,
            index_version=active_manifest.index_version,
            published_at=active_manifest.published_at,
        )


__all__ = ["_KnowledgeBaseVectorReuseMixin"]
