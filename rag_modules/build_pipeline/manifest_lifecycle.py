"""Artifact-manifest lifecycle coordination for build workflows."""

from __future__ import annotations

from typing import Optional

from ..runtime.artifact_ports import ArtifactManifestStorePort
from ..runtime.artifacts import (
    ARTIFACT_MANIFEST_SCHEMA_VERSION,
    ARTIFACT_STAGE_BUILDING,
    ARTIFACT_STAGE_FAILED,
    ARTIFACT_STAGE_READY,
    ArtifactManifest,
    utc_now_iso,
)

BUILD_FAILED_ERROR_CODE = "BUILD_FAILED"


def _failure_metadata(
    exc: Exception,
    *,
    request_id: str = "",
    build_job_id: str = "",
) -> dict[str, str]:
    metadata = {
        "code": BUILD_FAILED_ERROR_CODE,
        "error_type": type(exc).__name__,
    }
    if request_id:
        metadata["request_id"] = str(request_id)
    if build_job_id:
        metadata["build_job_id"] = str(build_job_id)
    return metadata


class KnowledgeBaseManifestLifecycle:
    """Own manifest loading and stage transitions for build workflows."""

    def __init__(self, manifest_store: ArtifactManifestStorePort) -> None:
        self.manifest_store = manifest_store
        self.artifact_manifest = manifest_store.load()
        self.candidate_manifest: ArtifactManifest | None = None

    def mark_building(self, candidate_manifest: ArtifactManifest) -> ArtifactManifest:
        self.candidate_manifest = candidate_manifest.evolve(
            schema_version=ARTIFACT_MANIFEST_SCHEMA_VERSION,
            manifest_version=max(self.artifact_manifest.manifest_version + 1, 1),
            stage=ARTIFACT_STAGE_BUILDING,
            last_error="",
        )
        if self.artifact_manifest.is_ready:
            self._save_candidate(self.candidate_manifest)
            return self.candidate_manifest
        self.artifact_manifest = self.manifest_store.save(self.candidate_manifest)
        return self.artifact_manifest

    def mark_ready(
        self,
        base_manifest: ArtifactManifest,
        *,
        vector_rows: int,
        build_metadata: Optional[dict] = None,
        index_version: str = "",
    ) -> ArtifactManifest:
        next_version = max(
            self.artifact_manifest.manifest_version + 1,
            base_manifest.manifest_version,
            1,
        )
        resolved_index_version = index_version or base_manifest.index_version
        if not resolved_index_version:
            signature_label = base_manifest.index_signature[:12] or "index"
            resolved_index_version = f"v{next_version:06d}-{signature_label}"
        self.artifact_manifest = self.manifest_store.save(
            base_manifest.evolve(
                schema_version=ARTIFACT_MANIFEST_SCHEMA_VERSION,
                manifest_version=next_version,
                stage=ARTIFACT_STAGE_READY,
                published_at=utc_now_iso(),
                index_version=resolved_index_version,
                vector_rows=vector_rows,
                cache_hit=bool(base_manifest.cache_hit),
                last_error="",
                build_metadata=build_metadata or {},
            )
        )
        self.candidate_manifest = None
        clear_candidate = getattr(self.manifest_store, "clear_candidate", None)
        if callable(clear_candidate):
            clear_candidate()
        return self.artifact_manifest

    def mark_failed(
        self,
        exc: Exception,
        *,
        request_id: str = "",
        build_job_id: str = "",
    ) -> ArtifactManifest:
        failed_base = self.candidate_manifest or self.artifact_manifest
        failed_manifest = failed_base.evolve(
            stage=ARTIFACT_STAGE_FAILED,
            last_error=BUILD_FAILED_ERROR_CODE,
            build_metadata={
                "failure": _failure_metadata(
                    exc,
                    request_id=request_id,
                    build_job_id=build_job_id,
                )
            },
        )
        if self.artifact_manifest.is_ready:
            self.candidate_manifest = self._save_candidate(failed_manifest)
            return self.artifact_manifest
        self.artifact_manifest = self.manifest_store.save(failed_manifest)
        return self.artifact_manifest

    def reset(self, *, stage: str) -> ArtifactManifest:
        reset_manifest = self.artifact_manifest.evolve(
            manifest_version=max(self.artifact_manifest.manifest_version + 1, 1),
            stage=stage,
            cache_hit=False,
            last_error="",
        )
        if self.artifact_manifest.is_ready:
            self.candidate_manifest = self._save_candidate(reset_manifest)
            return self.artifact_manifest
        self.artifact_manifest = self.manifest_store.save(reset_manifest)
        return self.artifact_manifest

    def _save_candidate(self, manifest: ArtifactManifest) -> ArtifactManifest:
        save_candidate = getattr(self.manifest_store, "save_candidate", None)
        if callable(save_candidate):
            return save_candidate(manifest)
        return manifest


__all__ = ["BUILD_FAILED_ERROR_CODE", "KnowledgeBaseManifestLifecycle"]
