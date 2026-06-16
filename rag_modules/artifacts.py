"""Artifact manifest and document cache serialization helpers."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Mapping

from .semantic_schema import SEMANTIC_SCHEMA_VERSION
from .text_document import TextDocument

ARTIFACT_MANIFEST_SCHEMA_VERSION = "graph-rag-artifact-manifest-v2"
ARTIFACT_STAGE_MISSING = "missing"
ARTIFACT_STAGE_DOCUMENTS_READY = "documents_ready"
ARTIFACT_STAGE_BUILDING = "building"
ARTIFACT_STAGE_REBUILDING = "rebuilding"
ARTIFACT_STAGE_READY = "ready"
ARTIFACT_STAGE_FAILED = "failed"
ARTIFACT_STAGE_STALE = "stale"
ARTIFACT_STAGE_MANIFEST_UNREADABLE = "manifest_unreadable"
ARTIFACT_HEALTH_READY = "ready"
ARTIFACT_HEALTH_IN_PROGRESS = "in_progress"
ARTIFACT_HEALTH_MISSING = "missing"
ARTIFACT_HEALTH_STALE = "stale"
ARTIFACT_HEALTH_FAILED = "failed"
ARTIFACT_HEALTH_UNKNOWN = "unknown"
ARTIFACT_IN_PROGRESS_STAGES = frozenset(
    {
        ARTIFACT_STAGE_BUILDING,
        ARTIFACT_STAGE_REBUILDING,
        ARTIFACT_STAGE_DOCUMENTS_READY,
    }
)
ARTIFACT_INVALID_STAGES = frozenset(
    {
        ARTIFACT_STAGE_MISSING,
        ARTIFACT_STAGE_FAILED,
        ARTIFACT_STAGE_STALE,
        ARTIFACT_STAGE_MANIFEST_UNREADABLE,
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


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]
    return str(value)


def serialize_document(document: TextDocument) -> Dict[str, Any]:
    content = getattr(document, "content", None)
    if content is None:
        content = getattr(document, "page_content", "")
    return {
        "content": str(content or ""),
        "metadata": _json_safe(getattr(document, "metadata", {}) or {}),
    }


def _canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        _json_safe(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def compute_documents_digest(documents: Iterable[TextDocument]) -> str:
    payload = [serialize_document(document) for document in documents]
    return hashlib.sha256(_canonical_json_bytes(payload)).hexdigest()


def deserialize_document(payload: Mapping[str, Any]) -> TextDocument:
    return TextDocument(
        content=str(payload.get("content") or payload.get("page_content") or ""),
        metadata=dict(payload.get("metadata") or {}),
    )


def write_documents(path: str, documents: Iterable[TextDocument]) -> None:
    payload = [serialize_document(document) for document in documents]
    write_json_atomic(path, payload)


def read_documents(path: str) -> List[TextDocument]:
    with open(path, "r", encoding="utf-8") as file:
        payload = json.load(file)
    if not isinstance(payload, list):
        raise ValueError(f"Document cache payload at {path!r} must be a list.")
    if not all(isinstance(item, Mapping) for item in payload):
        raise ValueError(f"Document cache payload at {path!r} contains invalid items.")
    return [deserialize_document(item) for item in payload]


def compute_graph_signature(data_module) -> str:
    collections = (
        ("recipes", getattr(data_module, "recipes", []) or []),
        ("ingredients", getattr(data_module, "ingredients", []) or []),
        ("cooking_steps", getattr(data_module, "cooking_steps", []) or []),
    )
    payload: Dict[str, Any] = {
        "schema": "graph-content-v2",
        "semantic_schema_version": SEMANTIC_SCHEMA_VERSION,
    }
    for collection_name, collection in collections:
        payload[collection_name] = sorted(
            (
                {
                    "node_id": str(getattr(node, "node_id", "")),
                    "name": str(getattr(node, "name", "")),
                    "labels": sorted(
                        str(label) for label in (getattr(node, "labels", []) or [])
                    ),
                    "properties": _json_safe(getattr(node, "properties", {}) or {}),
                }
                for node in collection
            ),
            key=lambda item: (
                item["node_id"],
                item["name"],
                _canonical_json_bytes(item["properties"]),
            ),
        )
    return hashlib.sha256(_canonical_json_bytes(payload)).hexdigest()


def _signature(namespace: str, payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        _canonical_json_bytes(
            {
                "namespace": namespace,
                **dict(payload),
            }
        )
    ).hexdigest()


def write_json_atomic(path: str, payload: Any) -> None:
    parent_dir = os.path.dirname(path) or "."
    os.makedirs(parent_dir, exist_ok=True)
    temporary_path = ""
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=parent_dir,
            prefix=f".{os.path.basename(path)}.",
            suffix=".tmp",
            delete=False,
        ) as file:
            temporary_path = file.name
            json.dump(payload, file, ensure_ascii=False, indent=2)
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary_path, path)
    finally:
        if temporary_path and os.path.exists(temporary_path):
            os.remove(temporary_path)


def compute_document_signature(*, graph_signature: str, chunk_size: int, chunk_overlap: int) -> str:
    return _signature(
        "document-artifacts-v2",
        {
            "graph_signature": graph_signature,
            "semantic_schema_version": SEMANTIC_SCHEMA_VERSION,
            "chunk_size": int(chunk_size),
            "chunk_overlap": int(chunk_overlap),
        },
    )


def compute_embedding_signature(*, model_name: str, dimension: int, base_url: str) -> str:
    return _signature(
        "embedding-runtime-v2",
        {
            "model_name": str(model_name),
            "dimension": int(dimension),
            "base_url": str(base_url),
        },
    )


def compute_index_signature(
    *,
    document_signature: str,
    embedding_signature: str,
    collection_name: str,
) -> str:
    return _signature(
        "vector-index-v2",
        {
            "document_signature": document_signature,
            "embedding_signature": embedding_signature,
            "collection_name": str(collection_name),
        },
    )


@dataclass(slots=True)
class ArtifactManifest:
    schema_version: str = ARTIFACT_MANIFEST_SCHEMA_VERSION
    manifest_version: int = 0
    semantic_schema_version: str = SEMANTIC_SCHEMA_VERSION
    stage: str = ARTIFACT_STAGE_MISSING
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

    @property
    def is_ready(self) -> bool:
        return self.stage == ARTIFACT_STAGE_READY

    @property
    def is_missing(self) -> bool:
        return self.stage == ARTIFACT_STAGE_MISSING

    @property
    def is_stale(self) -> bool:
        return self.stage == ARTIFACT_STAGE_STALE

    @property
    def is_failed(self) -> bool:
        return self.stage in {ARTIFACT_STAGE_FAILED, ARTIFACT_STAGE_MANIFEST_UNREADABLE}

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
            "stage": self.stage,
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
            "build_metadata": _json_safe(self.build_metadata),
        }

    def evolve(self, **changes: Any) -> "ArtifactManifest":
        build_metadata = changes.pop("build_metadata", None)
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
            semantic_schema_version=str(payload.get("semantic_schema_version") or SEMANTIC_SCHEMA_VERSION),
            stage=str(payload.get("stage") or ARTIFACT_STAGE_MISSING),
            updated_at=str(payload.get("updated_at") or utc_now_iso()),
            published_at=str(payload.get("published_at") or ""),
            graph_signature=str(payload.get("graph_signature") or ""),
            document_signature=str(payload.get("document_signature") or ""),
            embedding_signature=str(payload.get("embedding_signature") or ""),
            index_signature=str(payload.get("index_signature") or ""),
            index_version=str(payload.get("index_version") or ""),
            collection_name=str(payload.get("collection_name") or ""),
            collection_base_name=str(
                payload.get("collection_base_name")
                or payload.get("collection_name")
                or ""
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
            stage=ARTIFACT_STAGE_MISSING,
            documents_path=documents_path,
            chunks_path=chunks_path,
            manifest_path=manifest_path,
            collection_name=collection_name,
            collection_base_name=collection_base_name or collection_name,
        )


class ArtifactManifestStore:
    """Persist an active manifest, a candidate sidecar, and immutable versions."""

    def __init__(self, config):
        storage = config.storage
        self.manifest_path = str(storage.artifact_manifest_path)
        parent_dir = os.path.dirname(self.manifest_path)
        if parent_dir:
            os.makedirs(parent_dir, exist_ok=True)
        filename = os.path.basename(self.manifest_path)
        stem, _ = os.path.splitext(filename)
        self.candidate_path = os.path.join(
            parent_dir,
            f"{stem}.candidate.json",
        )
        self.versions_dir = os.path.join(parent_dir, f"{stem}.versions")

    def load(self) -> ArtifactManifest:
        if not os.path.exists(self.manifest_path):
            return ArtifactManifest.missing(manifest_path=self.manifest_path)
        try:
            with open(self.manifest_path, "r", encoding="utf-8") as file:
                payload = json.load(file)
            manifest = ArtifactManifest.from_dict(payload)
            if manifest.manifest_path != self.manifest_path:
                manifest = manifest.evolve(manifest_path=self.manifest_path)
            return manifest
        except Exception as exc:
            return ArtifactManifest.missing(
                manifest_path=self.manifest_path,
            ).evolve(
                stage=ARTIFACT_STAGE_MANIFEST_UNREADABLE,
                last_error=str(exc),
            )

    def save(self, manifest: ArtifactManifest) -> ArtifactManifest:
        current = self.load()
        next_version = max(
            int(current.manifest_version or 0) + 1,
            int(manifest.manifest_version or 0),
            1,
        )
        normalized = manifest.evolve(
            schema_version=ARTIFACT_MANIFEST_SCHEMA_VERSION,
            manifest_version=next_version,
            manifest_path=self.manifest_path,
        )
        self._write_json_atomic(
            self.version_path(next_version),
            normalized.to_dict(),
        )
        self._write_json_atomic(self.manifest_path, normalized.to_dict())
        return normalized

    def load_candidate(self) -> ArtifactManifest | None:
        if not os.path.exists(self.candidate_path):
            return None
        try:
            with open(self.candidate_path, "r", encoding="utf-8") as file:
                payload = json.load(file)
            manifest = ArtifactManifest.from_dict(payload)
            return manifest.evolve(
                manifest_path=self.manifest_path,
                updated_at=manifest.updated_at,
            )
        except Exception:
            return None

    def save_candidate(self, manifest: ArtifactManifest) -> ArtifactManifest:
        active = self.load()
        candidate_version = max(
            int(active.manifest_version or 0) + 1,
            int(manifest.manifest_version or 0),
            1,
        )
        normalized = manifest.evolve(
            schema_version=ARTIFACT_MANIFEST_SCHEMA_VERSION,
            manifest_version=candidate_version,
            manifest_path=self.manifest_path,
        )
        self._write_json_atomic(self.candidate_path, normalized.to_dict())
        return normalized

    def clear_candidate(self) -> None:
        try:
            os.remove(self.candidate_path)
        except FileNotFoundError:
            return

    def version_path(self, manifest_version: int) -> str:
        return os.path.join(
            self.versions_dir,
            f"v{int(manifest_version):06d}.json",
        )

    def list_versions(self) -> List[int]:
        versions: List[int] = []
        if not os.path.isdir(self.versions_dir):
            return versions
        for filename in os.listdir(self.versions_dir):
            if not (filename.startswith("v") and filename.endswith(".json")):
                continue
            try:
                versions.append(int(filename[1:-5]))
            except ValueError:
                continue
        return sorted(versions)

    def load_version(self, manifest_version: int) -> ArtifactManifest:
        path = self.version_path(manifest_version)
        with open(path, "r", encoding="utf-8") as file:
            manifest = ArtifactManifest.from_dict(json.load(file))
            return manifest.evolve(
                manifest_path=self.manifest_path,
                updated_at=manifest.updated_at,
            )

    @staticmethod
    def _write_json_atomic(path: str, payload: Mapping[str, Any]) -> None:
        write_json_atomic(path, payload)
