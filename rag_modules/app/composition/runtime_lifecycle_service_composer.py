"""Compose lifecycle services from public bootstrappers or lower-level collaborators."""

from __future__ import annotations

from dataclasses import dataclass

from ...configuration.models import GraphRAGConfig
from .build_runtime_lifecycle_service import BuildRuntimeLifecycleService
from .contracts import (
    BuildRuntimeExecutorProtocol,
    BuildRuntimeFactoryProtocol,
    ServingRuntimeFactoryProtocol,
    ServingRuntimeLifecycleServiceProtocol,
    ServingRuntimePreparerProtocol,
)
from .runtime_initialization_service import RuntimeInitializationService
from .runtime_readiness_service import RuntimeReadinessService
from .serving_runtime_lifecycle_service import ServingRuntimeLifecycleService


@dataclass(frozen=True)
class RuntimeBootstrapperComponents:
    """Adapted runtime collaborators resolved from public bootstrapper surfaces."""

    build_runtime_factory: BuildRuntimeFactoryProtocol
    build_runtime_executor: BuildRuntimeExecutorProtocol
    serving_runtime_factory: ServingRuntimeFactoryProtocol
    serving_runtime_preparer: ServingRuntimePreparerProtocol
    serving_runtime_lifecycle_service: ServingRuntimeLifecycleServiceProtocol


@dataclass(frozen=True)
class RuntimeLifecycleServiceBundle:
    """Lifecycle services wired for a runtime manager instance."""

    initialization_service: RuntimeInitializationService
    readiness_service: RuntimeReadinessService
    serving_lifecycle_service: ServingRuntimeLifecycleServiceProtocol
    build_lifecycle_service: BuildRuntimeLifecycleService


class RuntimeLifecycleServiceComposer:
    """Adapt bootstrapper collaborators and compose the internal lifecycle service bundle."""

    def adapt_bootstrappers(
        self,
        *,
        build_bootstrapper,
        serving_bootstrapper,
    ) -> RuntimeBootstrapperComponents:
        build_runtime_factory = getattr(build_bootstrapper, "factory", build_bootstrapper)
        build_runtime_executor = getattr(build_bootstrapper, "executor", build_bootstrapper)
        serving_runtime_factory = getattr(serving_bootstrapper, "factory", serving_bootstrapper)
        serving_runtime_preparer = getattr(serving_bootstrapper, "preparer", serving_bootstrapper)
        serving_runtime_lifecycle_service = getattr(
            serving_bootstrapper,
            "lifecycle_service",
            None,
        ) or ServingRuntimeLifecycleService(
            serving_runtime_factory=serving_runtime_factory,
            serving_runtime_preparer=serving_runtime_preparer,
        )
        return RuntimeBootstrapperComponents(
            build_runtime_factory=build_runtime_factory,
            build_runtime_executor=build_runtime_executor,
            serving_runtime_factory=serving_runtime_factory,
            serving_runtime_preparer=serving_runtime_preparer,
            serving_runtime_lifecycle_service=serving_runtime_lifecycle_service,
        )

    def compose(
        self,
        *,
        config: GraphRAGConfig,
        build_bootstrapper,
        serving_bootstrapper,
        initialization_service: RuntimeInitializationService | None = None,
        readiness_service: RuntimeReadinessService | None = None,
        build_lifecycle_service: BuildRuntimeLifecycleService | None = None,
    ) -> RuntimeLifecycleServiceBundle:
        components = self.adapt_bootstrappers(
            build_bootstrapper=build_bootstrapper,
            serving_bootstrapper=serving_bootstrapper,
        )
        readiness_service = readiness_service or RuntimeReadinessService()
        initialization_service = initialization_service or RuntimeInitializationService(
            config=config,
            build_runtime_factory=components.build_runtime_factory,
            serving_runtime_lifecycle_service=components.serving_runtime_lifecycle_service,
        )
        build_lifecycle_service = build_lifecycle_service or BuildRuntimeLifecycleService(
            build_runtime_executor=components.build_runtime_executor,
            serving_lifecycle_service=components.serving_runtime_lifecycle_service,
            readiness_service=readiness_service,
        )
        return RuntimeLifecycleServiceBundle(
            initialization_service=initialization_service,
            readiness_service=readiness_service,
            serving_lifecycle_service=components.serving_runtime_lifecycle_service,
            build_lifecycle_service=build_lifecycle_service,
        )


__all__ = [
    "RuntimeBootstrapperComponents",
    "RuntimeLifecycleServiceBundle",
    "RuntimeLifecycleServiceComposer",
]
