"""Artifact manifest state model and health classification."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, Mapping

from ...domain.shared.semantic_schema import SEMANTIC_SCHEMA_VERSION
from .json import json_safe

ARTIFACT_MANIFEST_SCHEMA_VERSION = "graph-rag-artifact-manifest-v2"


class ArtifactStage(str, Enum):
    MISSING = "missing"
    DOCUMENTS_READY = "documents_ready"
    BUILDING = "building"
    REBUILDING = "rebuilding"
    READY = "ready"
    FAILED = "failed"
    STALE = "stale"
    MANIFEST_UNREADABLE = "manifest_unreadable"


def _artifact_stage(value: "ArtifactStage | str | None") -> ArtifactStage:
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
    total_recipes: int = 0
    total_ingredients: int = 0
    total_cooking_steps: int = 0
    total_documents: int = 0
    total_chunks: int = 0
    vector_rows: int = 0
    cache_hit: bool = False
    last_error: str = ""
    build_metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.stage = _artifact_stage(self.stage)

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

    def to_dict(self) -> Dict[str, Any]:
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
            "total_recipes": self.total_recipes,
            "total_ingredients": self.total_ingredients,
            "total_cooking_steps": self.total_cooking_steps,
            "total_documents": self.total_documents,
            "total_chunks": self.total_chunks,
            "vector_rows": self.vector_rows,
            "cache_hit": self.cache_hit,
            "last_error": self.last_error,
            "build_metadata": json_safe(self.build_metadata),
        }

    def evolve(self, **changes: Any) -> "ArtifactManifest":
        build_metadata = changes.pop("build_metadata", None)
        if "stage" in changes:
            changes["stage"] = _artifact_stage(changes["stage"])
        next_manifest = replace(
            self,
            updated_at=changes.pop("updated_at", utc_now_iso()),
            **changes,
        )
        if build_metadata is not None:
            merged_metadata = dict(self.build_metadata)
            merged_metadata.update(dict(build_metadata))
            next_manifest.build_metadata = merged_metadata
        return next_manifest

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any] | None) -> "ArtifactManifest":
        if not payload:
            return cls()
        return cls(
            schema_version=str(payload.get("schema_version") or ARTIFACT_MANIFEST_SCHEMA_VERSION),
            manifest_version=int(payload.get("manifest_version") or 0),
            semantic_schema_version=str(
                payload.get("semantic_schema_version") or SEMANTIC_SCHEMA_VERSION
            ),
            stage=_artifact_stage(payload.get("stage")),
            updated_at=str(payload.get("updated_at") or utc_now_iso()),
            published_at=str(payload.get("published_at") or ""),
            graph_signature=str(payload.get("graph_signature") or ""),
            document_signature=str(payload.get("document_signature") or ""),
            embedding_signature=str(payload.get("embedding_signature") or ""),
            index_signature=str(payload.get("index_signature") or ""),
            index_version=str(payload.get("index_version") or ""),
            collection_name=str(payload.get("collection_name") or ""),
            collection_base_name=str(
                payload.get("collection_base_name") or payload.get("collection_name") or ""
            ),
            collection_slot=str(payload.get("collection_slot") or ""),
            previous_collection_name=str(payload.get("previous_collection_name") or ""),
            documents_path=str(payload.get("documents_path") or ""),
            chunks_path=str(payload.get("chunks_path") or ""),
            manifest_path=str(payload.get("manifest_path") or ""),
            total_recipes=int(payload.get("total_recipes") or 0),
            total_ingredients=int(payload.get("total_ingredients") or 0),
            total_cooking_steps=int(payload.get("total_cooking_steps") or 0),
            total_documents=int(payload.get("total_documents") or 0),
            total_chunks=int(payload.get("total_chunks") or 0),
            vector_rows=int(payload.get("vector_rows") or 0),
            cache_hit=bool(payload.get("cache_hit")),
            last_error=str(payload.get("last_error") or ""),
            build_metadata=dict(payload.get("build_metadata") or {}),
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
    "ArtifactStage",
    "artifact_health",
    "utc_now_iso",
]
