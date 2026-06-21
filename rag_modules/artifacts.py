"""Compatibility facade for artifact manifest and cache helpers."""

from __future__ import annotations

from .artifact_documents import (
    compute_documents_digest,
    deserialize_document,
    read_documents,
    serialize_document,
    write_documents,
)
from .artifact_json import canonical_json_bytes as _canonical_json_bytes
from .artifact_json import json_safe as _json_safe
from .artifact_json import write_json_atomic
from .artifact_manifest import (
    ARTIFACT_HEALTH_FAILED,
    ARTIFACT_HEALTH_IN_PROGRESS,
    ARTIFACT_HEALTH_MISSING,
    ARTIFACT_HEALTH_READY,
    ARTIFACT_HEALTH_STALE,
    ARTIFACT_HEALTH_UNKNOWN,
    ARTIFACT_IN_PROGRESS_STAGES,
    ARTIFACT_INVALID_STAGES,
    ARTIFACT_MANIFEST_SCHEMA_VERSION,
    ARTIFACT_STAGE_BUILDING,
    ARTIFACT_STAGE_DOCUMENTS_READY,
    ARTIFACT_STAGE_FAILED,
    ARTIFACT_STAGE_MANIFEST_UNREADABLE,
    ARTIFACT_STAGE_MISSING,
    ARTIFACT_STAGE_READY,
    ARTIFACT_STAGE_REBUILDING,
    ARTIFACT_STAGE_STALE,
    ArtifactManifest,
    artifact_health,
    utc_now_iso,
)
from .artifact_manifest_store import ArtifactManifestStore
from .artifact_signatures import (
    compute_document_signature,
    compute_embedding_signature,
    compute_graph_signature,
    compute_index_signature,
)

__all__ = [
    "ARTIFACT_HEALTH_FAILED",
    "ARTIFACT_HEALTH_IN_PROGRESS",
    "ARTIFACT_HEALTH_MISSING",
    "ARTIFACT_HEALTH_READY",
    "ARTIFACT_HEALTH_STALE",
    "ARTIFACT_HEALTH_UNKNOWN",
    "ARTIFACT_IN_PROGRESS_STAGES",
    "ARTIFACT_INVALID_STAGES",
    "ARTIFACT_MANIFEST_SCHEMA_VERSION",
    "ARTIFACT_STAGE_BUILDING",
    "ARTIFACT_STAGE_DOCUMENTS_READY",
    "ARTIFACT_STAGE_FAILED",
    "ARTIFACT_STAGE_MANIFEST_UNREADABLE",
    "ARTIFACT_STAGE_MISSING",
    "ARTIFACT_STAGE_READY",
    "ARTIFACT_STAGE_REBUILDING",
    "ARTIFACT_STAGE_STALE",
    "ArtifactManifest",
    "ArtifactManifestStore",
    "_canonical_json_bytes",
    "_json_safe",
    "artifact_health",
    "compute_document_signature",
    "compute_documents_digest",
    "compute_embedding_signature",
    "compute_graph_signature",
    "compute_index_signature",
    "deserialize_document",
    "read_documents",
    "serialize_document",
    "utc_now_iso",
    "write_documents",
    "write_json_atomic",
]
