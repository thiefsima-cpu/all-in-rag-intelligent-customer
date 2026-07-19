"""Startup and system diagnostics DTOs."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from ..kernel.json_types import JsonObject
from .diagnostics_artifact_models import ArtifactManifestDiagnostics
from .diagnostics_formatters import startup_diagnostics_lines
from .diagnostics_stats_models import (
    DataStatsDiagnostics,
    IndexStatsDiagnostics,
    ModelDiagnostics,
    RetrievalRuntimeProfileDiagnostics,
    RouteStatsDiagnostics,
    TraceStatsDiagnostics,
)


@dataclass(slots=True)
class StartupDiagnostics:
    mode: str
    llm_model: str
    embedding_model: str
    rerank_model: str
    trace_enabled: bool
    trace_path: str
    trace_stats: TraceStatsDiagnostics
    build_initialized: bool
    serving_initialized: bool
    artifacts_ready: bool
    system_ready: bool
    retrieval_engines_initialized: bool
    manifest: ArtifactManifestDiagnostics
    domain_name: str = ""

    def to_dict(self) -> JsonObject:
        return {
            "mode": self.mode,
            "domain_name": self.domain_name,
            "llm_model": self.llm_model,
            "embedding_model": self.embedding_model,
            "rerank_model": self.rerank_model,
            "trace_enabled": self.trace_enabled,
            "trace_path": self.trace_path,
            "trace_stats": self.trace_stats.to_dict(),
            "build_initialized": self.build_initialized,
            "serving_initialized": self.serving_initialized,
            "artifacts_ready": self.artifacts_ready,
            "system_ready": self.system_ready,
            "retrieval_engines_initialized": self.retrieval_engines_initialized,
            "manifest": self.manifest.to_dict(),
        }

    def to_lines(self, *, title: Optional[str] = None) -> list[str]:
        return startup_diagnostics_lines(self, title=title)


@dataclass(slots=True)
class SystemStatsDiagnostics:
    initialized: bool
    build_initialized: bool
    serving_initialized: bool
    artifacts_ready: bool
    ready: bool
    models: ModelDiagnostics
    trace_stats: TraceStatsDiagnostics
    retrieval_runtime_profile: RetrievalRuntimeProfileDiagnostics
    manifest: ArtifactManifestDiagnostics
    data_stats: DataStatsDiagnostics
    index_stats: IndexStatsDiagnostics
    route_stats: RouteStatsDiagnostics

    def to_dict(self) -> JsonObject:
        return {
            "initialized": self.initialized,
            "build_initialized": self.build_initialized,
            "serving_initialized": self.serving_initialized,
            "artifacts_ready": self.artifacts_ready,
            "ready": self.ready,
            "models": self.models.to_dict(),
            "trace_stats": self.trace_stats.to_dict(),
            "retrieval_runtime_profile": self.retrieval_runtime_profile.to_dict(),
            "artifact_manifest": self.manifest.to_dict(),
            "data_stats": self.data_stats.to_dict(),
            "index_stats": self.index_stats.to_dict(),
            "route_stats": self.route_stats.to_dict(),
        }


__all__ = [
    "StartupDiagnostics",
    "SystemStatsDiagnostics",
]
