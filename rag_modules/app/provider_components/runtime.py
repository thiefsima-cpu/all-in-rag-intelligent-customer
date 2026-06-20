"""Composite runtime provider."""

from __future__ import annotations

from .build_pipeline import DefaultBuildPipelineComponentProvider
from .diagnostics import DefaultDiagnosticsComponentProvider
from .generation import DefaultGenerationComponentProvider
from .infrastructure import DefaultInfrastructureComponentProvider
from .lifecycle import DefaultLifecycleComponentProvider
from .query_understanding import DefaultQueryUnderstandingComponentProvider
from .retrieval import DefaultRetrievalComponentProvider
from .services import DefaultApplicationServiceComponentProvider


class DefaultRuntimeComponentProvider:
    """Capability container used by the application composition root."""

    capability_names = (
        "infrastructure",
        "build_pipeline",
        "diagnostics",
        "lifecycle",
        "generation",
        "query_understanding",
        "retrieval",
        "services",
    )

    def __init__(
        self,
        *,
        infrastructure=None,
        build_pipeline=None,
        diagnostics=None,
        lifecycle=None,
        generation=None,
        query_understanding=None,
        retrieval=None,
        services=None,
    ) -> None:
        self.infrastructure = infrastructure or DefaultInfrastructureComponentProvider()
        self.build_pipeline = build_pipeline or DefaultBuildPipelineComponentProvider()
        self.diagnostics = diagnostics or DefaultDiagnosticsComponentProvider()
        self.lifecycle = lifecycle or DefaultLifecycleComponentProvider()
        self.generation = generation or DefaultGenerationComponentProvider()
        self.query_understanding = (
            query_understanding or DefaultQueryUnderstandingComponentProvider()
        )
        self.retrieval = retrieval or DefaultRetrievalComponentProvider()
        self.services = services or DefaultApplicationServiceComponentProvider()

    @property
    def provider(self) -> "DefaultRuntimeComponentProvider":
        """Allow the capability container to act as its own resolved surface."""

        return self


__all__ = ["DefaultRuntimeComponentProvider"]
