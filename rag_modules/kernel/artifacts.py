"""Artifact manifest state model and health classification."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from enum import Enum
from typing import Mapping, TypedDict, Unpack

from .documents import TextDocument
from .json_types import JsonObject, coerce_int, coerce_json_object, coerce_str
from .semantic_schema import SEMANTIC_SCHEMA_VERSION

ARTIFACT_MANIFEST_SCHEMA_VERSION = "graph-rag-artifact-manifest-v3"


class ArtifactStage(str, Enum):
    MISSING = "missing"
    DOCUMENTS_READY = "documents_ready"
    BUILDING = "building"
    REBUILDING = "rebuilding"
    READY = "ready"
    FAILED = "failed"
    STALE = "stale"
    MANIFEST_UNREADABLE = "manifest_unreadable"


def _artifact_stage(value: object) -> ArtifactStage:
    if isinstance(value, ArtifactStage):
        return value
    try:
        return ArtifactStage(str(value or ArtifactStage.MISSING.value))
    except ValueError:
        return ArtifactStage.MISSING


ARTIFACT_STAGE_MISSING = ArtifactStage.MISSING.value
ARTIFACT_STAGE_DOCUMENTS_READY = ArtifactStage.DOCUMENTS_READY.value
ARTIFACT_STAGE_BUILDING = ArtifactStage.BUILDING.value
ARTIFACT_STAGE_REBUILDING = ArtifactStage.REBUILDING.value
ARTIFACT_STAGE_READY = ArtifactStage.READY.value
ARTIFACT_STAGE_FAILED = ArtifactStage.FAILED.value
ARTIFACT_STAGE_STALE = ArtifactStage.STALE.value
ARTIFACT_STAGE_MANIFEST_UNREADABLE = ArtifactStage.MANIFEST_UNREADABLE.value
ARTIFACT_HEALTH_READY = "ready"
ARTIFACT_HEALTH_IN_PROGRESS = "in_progress"
ARTIFACT_HEALTH_MISSING = "missing"
ARTIFACT_HEALTH_STALE = "stale"
ARTIFACT_HEALTH_FAILED = "failed"
ARTIFACT_HEALTH_UNKNOWN = "unknown"
ARTIFACT_IN_PROGRESS_STAGES = frozenset(
    {
        ArtifactStage.BUILDING,
        ArtifactStage.REBUILDING,
        ArtifactStage.DOCUMENTS_READY,
    }
)
ARTIFACT_INVALID_STAGES = frozenset(
    {
        ArtifactStage.MISSING,
        ArtifactStage.FAILED,
        ArtifactStage.STALE,
        ArtifactStage.MANIFEST_UNREADABLE,
    }
)


class ArtifactManifestUpdate(TypedDict, total=False):
    schema_version: str
    manifest_version: int
    semantic_schema_version: str
    stage: ArtifactStage | str
    updated_at: str
    published_at: str
    graph_signature: str
    document_signature: str
    embedding_signature: str
    index_signature: str
    index_version: str
    collection_name: str
    collection_base_name: str
    collection_slot: str
    previous_collection_name: str
    documents_path: str
    chunks_path: str
    manifest_path: str
    total_entities: int
    total_documents: int
    total_chunks: int
    domain_metrics: JsonObject
    vector_rows: int
    cache_hit: bool
    last_error: str
    build_metadata: JsonObject


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def artifact_health(manifest: "ArtifactManifest | None") -> str:
    manifest = manifest or ArtifactManifest()
    if manifest.is_ready:
        return ARTIFACT_HEALTH_READY
    if manifest.is_stale:
        return ARTIFACT_HEALTH_STALE
    if manifest.is_failed:
        return ARTIFACT_HEALTH_FAILED
    if manifest.is_in_progress:
        return ARTIFACT_HEALTH_IN_PROGRESS
    if manifest.is_missing:
        return ARTIFACT_HEALTH_MISSING
    return ARTIFACT_HEALTH_UNKNOWN


@dataclass(slots=True)
class ArtifactManifest:
    schema_version: str = ARTIFACT_MANIFEST_SCHEMA_VERSION
    manifest_version: int = 0
    semantic_schema_version: str = SEMANTIC_SCHEMA_VERSION
    stage: ArtifactStage | str = ArtifactStage.MISSING
    updated_at: str = field(default_factory=utc_now_iso)
    published_at: str = ""
    graph_signature: str = ""
    document_signature: str = ""
    embedding_signature: str = ""
    index_signature: str = ""
    index_version: str = ""
    collection_name: str = ""
    collection_base_name: str = ""
    collection_slot: str = ""
    previous_collection_name: str = ""
    documents_path: str = ""
    chunks_path: str = ""
    manifest_path: str = ""
    total_entities: int = 0
    total_documents: int = 0
    total_chunks: int = 0
    domain_metrics: JsonObject = field(default_factory=dict)
    vector_rows: int = 0
    cache_hit: bool = False
    last_error: str = ""
    build_metadata: JsonObject = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.stage = _artifact_stage(self.stage)
        self.build_metadata = coerce_json_object(self.build_metadata)
        self.domain_metrics = coerce_json_object(self.domain_metrics)

    @property
    def is_ready(self) -> bool:
        return self.stage == ArtifactStage.READY

    @property
    def is_missing(self) -> bool:
        return self.stage == ArtifactStage.MISSING

    @property
    def is_stale(self) -> bool:
        return self.stage == ArtifactStage.STALE

    @property
    def is_failed(self) -> bool:
        return self.stage in {ArtifactStage.FAILED, ArtifactStage.MANIFEST_UNREADABLE}

    @property
    def is_in_progress(self) -> bool:
        return self.stage in ARTIFACT_IN_PROGRESS_STAGES

    @property
    def is_invalid(self) -> bool:
        return self.stage in ARTIFACT_INVALID_STAGES

    def to_dict(self) -> JsonObject:
        return {
            "schema_version": self.schema_version,
            "manifest_version": self.manifest_version,
            "semantic_schema_version": self.semantic_schema_version,
            "stage": _artifact_stage(self.stage).value,
            "updated_at": self.updated_at,
            "published_at": self.published_at,
            "graph_signature": self.graph_signature,
            "document_signature": self.document_signature,
            "embedding_signature": self.embedding_signature,
            "index_signature": self.index_signature,
            "index_version": self.index_version,
            "collection_name": self.collection_name,
            "collection_base_name": self.collection_base_name,
            "collection_slot": self.collection_slot,
            "previous_collection_name": self.previous_collection_name,
            "documents_path": self.documents_path,
            "chunks_path": self.chunks_path,
            "manifest_path": self.manifest_path,
            "total_entities": self.total_entities,
            "total_documents": self.total_documents,
            "total_chunks": self.total_chunks,
            "domain_metrics": coerce_json_object(self.domain_metrics),
            "vector_rows": self.vector_rows,
            "cache_hit": self.cache_hit,
            "last_error": self.last_error,
            "build_metadata": coerce_json_object(self.build_metadata),
        }

    def evolve(self, **changes: Unpack[ArtifactManifestUpdate]) -> "ArtifactManifest":
        build_metadata = changes.get("build_metadata")
        if "stage" in changes:
            changes["stage"] = _artifact_stage(changes["stage"])
        changes.setdefault("updated_at", utc_now_iso())
        next_manifest = replace(self, **changes)
        if build_metadata is not None:
            merged_metadata = dict(self.build_metadata)
            merged_metadata.update(dict(build_metadata))
            next_manifest.build_metadata = merged_metadata
        return next_manifest

    @classmethod
    def from_dict(cls, payload: Mapping[str, object] | None) -> "ArtifactManifest":
        if not payload:
            return cls()
        return cls(
            schema_version=coerce_str(payload.get("schema_version"))
            or ARTIFACT_MANIFEST_SCHEMA_VERSION,
            manifest_version=coerce_int(payload.get("manifest_version")),
            semantic_schema_version=coerce_str(
                payload.get("semantic_schema_version") or SEMANTIC_SCHEMA_VERSION
            ),
            stage=_artifact_stage(payload.get("stage")),
            updated_at=coerce_str(payload.get("updated_at")) or utc_now_iso(),
            published_at=coerce_str(payload.get("published_at")),
            graph_signature=coerce_str(payload.get("graph_signature")),
            document_signature=coerce_str(payload.get("document_signature")),
            embedding_signature=coerce_str(payload.get("embedding_signature")),
            index_signature=coerce_str(payload.get("index_signature")),
            index_version=coerce_str(payload.get("index_version")),
            collection_name=coerce_str(payload.get("collection_name")),
            collection_base_name=coerce_str(
                payload.get("collection_base_name") or payload.get("collection_name") or ""
            ),
            collection_slot=coerce_str(payload.get("collection_slot")),
            previous_collection_name=coerce_str(payload.get("previous_collection_name")),
            documents_path=coerce_str(payload.get("documents_path")),
            chunks_path=coerce_str(payload.get("chunks_path")),
            manifest_path=coerce_str(payload.get("manifest_path")),
            total_entities=coerce_int(payload.get("total_entities")),
            total_documents=coerce_int(payload.get("total_documents")),
            total_chunks=coerce_int(payload.get("total_chunks")),
            domain_metrics=coerce_json_object(payload.get("domain_metrics")),
            vector_rows=coerce_int(payload.get("vector_rows")),
            cache_hit=bool(payload.get("cache_hit")),
            last_error=coerce_str(payload.get("last_error")),
            build_metadata=coerce_json_object(payload.get("build_metadata")),
        )

    @classmethod
    def missing(
        cls,
        *,
        documents_path: str = "",
        chunks_path: str = "",
        manifest_path: str = "",
        collection_name: str = "",
        collection_base_name: str = "",
    ) -> "ArtifactManifest":
        return cls(
            stage=ArtifactStage.MISSING,
            documents_path=documents_path,
            chunks_path=chunks_path,
            manifest_path=manifest_path,
            collection_name=collection_name,
            collection_base_name=collection_base_name or collection_name,
        )


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


@dataclass(slots=True)
class DocumentArtifactResult:
    documents: list[TextDocument]
    chunks: list[TextDocument]
    manifest: ArtifactManifest
    cache_hit: bool


@dataclass(slots=True)
class DocumentArtifactSignatures:
    graph_signature: str
    document_signature: str
    embedding_signature: str
    index_signature: str


@dataclass(slots=True)
class DocumentArtifactStats:
    total_entities: int
    total_documents: int
    total_chunks: int
    domain_metrics: JsonObject = field(default_factory=dict)


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
    "ArtifactManifestUpdate",
    "ArtifactStage",
    "DocumentArtifactResult",
    "DocumentArtifactSignatures",
    "DocumentArtifactStats",
    "artifact_health",
    "utc_now_iso",
    "vector_artifact_mismatch_reason",
    "vector_artifacts_compatible",
]
