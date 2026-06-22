"""Lifecycle coordinator for build and serving runtimes."""

from __future__ import annotations

from ...configuration.models import GraphRAGConfig
from ...runtime.artifacts import ArtifactManifest
from ..runtime_state import BuildRuntime, ServingRuntime
from ..runtime_view import SystemRuntime
from ..services.runtime_diagnostics_service import RuntimeDiagnosticsService
from ..services.runtime_shutdown_service import RuntimeShutdownService
from .runtime_lifecycle_service_composer import RuntimeLifecycleServiceBundle
from .runtime_state_store import RuntimeStateStore
from .shared import ProgressCallback


class SystemRuntimeManager:
    """Coordinate runtime state while delegating heavy lifecycle logic to collaborators."""

    def __init__(
        self,
        *,
        config: GraphRAGConfig,
        diagnostics_service: RuntimeDiagnosticsService,
        shutdown_service: RuntimeShutdownService,
        lifecycle_services: RuntimeLifecycleServiceBundle,
        runtime_state_store: RuntimeStateStore | None = None,
    ) -> None:
        self.config = config
        self.diagnostics_service = diagnostics_service
        self.shutdown_service = shutdown_service
        self.initialization_service = lifecycle_services.initialization_service
        self.readiness_service = lifecycle_services.readiness_service
        self.refresh_service = lifecycle_services.refresh_service
        self.build_lifecycle_service = lifecycle_services.build_lifecycle_service
        self.runtime_state_store = runtime_state_store or RuntimeStateStore()

    def initialize_build_runtime(
        self,
        *,
        progress: ProgressCallback = None,
        neo4j_manager=None,
    ) -> BuildRuntime:
        runtime = self.initialization_service.initialize_build_runtime(
            self.build_runtime,
            progress=progress,
            neo4j_manager=neo4j_manager,
        )
        self.build_runtime = runtime
        return runtime

    def initialize_serving_runtime(
        self,
        *,
        progress: ProgressCallback = None,
        query_tracer=None,
        neo4j_manager=None,
    ) -> ServingRuntime:
        runtime = self.initialization_service.initialize_serving_runtime(
            self.serving_runtime,
            build_runtime=self.build_runtime,
            progress=progress,
            query_tracer=query_tracer,
            neo4j_manager=neo4j_manager,
        )
        self.serving_runtime = runtime
        return runtime

    def initialize_system(
        self,
        *,
        progress: ProgressCallback = None,
        query_tracer=None,
        neo4j_manager=None,
    ) -> SystemRuntime:
        build_runtime, serving_runtime = self.initialization_service.initialize_system(
            build_runtime=self.build_runtime,
            serving_runtime=self.serving_runtime,
            progress=progress,
            query_tracer=query_tracer,
            neo4j_manager=neo4j_manager,
        )
        return self.runtime_state_store.replace(
            build_runtime=build_runtime,
            serving_runtime=serving_runtime,
        )

    def build_knowledge_base(self, *, progress: ProgressCallback = None) -> BuildRuntime:
        build_runtime, serving_runtime = self.build_lifecycle_service.build_knowledge_base(
            self.build_runtime,
            serving_runtime=self.serving_runtime,
            progress=progress,
        )
        self.runtime_state_store.replace(
            build_runtime=build_runtime,
            serving_runtime=serving_runtime,
        )
        return build_runtime

    def rebuild_knowledge_base(self, *, progress: ProgressCallback = None) -> BuildRuntime:
        build_runtime, serving_runtime = self.build_lifecycle_service.rebuild_knowledge_base(
            self.build_runtime,
            serving_runtime=self.serving_runtime,
            progress=progress,
        )
        self.runtime_state_store.replace(
            build_runtime=build_runtime,
            serving_runtime=serving_runtime,
        )
        return build_runtime

    def collect_system_stats(self) -> dict:
        runtime = self.runtime_view()
        return self.diagnostics_service.collect_system_stats(
            runtime=runtime,
            build_initialized=self.is_build_initialized(),
            serving_initialized=self.is_serving_initialized(),
        ).to_dict()

    def collect_startup_diagnostics(self, mode: str):
        runtime = self.runtime_view()
        return self.diagnostics_service.collect_startup_diagnostics(
            mode=mode,
            runtime=runtime,
            build_initialized=self.is_build_initialized(),
            serving_initialized=self.is_serving_initialized(),
        )

    def close(self) -> None:
        runtime = self.runtime_view()
        self.shutdown_service.close(runtime=runtime)
        self.runtime_state_store.clear()

    def compose_runtime(self) -> SystemRuntime:
        return self.runtime_state_store.refresh()

    def prepare_existing_serving_runtime(
        self,
        *,
        progress: ProgressCallback = None,
        force: bool = False,
    ) -> ServingRuntime | None:
        self.serving_runtime = self.refresh_service.prepare_existing(
            self.serving_runtime,
            shared_runtime=self.build_runtime,
            progress=progress,
            force=force,
        )
        return self.serving_runtime

    def refresh_serving_runtime(
        self,
        *,
        progress: ProgressCallback = None,
        force: bool = True,
    ) -> ServingRuntime:
        runtime = self.readiness_service.require_serving_runtime(self.serving_runtime)
        refreshed_runtime = self.refresh_service.prepare_existing(
            runtime,
            shared_runtime=None,
            progress=progress,
            force=force,
        )
        if refreshed_runtime is None:
            raise ValueError("Serving runtime refresh unexpectedly returned no runtime.")
        self.serving_runtime = refreshed_runtime
        return refreshed_runtime

    def runtime_view(self) -> SystemRuntime:
        return self.runtime_state_store.runtime_view()

    def require_build_runtime(self) -> BuildRuntime:
        return self.readiness_service.require_build_runtime(self.build_runtime)

    def require_serving_runtime(self) -> ServingRuntime:
        return self.readiness_service.require_serving_runtime(self.serving_runtime)

    def require_ready(self) -> ServingRuntime:
        return self.readiness_service.require_ready(
            self.serving_runtime,
            artifacts_ready=self.artifacts_ready,
        )

    def is_initialized(self) -> bool:
        return self.runtime_state_store.is_initialized()

    @property
    def build_runtime(self) -> BuildRuntime | None:
        return self.runtime_state_store.build_runtime

    @build_runtime.setter
    def build_runtime(self, runtime: BuildRuntime | None) -> None:
        self.runtime_state_store.build_runtime = runtime

    @property
    def serving_runtime(self) -> ServingRuntime | None:
        return self.runtime_state_store.serving_runtime

    @serving_runtime.setter
    def serving_runtime(self, runtime: ServingRuntime | None) -> None:
        self.runtime_state_store.serving_runtime = runtime

    @property
    def runtime(self) -> SystemRuntime:
        return self.runtime_state_store.runtime

    def is_build_initialized(self) -> bool:
        return self.readiness_service.is_build_initialized(self.build_runtime)

    def is_serving_initialized(self) -> bool:
        return self.readiness_service.is_serving_initialized(self.serving_runtime)

    @property
    def artifact_manifest(self) -> ArtifactManifest:
        return self.runtime_state_store.artifact_manifest

    @property
    def artifacts_ready(self) -> bool:
        return self.runtime_state_store.artifacts_ready

    @property
    def system_ready(self) -> bool:
        return self.runtime_state_store.system_ready


__all__ = ["SystemRuntimeManager"]
