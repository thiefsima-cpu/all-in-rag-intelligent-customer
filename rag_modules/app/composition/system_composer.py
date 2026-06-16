"""Compose the application system facade and its immediate collaborators."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from ...configuration import get_default_config
from ...configuration.models import GraphRAGConfig
from ..services.answer_models import QuestionAnswerer
from ..services.runtime_diagnostics_service import RuntimeDiagnosticsService
from ..services.runtime_shutdown_service import RuntimeShutdownService
from .bootstrapper_composer import GraphRAGBootstrapperComposer
from .contracts import (
    SystemFacadeSupportProtocol,
    SystemOperationsBackendProtocol,
    SystemOperationsProtocol,
)
from .provider_resolution import (
    RuntimeProviderSurface,
    RuntimeProviderSurfaceResolver,
)
from .runtime_lifecycle_service_composer import (
    RuntimeLifecycleServiceBundle,
    RuntimeLifecycleServiceComposer,
)
from .runtime_manager import SystemRuntimeManager
from .runtime_state_store import RuntimeStateStore
from .system_answering_service import SystemAnsweringService
from .system_facade_support import SystemFacadeSupport
from .system_operations_service import SystemOperationsService

if TYPE_CHECKING:
    from ..bootstrap import BuildBootstrapper, GraphRAGBootstrapper, ServingBootstrapper
    from ..provider_components.contracts import RuntimeComponentProvider


@dataclass(frozen=True)
class AdvancedGraphRAGBootstrapperSurface:
    """Resolved bootstrapper facade surface for application assembly."""

    provider_surface: RuntimeProviderSurface
    bootstrapper: "GraphRAGBootstrapper"
    build_bootstrapper: "BuildBootstrapper"
    serving_bootstrapper: "ServingBootstrapper"


class SystemBootstrapperSurfaceComposer:
    """Resolve or compose the public bootstrapper surface."""

    def compose(
        self,
        *,
        provider: "RuntimeComponentProvider" | None = None,
        bootstrapper=None,
        build_bootstrapper=None,
        serving_bootstrapper=None,
        bootstrapper_composer: GraphRAGBootstrapperComposer | None = None,
        provider_surface_resolver: RuntimeProviderSurfaceResolver | None = None,
    ) -> AdvancedGraphRAGBootstrapperSurface:
        provider_surface = (
            provider_surface_resolver or RuntimeProviderSurfaceResolver()
        ).resolve(
            provider=provider,
            bootstrapper=bootstrapper,
            build_bootstrapper=build_bootstrapper,
            serving_bootstrapper=serving_bootstrapper,
        )
        if bootstrapper is None:
            from ..bootstrap import GraphRAGBootstrapper

            bootstrapper = GraphRAGBootstrapper(
                provider=provider_surface.provider,
                build_bootstrapper=build_bootstrapper,
                serving_bootstrapper=serving_bootstrapper,
                bootstrapper_composer=bootstrapper_composer,
            )
        return AdvancedGraphRAGBootstrapperSurface(
            provider_surface=provider_surface,
            bootstrapper=bootstrapper,
            build_bootstrapper=bootstrapper.build_bootstrapper,
            serving_bootstrapper=bootstrapper.serving_bootstrapper,
        )


@dataclass(frozen=True)
class SystemRuntimeInfrastructure:
    """Runtime infrastructure resolved for the application system facade."""

    diagnostics_service: RuntimeDiagnosticsService
    shutdown_service: RuntimeShutdownService
    runtime_state_store: RuntimeStateStore
    runtime_manager: SystemRuntimeManager


class SystemRuntimeInfrastructureComposer:
    """Resolve provider-backed runtime services and assemble the runtime manager."""

    def compose(
        self,
        *,
        config: GraphRAGConfig,
        provider_surface: RuntimeProviderSurface,
        lifecycle_services: RuntimeLifecycleServiceBundle,
        diagnostics_service: RuntimeDiagnosticsService | None = None,
        shutdown_service: RuntimeShutdownService | None = None,
        runtime_state_store: RuntimeStateStore | None = None,
        runtime_manager: SystemRuntimeManager | None = None,
    ) -> SystemRuntimeInfrastructure:
        runtime_stats_access = provider_surface.diagnostics.provide_runtime_stats_access(
            config=config,
        )
        diagnostics_service = diagnostics_service or (
            provider_surface.diagnostics.provide_runtime_diagnostics_service(
                config=config,
                runtime_stats_access=runtime_stats_access,
            )
        )
        shutdown_service = shutdown_service or (
            provider_surface.lifecycle.provide_runtime_shutdown_service(config=config)
        )
        runtime_state_store = runtime_state_store or RuntimeStateStore()
        runtime_manager = runtime_manager or SystemRuntimeManager(
            config=config,
            diagnostics_service=diagnostics_service,
            shutdown_service=shutdown_service,
            lifecycle_services=lifecycle_services,
            runtime_state_store=runtime_state_store,
        )
        return SystemRuntimeInfrastructure(
            diagnostics_service=diagnostics_service,
            shutdown_service=shutdown_service,
            runtime_state_store=runtime_state_store,
            runtime_manager=runtime_manager,
        )


@dataclass(frozen=True)
class SystemApplicationServices:
    """Application-facing services resolved for the public system facade."""

    operations_service: SystemOperationsProtocol
    answering_service: QuestionAnswerer
    facade_support: SystemFacadeSupportProtocol


class SystemApplicationServiceComposer:
    """Assemble application-facing services from runtime-backed collaborators."""

    def compose(
        self,
        *,
        runtime_backend: SystemOperationsBackendProtocol,
        runtime_state_store: RuntimeStateStore,
        operations_service: SystemOperationsProtocol | None = None,
        answering_service: QuestionAnswerer | None = None,
        facade_support: SystemFacadeSupportProtocol | None = None,
    ) -> SystemApplicationServices:
        operations_service = operations_service or SystemOperationsService(
            backend=runtime_backend,
        )
        answering_service = answering_service or SystemAnsweringService(
            backend=runtime_backend,
            runtime_state_store=runtime_state_store,
        )
        facade_support = facade_support or SystemFacadeSupport(
            runtime_state_store=runtime_state_store,
        )
        return SystemApplicationServices(
            operations_service=operations_service,
            answering_service=answering_service,
            facade_support=facade_support,
        )


@dataclass(frozen=True)
class AdvancedGraphRAGSystemComponents:
    """Resolved collaborators for the application system facade."""

    config: GraphRAGConfig
    provider: RuntimeComponentProvider
    provider_surface: RuntimeProviderSurface
    bootstrapper: "GraphRAGBootstrapper"
    build_bootstrapper: "BuildBootstrapper"
    serving_bootstrapper: "ServingBootstrapper"
    diagnostics_service: RuntimeDiagnosticsService
    shutdown_service: RuntimeShutdownService
    lifecycle_services: RuntimeLifecycleServiceBundle
    runtime_state_store: RuntimeStateStore
    operations_service: SystemOperationsProtocol
    answering_service: QuestionAnswerer
    facade_support: SystemFacadeSupportProtocol


class AdvancedGraphRAGSystemComposer:
    """Resolve inputs and assemble the application system facade."""

    def resolve_bootstrapper_surface(
        self,
        *,
        provider: RuntimeComponentProvider | None = None,
        bootstrapper=None,
        build_bootstrapper=None,
        serving_bootstrapper=None,
        bootstrapper_composer: GraphRAGBootstrapperComposer | None = None,
        provider_surface_resolver: RuntimeProviderSurfaceResolver | None = None,
        bootstrapper_surface_composer: SystemBootstrapperSurfaceComposer | None = None,
    ) -> AdvancedGraphRAGBootstrapperSurface:
        return (
            bootstrapper_surface_composer or SystemBootstrapperSurfaceComposer()
        ).compose(
            provider=provider,
            bootstrapper=bootstrapper,
            build_bootstrapper=build_bootstrapper,
            serving_bootstrapper=serving_bootstrapper,
            bootstrapper_composer=bootstrapper_composer,
            provider_surface_resolver=provider_surface_resolver,
        )

    def compose(
        self,
        config: GraphRAGConfig | None = None,
        *,
        provider: RuntimeComponentProvider | None = None,
        bootstrapper=None,
        build_bootstrapper=None,
        serving_bootstrapper=None,
        bootstrapper_composer: GraphRAGBootstrapperComposer | None = None,
        provider_surface_resolver: RuntimeProviderSurfaceResolver | None = None,
        bootstrapper_surface_composer: SystemBootstrapperSurfaceComposer | None = None,
        diagnostics_service: RuntimeDiagnosticsService | None = None,
        shutdown_service: RuntimeShutdownService | None = None,
        lifecycle_services: RuntimeLifecycleServiceBundle | None = None,
        lifecycle_service_composer: RuntimeLifecycleServiceComposer | None = None,
        runtime_infrastructure_composer: SystemRuntimeInfrastructureComposer | None = None,
        application_service_composer: SystemApplicationServiceComposer | None = None,
        runtime_state_store: RuntimeStateStore | None = None,
        operations_service: SystemOperationsProtocol | None = None,
        answering_service: QuestionAnswerer | None = None,
        facade_support: SystemFacadeSupportProtocol | None = None,
        runtime_manager: SystemRuntimeManager | None = None,
    ) -> AdvancedGraphRAGSystemComponents:
        resolved_config = config or get_default_config()
        bootstrapper_surface = self.resolve_bootstrapper_surface(
            provider=provider,
            bootstrapper=bootstrapper,
            build_bootstrapper=build_bootstrapper,
            serving_bootstrapper=serving_bootstrapper,
            bootstrapper_composer=bootstrapper_composer,
            provider_surface_resolver=provider_surface_resolver,
            bootstrapper_surface_composer=bootstrapper_surface_composer,
        )
        lifecycle_services = lifecycle_services or (
            lifecycle_service_composer or RuntimeLifecycleServiceComposer()
        ).compose(
            config=resolved_config,
            build_bootstrapper=bootstrapper_surface.build_bootstrapper,
            serving_bootstrapper=bootstrapper_surface.serving_bootstrapper,
        )
        runtime_infrastructure = (
            runtime_infrastructure_composer or SystemRuntimeInfrastructureComposer()
        ).compose(
            config=resolved_config,
            provider_surface=bootstrapper_surface.provider_surface,
            lifecycle_services=lifecycle_services,
            diagnostics_service=diagnostics_service,
            shutdown_service=shutdown_service,
            runtime_state_store=runtime_state_store,
            runtime_manager=runtime_manager,
        )
        application_services = (
            application_service_composer or SystemApplicationServiceComposer()
        ).compose(
            runtime_backend=runtime_infrastructure.runtime_manager,
            runtime_state_store=runtime_infrastructure.runtime_state_store,
            operations_service=operations_service,
            answering_service=answering_service,
            facade_support=facade_support,
        )
        return AdvancedGraphRAGSystemComponents(
            config=resolved_config,
            provider=bootstrapper_surface.provider_surface.provider,
            provider_surface=bootstrapper_surface.provider_surface,
            bootstrapper=bootstrapper_surface.bootstrapper,
            build_bootstrapper=bootstrapper_surface.build_bootstrapper,
            serving_bootstrapper=bootstrapper_surface.serving_bootstrapper,
            diagnostics_service=runtime_infrastructure.diagnostics_service,
            shutdown_service=runtime_infrastructure.shutdown_service,
            lifecycle_services=lifecycle_services,
            runtime_state_store=runtime_infrastructure.runtime_state_store,
            operations_service=application_services.operations_service,
            answering_service=application_services.answering_service,
            facade_support=application_services.facade_support,
        )


__all__ = [
    "AdvancedGraphRAGBootstrapperSurface",
    "AdvancedGraphRAGSystemComponents",
    "AdvancedGraphRAGSystemComposer",
    "SystemApplicationServiceComposer",
    "SystemApplicationServices",
    "SystemBootstrapperSurfaceComposer",
    "SystemRuntimeInfrastructure",
    "SystemRuntimeInfrastructureComposer",
]
