"""Composite runtime provider."""

from __future__ import annotations

from typing import Any

from .build_pipeline import DefaultBuildPipelineComponentProvider
from .diagnostics import DefaultDiagnosticsComponentProvider
from .generation import DefaultGenerationComponentProvider
from .infrastructure import DefaultInfrastructureComponentProvider
from .lifecycle import DefaultLifecycleComponentProvider
from .query_understanding import DefaultQueryUnderstandingComponentProvider
from .retrieval import DefaultRetrievalComponentProvider
from .services import DefaultApplicationServiceComponentProvider


class DefaultRuntimeComponentProvider:
    """Capability container used by the application composition root.

    Capability providers are the primary API. Dynamic ``provide_*`` delegation
    keeps the former monolithic provider surface working during migration
    without duplicating every provider method here.
    """

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

    def __getattr__(self, name: str) -> Any:
        if not name.startswith("provide_"):
            raise AttributeError(name)

        for capability_name in self.capability_names:
            capability = object.__getattribute__(self, capability_name)
            provider_method = getattr(capability, name, None)
            if callable(provider_method):
                return provider_method

        if name == "provide_routing_workflow":
            legacy_method = getattr(self.retrieval, "provide_query_router", None)
            if callable(legacy_method):
                return legacy_method

        raise AttributeError(
            f"{self.__class__.__name__!s} has no provider method {name!r}."
        )


__all__ = ["DefaultRuntimeComponentProvider"]
