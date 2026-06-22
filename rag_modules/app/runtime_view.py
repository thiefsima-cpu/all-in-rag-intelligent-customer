"""Runtime view over build and serving state."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from ..configuration.models import GraphRAGConfig
from ..runtime.artifacts import ArtifactManifest
from .runtime_state import BuildRuntime, ServingRuntime
from .runtime_view_builder import SystemRuntimeViewBuilder
from .runtime_views import (
    SystemInfrastructureView,
    SystemRetrievalView,
    SystemServicesView,
)


@dataclass
class SystemRuntime:
    """Unified runtime view that exposes build and serving state under one surface."""

    build_runtime: Optional[BuildRuntime] = None
    serving_runtime: Optional[ServingRuntime] = None
    _view_builder: SystemRuntimeViewBuilder = field(
        default_factory=SystemRuntimeViewBuilder,
        init=False,
        repr=False,
        compare=False,
    )
    _infrastructure_view: SystemInfrastructureView | None = field(
        default=None,
        init=False,
        repr=False,
        compare=False,
    )
    _retrieval_view: SystemRetrievalView | None = field(
        default=None,
        init=False,
        repr=False,
        compare=False,
    )
    _services_view: SystemServicesView | None = field(
        default=None,
        init=False,
        repr=False,
        compare=False,
    )

    def is_initialized(self) -> bool:
        return bool(
            (self.build_runtime and self.build_runtime.is_initialized())
            or (self.serving_runtime and self.serving_runtime.is_initialized())
        )

    @property
    def config(self) -> Optional[GraphRAGConfig]:
        if self.serving_runtime:
            return self.serving_runtime.config
        if self.build_runtime:
            return self.build_runtime.config
        return None

    @property
    def artifact_manifest(self) -> ArtifactManifest:
        if self.build_runtime:
            return self.build_runtime.artifact_manifest
        if self.serving_runtime:
            return self.serving_runtime.artifact_manifest
        return ArtifactManifest()

    @property
    def artifacts_ready(self) -> bool:
        return bool(self.artifact_manifest and self.artifact_manifest.is_ready)

    @property
    def system_ready(self) -> bool:
        return bool(self.serving_runtime and self.serving_runtime.system_ready)

    @property
    def infrastructure(self) -> SystemInfrastructureView:
        if self._infrastructure_view is None:
            self._infrastructure_view = self._view_builder.build_infrastructure_view(
                build_runtime=self.build_runtime,
                serving_runtime=self.serving_runtime,
            )
        return self._infrastructure_view

    @property
    def retrieval(self) -> SystemRetrievalView:
        if self._retrieval_view is None:
            self._retrieval_view = self._view_builder.build_retrieval_view(
                serving_runtime=self.serving_runtime,
            )
        return self._retrieval_view

    @property
    def services(self) -> SystemServicesView:
        if self._services_view is None:
            self._services_view = self._view_builder.build_services_view(
                build_runtime=self.build_runtime,
                serving_runtime=self.serving_runtime,
            )
        return self._services_view


__all__ = [
    "SystemInfrastructureView",
    "SystemRetrievalView",
    "SystemRuntime",
    "SystemServicesView",
]
