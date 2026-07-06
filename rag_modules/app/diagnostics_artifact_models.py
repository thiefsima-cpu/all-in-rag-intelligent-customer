"""Artifact manifest diagnostics DTOs."""

from __future__ import annotations

from dataclasses import dataclass, field

from ..kernel.artifacts import ArtifactManifest, artifact_health
from ..kernel.json_types import JsonObject, coerce_json_object
from .diagnostics_payloads import extra_payload, put_if_present_or_meaningful


@dataclass(slots=True)
class ConfigProfileDiagnostics:
    name: str = ""
    path: str = ""
    hash: str = ""
    extra: JsonObject = field(default_factory=dict)
    present_keys: frozenset[str] = field(default_factory=frozenset)

    @property
    def has_values(self) -> bool:
        return bool(self.name or self.path or self.hash)

    @classmethod
    def from_payload(cls, payload: object) -> "ConfigProfileDiagnostics":
        data = coerce_json_object(payload)
        return cls(
            name=str(data.get("name") or ""),
            path=str(data.get("path") or ""),
            hash=str(data.get("hash") or ""),
            extra=extra_payload(data, frozenset({"name", "path", "hash"})),
            present_keys=frozenset(data),
        )

    def to_dict(self) -> JsonObject:
        payload = dict(self.extra)
        put_if_present_or_meaningful(payload, self.present_keys, "name", self.name)
        put_if_present_or_meaningful(payload, self.present_keys, "path", self.path)
        put_if_present_or_meaningful(payload, self.present_keys, "hash", self.hash)
        return payload


@dataclass(slots=True)
class ArtifactBuildMetadataDiagnostics:
    config_profile: ConfigProfileDiagnostics = field(default_factory=ConfigProfileDiagnostics)
    extra: JsonObject = field(default_factory=dict)
    config_profile_present: bool = False

    @classmethod
    def from_payload(cls, payload: object) -> "ArtifactBuildMetadataDiagnostics":
        data = coerce_json_object(payload)
        config_profile = ConfigProfileDiagnostics.from_payload(data.get("config_profile"))
        extra = {key: value for key, value in data.items() if key != "config_profile"}
        return cls(
            config_profile=config_profile,
            extra=extra,
            config_profile_present="config_profile" in data,
        )

    def to_dict(self) -> JsonObject:
        payload = dict(self.extra)
        if self.config_profile_present or self.config_profile.has_values:
            payload["config_profile"] = self.config_profile.to_dict()
        return payload


@dataclass(slots=True)
class ArtifactManifestDiagnostics:
    stage: str
    health: str
    updated_at: str
    collection_name: str
    manifest_path: str
    documents_path: str
    chunks_path: str
    total_documents: int
    total_chunks: int
    vector_rows: int
    cache_hit: bool
    last_error: str
    build_metadata: ArtifactBuildMetadataDiagnostics
    manifest_version: int = 0
    index_version: str = ""
    collection_base_name: str = ""
    collection_slot: str = ""
    previous_collection_name: str = ""
    published_at: str = ""

    @classmethod
    def from_manifest(cls, manifest: ArtifactManifest | None) -> "ArtifactManifestDiagnostics":
        manifest = manifest or ArtifactManifest()
        return cls(
            stage=manifest.stage,
            health=artifact_health(manifest),
            updated_at=manifest.updated_at,
            collection_name=manifest.collection_name,
            manifest_path=manifest.manifest_path,
            documents_path=manifest.documents_path,
            chunks_path=manifest.chunks_path,
            total_documents=manifest.total_documents,
            total_chunks=manifest.total_chunks,
            vector_rows=manifest.vector_rows,
            cache_hit=manifest.cache_hit,
            last_error=manifest.last_error,
            build_metadata=ArtifactBuildMetadataDiagnostics.from_payload(manifest.build_metadata),
            manifest_version=manifest.manifest_version,
            index_version=manifest.index_version,
            collection_base_name=manifest.collection_base_name,
            collection_slot=manifest.collection_slot,
            previous_collection_name=manifest.previous_collection_name,
            published_at=manifest.published_at,
        )

    def to_dict(self) -> JsonObject:
        return {
            "stage": self.stage,
            "health": self.health,
            "updated_at": self.updated_at,
            "collection_name": self.collection_name,
            "manifest_path": self.manifest_path,
            "documents_path": self.documents_path,
            "chunks_path": self.chunks_path,
            "total_documents": self.total_documents,
            "total_chunks": self.total_chunks,
            "vector_rows": self.vector_rows,
            "cache_hit": self.cache_hit,
            "last_error": self.last_error,
            "build_metadata": self.build_metadata.to_dict(),
            "manifest_version": self.manifest_version,
            "index_version": self.index_version,
            "collection_base_name": self.collection_base_name,
            "collection_slot": self.collection_slot,
            "previous_collection_name": self.previous_collection_name,
            "published_at": self.published_at,
        }


__all__ = [
    "ArtifactBuildMetadataDiagnostics",
    "ArtifactManifestDiagnostics",
    "ConfigProfileDiagnostics",
]
