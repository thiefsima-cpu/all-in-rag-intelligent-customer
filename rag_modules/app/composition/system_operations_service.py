"""Application-level runtime operations over the composed system runtime manager."""

from __future__ import annotations

from ..diagnostics import StartupDiagnostics
from ..runtime_state import BuildRuntime, ServingRuntime
from ..runtime_view import SystemRuntime
from .contracts import SystemOperationsBackendProtocol
from .shared import ProgressCallback


class SystemOperationsService:
    """Delegate public runtime lifecycle and diagnostics operations to the runtime manager."""

    def __init__(self, *, backend: SystemOperationsBackendProtocol) -> None:
        self.backend = backend

    def initialize_build_runtime(
        self,
        *,
        progress: ProgressCallback = None,
        neo4j_manager=None,
    ) -> BuildRuntime:
        return self.backend.initialize_build_runtime(
            progress=progress,
            neo4j_manager=neo4j_manager,
        )

    def initialize_serving_runtime(
        self,
        *,
        progress: ProgressCallback = None,
        query_tracer=None,
        neo4j_manager=None,
    ) -> ServingRuntime:
        return self.backend.initialize_serving_runtime(
            progress=progress,
            query_tracer=query_tracer,
            neo4j_manager=neo4j_manager,
        )

    def initialize_system(
        self,
        *,
        progress: ProgressCallback = None,
        query_tracer=None,
        neo4j_manager=None,
    ) -> SystemRuntime:
        return self.backend.initialize_system(
            progress=progress,
            query_tracer=query_tracer,
            neo4j_manager=neo4j_manager,
        )

    def is_initialized(self) -> bool:
        return self.backend.is_initialized()

    def is_build_initialized(self) -> bool:
        return self.backend.is_build_initialized()

    def is_serving_initialized(self) -> bool:
        return self.backend.is_serving_initialized()

    def build_knowledge_base(self, *, progress: ProgressCallback = None) -> BuildRuntime:
        return self.backend.build_knowledge_base(progress=progress)

    def rebuild_knowledge_base(self, *, progress: ProgressCallback = None) -> BuildRuntime:
        return self.backend.rebuild_knowledge_base(progress=progress)

    def refresh_serving_runtime(
        self,
        *,
        progress: ProgressCallback = None,
        force: bool = True,
    ) -> ServingRuntime:
        return self.backend.refresh_serving_runtime(
            progress=progress,
            force=force,
        )

    def collect_system_stats(self) -> dict:
        return self.backend.collect_system_stats()

    def collect_startup_diagnostics(self, mode: str) -> StartupDiagnostics:
        return self.backend.collect_startup_diagnostics(mode)

    def require_ready(self) -> ServingRuntime:
        return self.backend.require_ready()

    def close(self) -> None:
        self.backend.close()


__all__ = ["SystemOperationsService"]
