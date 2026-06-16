"""Startup diagnostics for build and serving entrypoints."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from ..artifacts import ArtifactManifest, artifact_health


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
    build_metadata: Dict[str, Any]
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
            build_metadata=dict(manifest.build_metadata or {}),
            manifest_version=manifest.manifest_version,
            index_version=manifest.index_version,
            collection_base_name=manifest.collection_base_name,
            collection_slot=manifest.collection_slot,
            previous_collection_name=manifest.previous_collection_name,
            published_at=manifest.published_at,
        )

    def to_dict(self) -> Dict[str, Any]:
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
            "build_metadata": dict(self.build_metadata),
            "manifest_version": self.manifest_version,
            "index_version": self.index_version,
            "collection_base_name": self.collection_base_name,
            "collection_slot": self.collection_slot,
            "previous_collection_name": self.previous_collection_name,
            "published_at": self.published_at,
        }


@dataclass(slots=True)
class StartupDiagnostics:
    mode: str
    llm_model: str
    embedding_model: str
    rerank_model: str
    trace_enabled: bool
    trace_path: str
    trace_stats: Dict[str, Any]
    build_initialized: bool
    serving_initialized: bool
    artifacts_ready: bool
    system_ready: bool
    retrieval_engines_initialized: bool
    manifest: ArtifactManifestDiagnostics

    def to_dict(self) -> Dict[str, Any]:
        return {
            "mode": self.mode,
            "llm_model": self.llm_model,
            "embedding_model": self.embedding_model,
            "rerank_model": self.rerank_model,
            "trace_enabled": self.trace_enabled,
            "trace_path": self.trace_path,
            "trace_stats": dict(self.trace_stats),
            "build_initialized": self.build_initialized,
            "serving_initialized": self.serving_initialized,
            "artifacts_ready": self.artifacts_ready,
            "system_ready": self.system_ready,
            "retrieval_engines_initialized": self.retrieval_engines_initialized,
            "manifest": self.manifest.to_dict(),
        }

    def to_lines(self, *, title: Optional[str] = None) -> List[str]:
        heading = title or f"{self.mode.capitalize()} startup diagnostics"
        lines = [
            heading,
            "-" * len(heading),
            (
                f"Models: llm={self.llm_model}, "
                f"embedding={self.embedding_model}, rerank={self.rerank_model}"
            ),
            f"Tracing: {'enabled' if self.trace_enabled else 'disabled'} ({self.trace_path})",
            (
                "Runtime: "
                f"build_initialized={self.build_initialized}, "
                f"serving_initialized={self.serving_initialized}, "
                f"artifacts_ready={self.artifacts_ready}, "
                f"system_ready={self.system_ready}, "
                f"retrieval_engines_initialized={self.retrieval_engines_initialized}"
            ),
            (
                "Manifest: "
                f"health={self.manifest.health}, "
                f"stage={self.manifest.stage}, "
                f"version={self.manifest.manifest_version}, "
                f"slot={self.manifest.collection_slot or 'legacy'}, "
                f"cache_hit={self.manifest.cache_hit}, "
                f"documents={self.manifest.total_documents}, "
                f"chunks={self.manifest.total_chunks}, "
                f"vector_rows={self.manifest.vector_rows}"
            ),
            f"Manifest path: {self.manifest.manifest_path}",
        ]
        if self.manifest.documents_path:
            lines.append(f"Documents cache: {self.manifest.documents_path}")
        if self.manifest.chunks_path:
            lines.append(f"Chunks cache: {self.manifest.chunks_path}")
        if self.trace_stats:
            lines.append(
                "Trace stats: "
                f"dropped={self.trace_stats.get('dropped_events', 0)}, "
                f"queued={self.trace_stats.get('queued_events', 0)}, "
                f"async_enabled={self.trace_stats.get('async_enabled', False)}"
            )
        if self.manifest.last_error:
            lines.append(f"Manifest error: {self.manifest.last_error}")
        return lines


@dataclass(slots=True)
class SystemStatsDiagnostics:
    initialized: bool
    build_initialized: bool
    serving_initialized: bool
    artifacts_ready: bool
    ready: bool
    models: Dict[str, Any]
    trace_stats: Dict[str, Any]
    retrieval_runtime_profile: Dict[str, Any]
    manifest: ArtifactManifestDiagnostics
    data_stats: Dict[str, Any]
    index_stats: Dict[str, Any]
    route_stats: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "initialized": self.initialized,
            "build_initialized": self.build_initialized,
            "serving_initialized": self.serving_initialized,
            "artifacts_ready": self.artifacts_ready,
            "ready": self.ready,
            "models": dict(self.models),
            "trace_stats": dict(self.trace_stats),
            "retrieval_runtime_profile": dict(self.retrieval_runtime_profile),
            "artifact_manifest": self.manifest.to_dict(),
            "data_stats": dict(self.data_stats),
            "index_stats": dict(self.index_stats),
            "route_stats": dict(self.route_stats),
        }
