"""Resolve runtime providers and their capability-specific surfaces."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from ..provider_components.contracts import (
    ApplicationServiceComponentProvider,
    BuildPipelineComponentProvider,
    DiagnosticsComponentProvider,
    GenerationComponentProvider,
    InfrastructureComponentProvider,
    LifecycleComponentProvider,
    QueryUnderstandingComponentProvider,
    RetrievalComponentProvider,
    RuntimeComponentProvider,
)
def _create_default_runtime_provider() -> RuntimeComponentProvider:
    from ..provider_components.runtime import DefaultRuntimeComponentProvider

    return DefaultRuntimeComponentProvider()


class RuntimeComponentProviderResolver:
    """Resolve a runtime provider from explicit inputs before falling back to defaults."""

    def __init__(
        self,
        *,
        default_provider_factory: Callable[[], RuntimeComponentProvider] | None = None,
    ) -> None:
        self.default_provider_factory = (
            default_provider_factory or _create_default_runtime_provider
        )

    def resolve(
        self,
        *,
        provider: RuntimeComponentProvider | None = None,
        bootstrapper=None,
        build_bootstrapper=None,
        serving_bootstrapper=None,
    ) -> RuntimeComponentProvider:
        for candidate in (
            provider,
            getattr(bootstrapper, "provider", None),
            getattr(build_bootstrapper, "provider", None),
            getattr(serving_bootstrapper, "provider", None),
        ):
            if candidate is not None:
                return candidate
        return self.default_provider_factory()


@dataclass(frozen=True)
class RuntimeProviderSurface:
    """Resolved provider plus all capability-specific provider facets."""

    provider: RuntimeComponentProvider
    infrastructure: InfrastructureComponentProvider
    build_pipeline: BuildPipelineComponentProvider
    diagnostics: DiagnosticsComponentProvider
    lifecycle: LifecycleComponentProvider
    generation: GenerationComponentProvider
    query_understanding: QueryUnderstandingComponentProvider
    retrieval: RetrievalComponentProvider
    services: ApplicationServiceComponentProvider

    @classmethod
    def from_provider(
        cls,
        provider: RuntimeComponentProvider,
    ) -> "RuntimeProviderSurface":
        def capability(name: str):
            return getattr(provider, name, provider)

        return cls(
            provider=provider,
            infrastructure=capability("infrastructure"),
            build_pipeline=capability("build_pipeline"),
            diagnostics=capability("diagnostics"),
            lifecycle=capability("lifecycle"),
            generation=capability("generation"),
            query_understanding=capability("query_understanding"),
            retrieval=capability("retrieval"),
            services=capability("services"),
        )


class RuntimeProviderSurfaceResolver:
    """Resolve a stable runtime-provider surface from explicit or inherited inputs."""

    def resolve(
        self,
        *,
        provider: RuntimeComponentProvider | None = None,
        bootstrapper=None,
        build_bootstrapper=None,
        serving_bootstrapper=None,
        provider_resolver: RuntimeComponentProviderResolver | None = None,
    ) -> RuntimeProviderSurface:
        resolved_provider = (
            provider_resolver or RuntimeComponentProviderResolver()
        ).resolve(
            provider=provider,
            bootstrapper=bootstrapper,
            build_bootstrapper=build_bootstrapper,
            serving_bootstrapper=serving_bootstrapper,
        )
        return RuntimeProviderSurface.from_provider(resolved_provider)


__all__ = [
    "RuntimeComponentProviderResolver",
    "RuntimeProviderSurface",
    "RuntimeProviderSurfaceResolver",
]
