"""One-shot system bootstrap over build and serving composition services."""

from __future__ import annotations

from ...configuration.models import GraphRAGConfig
from ..runtime_view import SystemRuntime
from .contracts import BuildRuntimeFactoryProtocol, ServingRuntimeLifecycleServiceProtocol
from .shared import ProgressCallback


class SystemRuntimeBootstrapService:
    """Build a ready system runtime without routing through public bootstrapper logic."""

    def __init__(
        self,
        *,
        build_runtime_factory: BuildRuntimeFactoryProtocol,
        serving_runtime_lifecycle_service: ServingRuntimeLifecycleServiceProtocol,
    ) -> None:
        self.build_runtime_factory = build_runtime_factory
        self.serving_runtime_lifecycle_service = serving_runtime_lifecycle_service

    def build(
        self,
        config: GraphRAGConfig | None = None,
        *,
        query_tracer=None,
        neo4j_manager=None,
        progress: ProgressCallback = None,
    ) -> SystemRuntime:
        build_runtime = self.build_runtime_factory.build(
            config,
            neo4j_manager=neo4j_manager,
            progress=progress,
        )
        serving_runtime = self.serving_runtime_lifecycle_service.build_ready(
            config,
            shared_runtime=build_runtime,
            query_tracer=query_tracer,
            progress=progress,
        )
        return SystemRuntime(
            build_runtime=build_runtime,
            serving_runtime=serving_runtime,
        )


__all__ = ["SystemRuntimeBootstrapService"]
