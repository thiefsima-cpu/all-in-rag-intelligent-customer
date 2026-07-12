"""Compose the application system facade and its immediate collaborators."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from ...application.answering.answer_models import QuestionAnswerer
from ...configuration import get_default_config
from ...configuration.models import GraphRAGConfig
from ..ports import RuntimeDiagnosticsServicePort, RuntimeShutdownServicePort
from .bootstrapper_composer import GraphRAGBootstrapperComposer
from .contracts import (
    SystemFacadeSupportProtocol,
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

if TYPE_CHECKING:
    from ..bootstrap import BuildBootstrapper, GraphRAGBootstrapper, ServingBootstrapper
    from ..providers import RuntimeComponentProvider


@dataclass(frozen=True)
class AdvancedGraphRAGBootstrapperSurface:
    """Resolved bootstrapper facade surface for application assembly."""

    provider_surface: RuntimeProviderSurface
    bootstrapper: "GraphRAGBootstrapper"
    build_bootstrapper: "BuildBootstrapper"
    serving_bootstrapper: "ServingBootstrapper"


@dataclass(frozen=True)
class SystemBootstrapperOverrides:
    """Optional bootstrapper-facing collaborators for system assembly."""

    provider: "RuntimeComponentProvider" | None = None
    bootstrapper: "GraphRAGBootstrapper" | None = None
    build_bootstrapper: "BuildBootstrapper" | None = None
    serving_bootstrapper: "ServingBootstrapper" | None = None
    bootstrapper_composer: GraphRAGBootstrapperComposer | None = None
    provider_surface_resolver: RuntimeProviderSurfaceResolver | None = None


class SystemBootstrapperSurfaceComposer:
    """Resolve or compose the public bootstrapper surface."""

    def compose(
        self,
        *,
        overrides: SystemBootstrapperOverrides | None = None,
    ) -> AdvancedGraphRAGBootstrapperSurface:
        resolved_overrides = overrides or SystemBootstrapperOverrides()
        bootstrapper = resolved_overrides.bootstrapper
        build_bootstrapper = resolved_overrides.build_bootstrapper
        serving_bootstrapper = resolved_overrides.serving_bootstrapper
        provider_surface = (
            resolved_overrides.provider_surface_resolver or RuntimeProviderSurfaceResolver()
        ).resolve(
            provider=resolved_overrides.provider,
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
                bootstrapper_composer=resolved_overrides.bootstrapper_composer,
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

    diagnostics_service: RuntimeDiagnosticsServicePort
    shutdown_service: RuntimeShutdownServicePort
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
        diagnostics_service: RuntimeDiagnosticsServicePort | None = None,
        shutdown_service: RuntimeShutdownServicePort | None = None,
        runtime_state_store: RuntimeStateStore | None = None,
        runtime_manager: SystemRuntimeManager | None = None,
    ) -> SystemRuntimeInfrastructure:
        runtime_stats_access = provider_surface.services.provide_runtime_stats_access(
            config=config,
        )
        diagnostics_service = diagnostics_service or (
            provider_surface.services.provide_runtime_diagnostics_service(
                config=config,
                runtime_stats_access=runtime_stats_access,
            )
        )
        shutdown_service = shutdown_service or (
            provider_surface.services.provide_runtime_shutdown_service(config=config)
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
class SystemRuntimeOverrides:
    """Optional runtime infrastructure collaborators for system assembly."""

    lifecycle_services: RuntimeLifecycleServiceBundle | None = None
    diagnostics_service: RuntimeDiagnosticsServicePort | None = None
    shutdown_service: RuntimeShutdownServicePort | None = None
    runtime_state_store: RuntimeStateStore | None = None
    runtime_manager: SystemRuntimeManager | None = None


@dataclass(frozen=True)
class SystemFacadeOverrides:
    """Optional facade-level collaborators for system assembly."""

    operations_service: SystemOperationsProtocol | None = None
    answering_service: QuestionAnswerer | None = None
    facade_support: SystemFacadeSupportProtocol | None = None


@dataclass(frozen=True)
class AdvancedGraphRAGSystemOverrides:
    """Grouped override bundle for composing an application system."""

    bootstrapper: SystemBootstrapperOverrides = field(default_factory=SystemBootstrapperOverrides)
    runtime: SystemRuntimeOverrides = field(default_factory=SystemRuntimeOverrides)
    facade: SystemFacadeOverrides = field(default_factory=SystemFacadeOverrides)
    bootstrapper_surface_composer: SystemBootstrapperSurfaceComposer | None = None
    lifecycle_service_composer: RuntimeLifecycleServiceComposer | None = None
    runtime_infrastructure_composer: SystemRuntimeInfrastructureComposer | None = None


@dataclass(frozen=True)
class AdvancedGraphRAGSystemComponents:
    """Resolved collaborators for the application system facade."""

    config: GraphRAGConfig
    provider: RuntimeComponentProvider
    provider_surface: RuntimeProviderSurface
    bootstrapper: "GraphRAGBootstrapper"
    build_bootstrapper: "BuildBootstrapper"
    serving_bootstrapper: "ServingBootstrapper"
    diagnostics_service: RuntimeDiagnosticsServicePort
    shutdown_service: RuntimeShutdownServicePort
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
        overrides: SystemBootstrapperOverrides | None = None,
        bootstrapper_surface_composer: SystemBootstrapperSurfaceComposer | None = None,
    ) -> AdvancedGraphRAGBootstrapperSurface:
        resolved_overrides = overrides or SystemBootstrapperOverrides()
        return (bootstrapper_surface_composer or SystemBootstrapperSurfaceComposer()).compose(
            overrides=resolved_overrides,
        )

    def compose(
        self,
        config: GraphRAGConfig | None = None,
        *,
        overrides: AdvancedGraphRAGSystemOverrides | None = None,
    ) -> AdvancedGraphRAGSystemComponents:
        resolved_config = config or get_default_config()
        resolved_overrides = overrides or AdvancedGraphRAGSystemOverrides()
        runtime_overrides = resolved_overrides.runtime
        facade_overrides = resolved_overrides.facade
        bootstrapper_surface = self.resolve_bootstrapper_surface(
            overrides=resolved_overrides.bootstrapper,
            bootstrapper_surface_composer=resolved_overrides.bootstrapper_surface_composer,
        )
        lifecycle_services = runtime_overrides.lifecycle_services or (
            resolved_overrides.lifecycle_service_composer or RuntimeLifecycleServiceComposer()
        ).compose(
            config=resolved_config,
            build_bootstrapper=bootstrapper_surface.build_bootstrapper,
            serving_bootstrapper=bootstrapper_surface.serving_bootstrapper,
        )
        runtime_infrastructure = (
            resolved_overrides.runtime_infrastructure_composer
            or SystemRuntimeInfrastructureComposer()
        ).compose(
            config=resolved_config,
            provider_surface=bootstrapper_surface.provider_surface,
            lifecycle_services=lifecycle_services,
            diagnostics_service=runtime_overrides.diagnostics_service,
            shutdown_service=runtime_overrides.shutdown_service,
            runtime_state_store=runtime_overrides.runtime_state_store,
            runtime_manager=runtime_overrides.runtime_manager,
        )
        runtime_backend = runtime_infrastructure.runtime_manager
        resolved_operations_service: SystemOperationsProtocol = (
            facade_overrides.operations_service or runtime_backend
        )
        resolved_answering_service = facade_overrides.answering_service or SystemAnsweringService(
            backend=runtime_backend,
            runtime_state_store=runtime_infrastructure.runtime_state_store,
        )
        resolved_facade_support: SystemFacadeSupportProtocol = (
            facade_overrides.facade_support
            or SystemFacadeSupport(
                runtime_state_store=runtime_infrastructure.runtime_state_store,
            )
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
            operations_service=resolved_operations_service,
            answering_service=resolved_answering_service,
            facade_support=resolved_facade_support,
        )


__all__ = [
    "AdvancedGraphRAGBootstrapperSurface",
    "AdvancedGraphRAGSystemComponents",
    "AdvancedGraphRAGSystemComposer",
    "AdvancedGraphRAGSystemOverrides",
    "SystemBootstrapperOverrides",
    "SystemBootstrapperSurfaceComposer",
    "SystemFacadeOverrides",
    "SystemRuntimeInfrastructure",
    "SystemRuntimeInfrastructureComposer",
    "SystemRuntimeOverrides",
]
