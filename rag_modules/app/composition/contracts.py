"""Protocols for internal build/serving runtime composition collaborators."""

from __future__ import annotations

from typing import Any, Protocol

from ...configuration.models import GraphRAGConfig
from ...runtime.artifacts import ArtifactManifest
from ..diagnostics import StartupDiagnostics
from ..runtime_state import BuildRuntime, ServingRuntime
from ..runtime_view import SystemRuntime
from .shared import ProgressCallback


class BuildRuntimeFactoryProtocol(Protocol):
    """Factory capable of assembling a build runtime."""

    def build(
        self,
        config: GraphRAGConfig | None = None,
        *,
        neo4j_manager: Any | None = None,
        data_module: Any | None = None,
        index_module: Any | None = None,
        progress: ProgressCallback = None,
    ) -> BuildRuntime: ...


class BuildRuntimeExecutorProtocol(Protocol):
    """Executor capable of materializing or rebuilding build artifacts."""

    def build_knowledge_base(
        self,
        runtime: BuildRuntime,
        *,
        progress: ProgressCallback = None,
    ) -> BuildRuntime: ...

    def rebuild_knowledge_base(
        self,
        runtime: BuildRuntime,
        *,
        progress: ProgressCallback = None,
    ) -> BuildRuntime: ...


class ServingRuntimeFactoryProtocol(Protocol):
    """Factory capable of assembling a serving runtime."""

    def build(
        self,
        config: GraphRAGConfig | None = None,
        *,
        shared_runtime: BuildRuntime | None = None,
        query_tracer: Any | None = None,
        neo4j_manager: Any | None = None,
        data_module: Any | None = None,
        index_module: Any | None = None,
        progress: ProgressCallback = None,
    ) -> ServingRuntime: ...


class ServingRuntimePreparerProtocol(Protocol):
    """Preparer capable of warming a serving runtime from artifacts or shared runtime."""

    def prepare(
        self,
        runtime: ServingRuntime,
        *,
        chunks: Any | None = None,
        artifact_manifest: ArtifactManifest | None = None,
        progress: ProgressCallback = None,
        force: bool = False,
    ) -> ServingRuntime: ...

    def prepare_with_shared_runtime(
        self,
        runtime: ServingRuntime,
        *,
        shared_runtime: BuildRuntime | None = None,
        progress: ProgressCallback = None,
        force: bool = False,
    ) -> ServingRuntime: ...


class ServingRuntimeLifecycleServiceProtocol(Protocol):
    """Lifecycle coordinator capable of building and preparing a serving runtime."""

    def build_ready(
        self,
        config: GraphRAGConfig | None = None,
        *,
        shared_runtime: BuildRuntime | None = None,
        query_tracer: Any | None = None,
        neo4j_manager: Any | None = None,
        data_module: Any | None = None,
        index_module: Any | None = None,
        progress: ProgressCallback = None,
    ) -> ServingRuntime: ...

    def prepare(
        self,
        runtime: ServingRuntime,
        *,
        chunks: Any | None = None,
        artifact_manifest: ArtifactManifest | None = None,
        progress: ProgressCallback = None,
        force: bool = False,
    ) -> ServingRuntime: ...

    def prepare_with_shared_runtime(
        self,
        runtime: ServingRuntime,
        *,
        shared_runtime: BuildRuntime | None = None,
        progress: ProgressCallback = None,
        force: bool = False,
    ) -> ServingRuntime: ...


class SystemOperationsProtocol(Protocol):
    """Application-facing runtime lifecycle and diagnostics operations."""

    def initialize_build_runtime(
        self,
        *,
        progress: ProgressCallback = None,
        neo4j_manager: Any | None = None,
    ) -> BuildRuntime: ...

    def initialize_serving_runtime(
        self,
        *,
        progress: ProgressCallback = None,
        query_tracer: Any | None = None,
        neo4j_manager: Any | None = None,
    ) -> ServingRuntime: ...

    def initialize_system(
        self,
        *,
        progress: ProgressCallback = None,
        query_tracer: Any | None = None,
        neo4j_manager: Any | None = None,
    ) -> SystemRuntime: ...

    def is_initialized(self) -> bool: ...

    def is_build_initialized(self) -> bool: ...

    def is_serving_initialized(self) -> bool: ...

    def build_knowledge_base(
        self,
        *,
        progress: ProgressCallback = None,
    ) -> BuildRuntime: ...

    def rebuild_knowledge_base(
        self,
        *,
        progress: ProgressCallback = None,
    ) -> BuildRuntime: ...

    def refresh_serving_runtime(
        self,
        *,
        progress: ProgressCallback = None,
        force: bool = True,
    ) -> ServingRuntime: ...

    def collect_system_stats(self) -> dict[str, Any]: ...

    def collect_startup_diagnostics(self, mode: str) -> StartupDiagnostics: ...

    def require_ready(self) -> ServingRuntime: ...

    def close(self) -> None: ...


class SystemFacadeSupportProtocol(Protocol):
    """Runtime/public-surface adapter exposed to the thin application facade."""

    @property
    def runtime(self) -> SystemRuntime: ...

    @property
    def build_runtime(self) -> BuildRuntime | None: ...

    @property
    def serving_runtime(self) -> ServingRuntime | None: ...

    @property
    def infrastructure(self) -> Any: ...

    @property
    def retrieval(self) -> Any: ...

    @property
    def services(self) -> Any: ...

    @property
    def artifact_manifest(self) -> ArtifactManifest: ...

    @property
    def artifacts_ready(self) -> bool: ...

    @property
    def system_ready(self) -> bool: ...


__all__ = [
    "SystemFacadeSupportProtocol",
    "BuildRuntimeExecutorProtocol",
    "BuildRuntimeFactoryProtocol",
    "ServingRuntimeFactoryProtocol",
    "ServingRuntimeLifecycleServiceProtocol",
    "ServingRuntimePreparerProtocol",
    "SystemOperationsProtocol",
]
