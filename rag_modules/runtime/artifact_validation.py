"""Shared validation helpers for build- and serving-time artifact compatibility."""

from __future__ import annotations

from ..artifacts import ArtifactManifest


def vector_artifact_mismatch_reason(
    *,
    persisted_manifest: ArtifactManifest,
    current_manifest: ArtifactManifest,
) -> str:
    if not persisted_manifest.is_ready:
        return "Artifact manifest is missing or not ready. Existing vector collection cannot be trusted."
    if (
        not persisted_manifest.index_signature
        or not current_manifest.index_signature
        or persisted_manifest.index_signature != current_manifest.index_signature
    ):
        return "Persisted vector artifacts do not match the current document or embedding configuration."
    persisted_base_name = (
        persisted_manifest.collection_base_name or persisted_manifest.collection_name
    )
    current_base_name = current_manifest.collection_base_name or current_manifest.collection_name
    if persisted_base_name and current_base_name and persisted_base_name != current_base_name:
        return "Persisted vector collection name does not match the current runtime configuration."
    return ""


def vector_artifacts_compatible(
    *,
    persisted_manifest: ArtifactManifest,
    current_manifest: ArtifactManifest,
) -> bool:
    return not vector_artifact_mismatch_reason(
        persisted_manifest=persisted_manifest,
        current_manifest=current_manifest,
    )


__all__ = [
    "vector_artifact_mismatch_reason",
    "vector_artifacts_compatible",
]
