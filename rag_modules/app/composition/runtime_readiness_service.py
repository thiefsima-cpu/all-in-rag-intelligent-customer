"""Readiness and state guards for build and serving runtimes."""

from __future__ import annotations

from ..runtime_state import BuildRuntime, ServingRuntime


class RuntimeReadinessService:
    """Validate runtime state transitions without coupling callers to raw objects."""

    @staticmethod
    def is_build_initialized(runtime: BuildRuntime | None) -> bool:
        return bool(runtime and runtime.is_initialized())

    @staticmethod
    def is_serving_initialized(runtime: ServingRuntime | None) -> bool:
        return bool(runtime and runtime.is_initialized())

    def require_build_runtime(self, runtime: BuildRuntime | None) -> BuildRuntime:
        if runtime is None or not runtime.is_initialized():
            raise ValueError(
                "Build runtime is not initialized. Call initialize_build_runtime() first."
            )
        return runtime

    def require_serving_runtime(self, runtime: ServingRuntime | None) -> ServingRuntime:
        if runtime is None or not runtime.is_initialized():
            raise ValueError(
                "Serving runtime is not initialized. Call initialize_serving_runtime() first."
            )
        return runtime

    def require_ready(
        self, runtime: ServingRuntime | None, *, artifacts_ready: bool
    ) -> ServingRuntime:
        runtime = self.require_serving_runtime(runtime)
        if not artifacts_ready:
            raise ValueError(
                "Serving artifacts are not ready. Build the knowledge base first or load a valid artifact manifest."
            )
        if not runtime.system_ready:
            raise ValueError(
                "Serving runtime is not ready. Ensure the artifact manifest, cached documents, and vector collection are available."
            )
        return runtime


__all__ = ["RuntimeReadinessService"]
