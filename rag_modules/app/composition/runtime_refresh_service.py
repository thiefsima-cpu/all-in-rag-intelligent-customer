"""Serving-runtime refresh helpers shared by runtime-manager flows."""

from __future__ import annotations

from ..runtime_state import BuildRuntime, ServingRuntime
from .contracts import ServingRuntimeLifecycleServiceProtocol
from .shared import ProgressCallback


class ServingRuntimeRefreshService:
    """Own serving-runtime refresh and preparation semantics."""

    def __init__(
        self,
        *,
        serving_runtime_lifecycle_service: ServingRuntimeLifecycleServiceProtocol,
    ) -> None:
        self.serving_runtime_lifecycle_service = serving_runtime_lifecycle_service

    def prepare_existing(
        self,
        runtime: ServingRuntime | None,
        *,
        shared_runtime: BuildRuntime | None = None,
        progress: ProgressCallback = None,
        force: bool = False,
    ) -> ServingRuntime | None:
        if runtime is None:
            return None
        return self.serving_runtime_lifecycle_service.prepare_with_shared_runtime(
            runtime,
            shared_runtime=shared_runtime,
            progress=progress,
            force=force,
        )

    def prepare_if_needed(
        self,
        runtime: ServingRuntime,
        *,
        shared_runtime: BuildRuntime | None = None,
        progress: ProgressCallback = None,
    ) -> ServingRuntime:
        if runtime.system_ready:
            return runtime
        return self.serving_runtime_lifecycle_service.prepare_with_shared_runtime(
            runtime,
            shared_runtime=shared_runtime,
            progress=progress,
        )

    def refresh_from_build(
        self,
        runtime: ServingRuntime | None,
        *,
        build_runtime: BuildRuntime,
        progress: ProgressCallback = None,
        force: bool = False,
    ) -> ServingRuntime | None:
        if runtime is None or not runtime.is_initialized():
            return runtime
        return self.serving_runtime_lifecycle_service.prepare_with_shared_runtime(
            runtime,
            shared_runtime=build_runtime,
            progress=progress,
            force=force,
        )


__all__ = ["ServingRuntimeRefreshService"]
