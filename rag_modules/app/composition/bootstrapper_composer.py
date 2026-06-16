"""Compose build, serving, and graph bootstrapper facades."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from ..provider_components.contracts import RuntimeComponentProvider
from .build_runtime_executor import BuildRuntimeExecutor
from .build_runtime_factory import BuildRuntimeFactory
from .contracts import (
    BuildRuntimeExecutorProtocol,
    BuildRuntimeFactoryProtocol,
    ServingRuntimeFactoryProtocol,
    ServingRuntimeLifecycleServiceProtocol,
    ServingRuntimePreparerProtocol,
)
from .provider_resolution import RuntimeComponentProviderResolver
from .runtime_lifecycle_service_composer import RuntimeLifecycleServiceComposer
from .serving_runtime_factory import ServingRuntimeFactory
from .serving_runtime_lifecycle_service import ServingRuntimeLifecycleService
from .serving_runtime_preparer import ServingRuntimePreparer
from .system_runtime_bootstrap_service import SystemRuntimeBootstrapService

if TYPE_CHECKING:
    from ..bootstrap import BuildBootstrapper, ServingBootstrapper


@dataclass(frozen=True)
class BuildBootstrapperComponents:
    """Resolved collaborators required by the public build bootstrapper facade."""

    provider: RuntimeComponentProvider
    factory: BuildRuntimeFactoryProtocol
    executor: BuildRuntimeExecutorProtocol


class BuildBootstrapperComposer:
    """Assemble the build bootstrapper surface from explicit collaborators only."""

    def compose(
        self,
        *,
        provider: RuntimeComponentProvider | None = None,
        factory: BuildRuntimeFactoryProtocol | None = None,
        executor: BuildRuntimeExecutorProtocol | None = None,
        provider_resolver: RuntimeComponentProviderResolver | None = None,
    ) -> BuildBootstrapperComponents:
        resolved_provider = (
            provider_resolver or RuntimeComponentProviderResolver()
        ).resolve(provider=provider)
        return BuildBootstrapperComponents(
            provider=resolved_provider,
            factory=factory or BuildRuntimeFactory(provider=resolved_provider),
            executor=executor or BuildRuntimeExecutor(),
        )


@dataclass(frozen=True)
class ServingBootstrapperComponents:
    """Resolved collaborators required by the public serving bootstrapper facade."""

    provider: RuntimeComponentProvider
    factory: ServingRuntimeFactoryProtocol
    preparer: ServingRuntimePreparerProtocol
    lifecycle_service: ServingRuntimeLifecycleServiceProtocol


class ServingBootstrapperComposer:
    """Assemble the serving bootstrapper surface from explicit collaborators only."""

    def compose(
        self,
        *,
        provider: RuntimeComponentProvider | None = None,
        factory: ServingRuntimeFactoryProtocol | None = None,
        preparer: ServingRuntimePreparerProtocol | None = None,
        lifecycle_service: ServingRuntimeLifecycleServiceProtocol | None = None,
        provider_resolver: RuntimeComponentProviderResolver | None = None,
    ) -> ServingBootstrapperComponents:
        resolved_provider = (
            provider_resolver or RuntimeComponentProviderResolver()
        ).resolve(provider=provider)
        resolved_factory = factory or ServingRuntimeFactory(provider=resolved_provider)
        resolved_preparer = preparer or ServingRuntimePreparer(provider=resolved_provider)
        resolved_lifecycle_service = lifecycle_service or ServingRuntimeLifecycleService(
            serving_runtime_factory=resolved_factory,
            serving_runtime_preparer=resolved_preparer,
        )
        return ServingBootstrapperComponents(
            provider=resolved_provider,
            factory=resolved_factory,
            preparer=resolved_preparer,
            lifecycle_service=resolved_lifecycle_service,
        )


@dataclass(frozen=True)
class GraphBootstrapperSurface:
    """Resolved provider plus split public bootstrappers."""

    provider: RuntimeComponentProvider
    build_bootstrapper: "BuildBootstrapper"
    serving_bootstrapper: "ServingBootstrapper"


class GraphBootstrapperSurfaceComposer:
    """Resolve or compose the split bootstrapper surface."""

    def compose(
        self,
        *,
        provider: RuntimeComponentProvider | None = None,
        build_bootstrapper=None,
        serving_bootstrapper=None,
        provider_resolver: RuntimeComponentProviderResolver | None = None,
    ) -> GraphBootstrapperSurface:
        resolver = provider_resolver or RuntimeComponentProviderResolver()
        resolved_provider = resolver.resolve(
            provider=provider,
            build_bootstrapper=build_bootstrapper,
            serving_bootstrapper=serving_bootstrapper,
        )
        if build_bootstrapper is None or serving_bootstrapper is None:
            from ..bootstrap import BuildBootstrapper, ServingBootstrapper

            build_bootstrapper = build_bootstrapper or BuildBootstrapper(
                provider=resolved_provider,
                provider_resolver=resolver,
            )
            serving_bootstrapper = serving_bootstrapper or ServingBootstrapper(
                provider=resolved_provider,
                provider_resolver=resolver,
            )
        return GraphBootstrapperSurface(
            provider=resolved_provider,
            build_bootstrapper=build_bootstrapper,
            serving_bootstrapper=serving_bootstrapper,
        )


class SystemRuntimeBootstrapServiceComposer:
    """Assemble the one-shot bootstrap service from split bootstrappers."""

    def compose(
        self,
        *,
        build_bootstrapper,
        serving_bootstrapper,
        bootstrap_service: SystemRuntimeBootstrapService | None = None,
        lifecycle_service_composer: RuntimeLifecycleServiceComposer | None = None,
    ) -> SystemRuntimeBootstrapService:
        if bootstrap_service is not None:
            return bootstrap_service
        lifecycle_components = (
            lifecycle_service_composer or RuntimeLifecycleServiceComposer()
        ).adapt_bootstrappers(
            build_bootstrapper=build_bootstrapper,
            serving_bootstrapper=serving_bootstrapper,
        )
        return SystemRuntimeBootstrapService(
            build_runtime_factory=lifecycle_components.build_runtime_factory,
            serving_runtime_lifecycle_service=(
                lifecycle_components.serving_runtime_lifecycle_service
            ),
        )


@dataclass(frozen=True)
class GraphRAGBootstrapperComponents:
    """Resolved collaborators for the public graph bootstrapper facade."""

    provider: RuntimeComponentProvider
    build_bootstrapper: "BuildBootstrapper"
    serving_bootstrapper: "ServingBootstrapper"
    bootstrap_service: SystemRuntimeBootstrapService


class GraphRAGBootstrapperComposer:
    """Assemble the graph bootstrapper facade from explicit inputs only."""

    def compose(
        self,
        *,
        provider: RuntimeComponentProvider | None = None,
        build_bootstrapper=None,
        serving_bootstrapper=None,
        bootstrap_service: SystemRuntimeBootstrapService | None = None,
        lifecycle_service_composer: RuntimeLifecycleServiceComposer | None = None,
        provider_resolver: RuntimeComponentProviderResolver | None = None,
        bootstrapper_surface_composer: GraphBootstrapperSurfaceComposer | None = None,
        bootstrap_service_composer: SystemRuntimeBootstrapServiceComposer | None = None,
    ) -> GraphRAGBootstrapperComponents:
        bootstrapper_surface = (
            bootstrapper_surface_composer or GraphBootstrapperSurfaceComposer()
        ).compose(
            provider=provider,
            build_bootstrapper=build_bootstrapper,
            serving_bootstrapper=serving_bootstrapper,
            provider_resolver=provider_resolver,
        )
        resolved_bootstrap_service = (
            bootstrap_service_composer or SystemRuntimeBootstrapServiceComposer()
        ).compose(
            build_bootstrapper=bootstrapper_surface.build_bootstrapper,
            serving_bootstrapper=bootstrapper_surface.serving_bootstrapper,
            bootstrap_service=bootstrap_service,
            lifecycle_service_composer=lifecycle_service_composer,
        )
        return GraphRAGBootstrapperComponents(
            provider=bootstrapper_surface.provider,
            build_bootstrapper=bootstrapper_surface.build_bootstrapper,
            serving_bootstrapper=bootstrapper_surface.serving_bootstrapper,
            bootstrap_service=resolved_bootstrap_service,
        )


__all__ = [
    "BuildBootstrapperComponents",
    "BuildBootstrapperComposer",
    "GraphBootstrapperSurface",
    "GraphBootstrapperSurfaceComposer",
    "GraphRAGBootstrapperComponents",
    "GraphRAGBootstrapperComposer",
    "ServingBootstrapperComponents",
    "ServingBootstrapperComposer",
    "SystemRuntimeBootstrapServiceComposer",
]
