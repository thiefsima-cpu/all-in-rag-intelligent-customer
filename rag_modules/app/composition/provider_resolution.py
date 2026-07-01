"""Resolve runtime providers and their capability-specific surfaces."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from ..providers import (
    ApplicationServiceProvider,
    BuildPipelineProvider,
    InfrastructureProvider,
    RetrievalRuntimeProvider,
    RuntimeComponentProvider,
    create_default_runtime_provider,
)


class RuntimeComponentProviderResolver:
    """Resolve a runtime provider from explicit inputs before falling back to defaults."""

    def __init__(
        self,
        *,
        default_provider_factory: Callable[[], RuntimeComponentProvider] | None = None,
    ) -> None:
        self.default_provider_factory = default_provider_factory or create_default_runtime_provider

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
    infrastructure: InfrastructureProvider
    build_pipeline: BuildPipelineProvider
    retrieval_runtime: RetrievalRuntimeProvider
    services: ApplicationServiceProvider

    @classmethod
    def from_provider(
        cls,
        provider: RuntimeComponentProvider,
    ) -> "RuntimeProviderSurface":
        return cls(
            provider=provider,
            infrastructure=provider.infrastructure,
            build_pipeline=provider.build_pipeline,
            retrieval_runtime=provider.retrieval_runtime,
            services=provider.services,
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
        resolved_provider = (provider_resolver or RuntimeComponentProviderResolver()).resolve(
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
