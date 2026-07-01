"""Default runtime provider facade for application assembly."""

from __future__ import annotations

from ...configuration.models import GraphRAGConfig
from ...generation.service import GenerationWorkflowService
from ...observability.tracing_sinks import QueryTraceSinkFactory
from ...retrieval.runtime_profile import RetrievalRuntimeProfileFactory
from .build_pipeline import _DefaultBuildPipelineProvider
from .contracts import (
    ApplicationServiceProvider,
    BuildPipelineProvider,
    InfrastructureProvider,
    RetrievalRuntimeProvider,
    RuntimeComponentProvider,
)
from .generation import _DefaultGenerationProvider
from .infrastructure import _DefaultInfrastructureProvider
from .retrieval_runtime import _DefaultRetrievalRuntimeProvider
from .services import _DefaultApplicationServiceProvider


class DefaultRuntimeProvider:
    """Default provider used by application composition."""

    def __init__(
        self,
        *,
        infrastructure: InfrastructureProvider | None = None,
        build_pipeline: BuildPipelineProvider | None = None,
        retrieval_runtime: RetrievalRuntimeProvider | None = None,
        services: ApplicationServiceProvider | None = None,
        query_trace_sink_factory: QueryTraceSinkFactory | None = None,
        retrieval_profile_factory: RetrievalRuntimeProfileFactory | None = None,
    ) -> None:
        self.infrastructure = infrastructure or _DefaultInfrastructureProvider(
            query_trace_sink_factory=query_trace_sink_factory,
        )
        self.build_pipeline = build_pipeline or _DefaultBuildPipelineProvider()
        self.retrieval_runtime = retrieval_runtime or _DefaultRetrievalRuntimeProvider(
            profile_factory=retrieval_profile_factory,
        )
        self.services = services or _DefaultApplicationServiceProvider()
        self._generation = _DefaultGenerationProvider()

    def provide_generation_module(self, config: GraphRAGConfig) -> GenerationWorkflowService:
        return self._generation.provide_generation_module(config)

    @property
    def provider(self) -> "DefaultRuntimeProvider":
        return self


def create_default_runtime_provider() -> RuntimeComponentProvider:
    """Create the default runtime provider through the app facade."""

    return DefaultRuntimeProvider()


__all__ = [
    "DefaultRuntimeProvider",
    "create_default_runtime_provider",
]
