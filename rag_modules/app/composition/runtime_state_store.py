"""Centralized runtime state and snapshot access for build and serving lifecycles."""

from __future__ import annotations

from ...runtime.artifacts import ArtifactManifest
from ..runtime_state import BuildRuntime, ServingRuntime
from ..runtime_view import SystemRuntime


class RuntimeStateStore:
    """Own the active build/serving runtimes and the derived unified runtime view."""

    def __init__(
        self,
        *,
        build_runtime: BuildRuntime | None = None,
        serving_runtime: ServingRuntime | None = None,
    ) -> None:
        self._build_runtime = build_runtime
        self._serving_runtime = serving_runtime
        self._runtime = self._compose_runtime()

    @property
    def build_runtime(self) -> BuildRuntime | None:
        return self._build_runtime

    @build_runtime.setter
    def build_runtime(self, runtime: BuildRuntime | None) -> None:
        self._build_runtime = runtime
        self._runtime = self._compose_runtime()

    @property
    def serving_runtime(self) -> ServingRuntime | None:
        return self._serving_runtime

    @serving_runtime.setter
    def serving_runtime(self, runtime: ServingRuntime | None) -> None:
        self._serving_runtime = runtime
        self._runtime = self._compose_runtime()

    @property
    def runtime(self) -> SystemRuntime:
        return self._runtime

    def replace(
        self,
        *,
        build_runtime: BuildRuntime | None,
        serving_runtime: ServingRuntime | None,
    ) -> SystemRuntime:
        self._build_runtime = build_runtime
        self._serving_runtime = serving_runtime
        self._runtime = self._compose_runtime()
        return self._runtime

    def refresh(self) -> SystemRuntime:
        self._runtime = self._compose_runtime()
        return self._runtime

    def clear(self) -> SystemRuntime:
        self._build_runtime = None
        self._serving_runtime = None
        self._runtime = self._compose_runtime()
        return self._runtime

    def runtime_view(self) -> SystemRuntime:
        return self._runtime

    @property
    def artifact_manifest(self) -> ArtifactManifest:
        return self._runtime.artifact_manifest

    @property
    def artifacts_ready(self) -> bool:
        return self._runtime.artifacts_ready

    @property
    def system_ready(self) -> bool:
        return self._runtime.system_ready

    def is_initialized(self) -> bool:
        return self._runtime.is_initialized()

    def _compose_runtime(self) -> SystemRuntime:
        return SystemRuntime(
            build_runtime=self._build_runtime,
            serving_runtime=self._serving_runtime,
        )


__all__ = ["RuntimeStateStore"]
