"""Initialization coordination for build and serving runtimes."""

from __future__ import annotations

from ...configuration.models import GraphRAGConfig
from ..runtime_state import BuildRuntime, ServingRuntime
from .contracts import (
    BuildRuntimeFactoryProtocol,
    ServingRuntimeLifecycleServiceProtocol,
)
from .runtime_refresh_service import ServingRuntimeRefreshService
from .shared import ProgressCallback


class RuntimeInitializationService:
    """Own runtime bootstrap sequencing outside the stateful runtime manager."""

    def __init__(
        self,
        *,
        config: GraphRAGConfig,
        build_runtime_factory: BuildRuntimeFactoryProtocol,
        serving_runtime_lifecycle_service: ServingRuntimeLifecycleServiceProtocol,
        serving_runtime_refresh_service: ServingRuntimeRefreshService | None = None,
    ) -> None:
        self.config = config
        self.build_runtime_factory = build_runtime_factory
        self.serving_runtime_lifecycle_service = serving_runtime_lifecycle_service
        self.serving_runtime_refresh_service = (
            serving_runtime_refresh_service
            or ServingRuntimeRefreshService(
                serving_runtime_lifecycle_service=serving_runtime_lifecycle_service
            )
        )

    def initialize_build_runtime(
        self,
        current_runtime: BuildRuntime | None,
        *,
        progress: ProgressCallback = None,
        neo4j_manager=None,
    ) -> BuildRuntime:
        if current_runtime and current_runtime.is_initialized() and neo4j_manager is None:
            return current_runtime
        return self.build_runtime_factory.build(
            self.config,
            neo4j_manager=neo4j_manager,
            progress=progress,
        )

    def initialize_serving_runtime(
        self,
        current_runtime: ServingRuntime | None,
        *,
        build_runtime: BuildRuntime | None = None,
        progress: ProgressCallback = None,
        query_tracer=None,
        neo4j_manager=None,
    ) -> ServingRuntime:
        if (
            current_runtime
            and current_runtime.is_initialized()
            and query_tracer is None
            and neo4j_manager is None
        ):
            return self.serving_runtime_refresh_service.prepare_existing(
                current_runtime,
                shared_runtime=build_runtime,
                progress=progress,
            )

        shared_runtime = build_runtime if build_runtime and build_runtime.is_initialized() else None
        return self.serving_runtime_lifecycle_service.build_ready(
            self.config,
            shared_runtime=shared_runtime,
            query_tracer=query_tracer,
            neo4j_manager=neo4j_manager,
            data_module=None,
            index_module=None,
            progress=progress,
        )

    def initialize_system(
        self,
        *,
        build_runtime: BuildRuntime | None,
        serving_runtime: ServingRuntime | None,
        progress: ProgressCallback = None,
        query_tracer=None,
        neo4j_manager=None,
    ) -> tuple[BuildRuntime, ServingRuntime]:
        build_runtime = self.initialize_build_runtime(
            build_runtime,
            progress=progress,
            neo4j_manager=neo4j_manager,
        )
        serving_runtime = self.initialize_serving_runtime(
            serving_runtime,
            build_runtime=build_runtime,
            progress=progress,
            query_tracer=query_tracer,
            neo4j_manager=neo4j_manager,
        )
        return build_runtime, serving_runtime


__all__ = ["RuntimeInitializationService"]
