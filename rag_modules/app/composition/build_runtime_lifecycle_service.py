"""Build-runtime lifecycle coordination plus serving-runtime refresh."""

from __future__ import annotations

from ..runtime_state import BuildRuntime, ServingRuntime
from .contracts import BuildRuntimeExecutorProtocol, ServingRuntimeLifecycleServiceProtocol
from .runtime_readiness_service import RuntimeReadinessService
from .shared import ProgressCallback


class BuildRuntimeLifecycleService:
    """Own build/rebuild flows and serving refresh outside the runtime manager."""

    def __init__(
        self,
        *,
        build_runtime_executor: BuildRuntimeExecutorProtocol,
        serving_lifecycle_service: ServingRuntimeLifecycleServiceProtocol,
        readiness_service: RuntimeReadinessService,
    ) -> None:
        self.build_runtime_executor = build_runtime_executor
        self.serving_lifecycle_service = serving_lifecycle_service
        self.readiness_service = readiness_service

    def build_knowledge_base(
        self,
        build_runtime: BuildRuntime | None,
        *,
        serving_runtime: ServingRuntime | None = None,
        progress: ProgressCallback = None,
    ) -> tuple[BuildRuntime, ServingRuntime | None]:
        build_runtime = self.readiness_service.require_build_runtime(build_runtime)
        build_runtime = self.build_runtime_executor.build_knowledge_base(
            build_runtime,
            progress=progress,
        )
        serving_runtime = self.serving_lifecycle_service.refresh_from_build(
            serving_runtime,
            build_runtime=build_runtime,
            progress=progress,
            force=True,
        )
        return build_runtime, serving_runtime

    def rebuild_knowledge_base(
        self,
        build_runtime: BuildRuntime | None,
        *,
        serving_runtime: ServingRuntime | None = None,
        progress: ProgressCallback = None,
    ) -> tuple[BuildRuntime, ServingRuntime | None]:
        build_runtime = self.readiness_service.require_build_runtime(build_runtime)
        build_runtime = self.build_runtime_executor.rebuild_knowledge_base(
            build_runtime,
            progress=progress,
        )
        serving_runtime = self.serving_lifecycle_service.refresh_from_build(
            serving_runtime,
            build_runtime=build_runtime,
            progress=progress,
            force=True,
        )
        return build_runtime, serving_runtime


__all__ = ["BuildRuntimeLifecycleService"]
