"""Runtime diagnostics and stats assembly for app-facing entrypoints."""

from __future__ import annotations

from ...configuration.models import GraphRAGConfig
from ...runtime.stats_adapters import DefaultRuntimeStatsAccess
from ...runtime.stats_ports import RuntimeStatsAccessPort
from ..diagnostics import (
    ArtifactManifestDiagnostics,
    StartupDiagnostics,
    SystemStatsDiagnostics,
)
from ..runtime_view import SystemRuntime


class RuntimeDiagnosticsService:
    """Assemble startup diagnostics and runtime stats from stable runtime views."""

    def __init__(
        self,
        config: GraphRAGConfig,
        *,
        runtime_stats_access: RuntimeStatsAccessPort | None = None,
    ) -> None:
        self.config = config
        self.runtime_stats_access = runtime_stats_access or DefaultRuntimeStatsAccess()

    def collect_system_stats(
        self,
        *,
        runtime: SystemRuntime,
        build_initialized: bool,
        serving_initialized: bool,
    ) -> SystemStatsDiagnostics:
        models = self.config.models
        infrastructure = runtime.infrastructure
        retrieval = runtime.retrieval
        data_stats = self.runtime_stats_access.get_graph_data_stats(infrastructure.data_module)
        index_stats = self.runtime_stats_access.get_vector_collection_stats(
            infrastructure.index_module
        )
        route_stats = self.runtime_stats_access.get_route_stats(retrieval.routing_workflow)
        trace_stats = self.runtime_stats_access.get_query_trace_stats(infrastructure.query_tracer)
        runtime_profile = self.runtime_stats_access.get_retrieval_runtime_profile(
            retrieval.retrieval_runtime_profile
        )
        return SystemStatsDiagnostics(
            initialized=runtime.is_initialized(),
            build_initialized=build_initialized,
            serving_initialized=serving_initialized,
            artifacts_ready=runtime.artifacts_ready,
            ready=runtime.system_ready,
            models={
                "embedding_model": models.embedding_model,
                "llm_model": models.llm_model,
                "rerank_model": models.rerank_model,
            },
            trace_stats=trace_stats,
            retrieval_runtime_profile=runtime_profile,
            manifest=ArtifactManifestDiagnostics.from_manifest(runtime.artifact_manifest),
            data_stats=data_stats,
            index_stats=index_stats,
            route_stats=route_stats,
        )

    def collect_startup_diagnostics(
        self,
        *,
        mode: str,
        runtime: SystemRuntime,
        build_initialized: bool,
        serving_initialized: bool,
    ) -> StartupDiagnostics:
        models = self.config.models
        observability = self.config.observability
        trace_stats = self.runtime_stats_access.get_query_trace_stats(
            runtime.infrastructure.query_tracer
            if getattr(runtime, "infrastructure", None)
            else None
        )
        retrieval_engines_initialized = bool(
            runtime.serving_runtime and runtime.serving_runtime.retrieval_engines_initialized
        )
        return StartupDiagnostics(
            mode=mode,
            llm_model=models.llm_model,
            embedding_model=models.embedding_model,
            rerank_model=models.rerank_model,
            trace_enabled=bool(observability.enable_query_tracing),
            trace_path=str(observability.query_trace_path),
            trace_stats=trace_stats,
            build_initialized=build_initialized,
            serving_initialized=serving_initialized,
            artifacts_ready=runtime.artifacts_ready,
            system_ready=runtime.system_ready,
            retrieval_engines_initialized=retrieval_engines_initialized,
            manifest=ArtifactManifestDiagnostics.from_manifest(runtime.artifact_manifest),
        )


__all__ = ["RuntimeDiagnosticsService"]
