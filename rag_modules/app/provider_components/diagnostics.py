"""Diagnostics component providers."""

from __future__ import annotations

from ...configuration.models import GraphRAGConfig
from ...runtime.stats_adapters import DefaultRuntimeStatsAccess
from ...runtime.stats_ports import RuntimeStatsAccessPort
from ..services.runtime_diagnostics_service import RuntimeDiagnosticsService


class DefaultDiagnosticsComponentProvider:
    """Default diagnostics and runtime-stats providers."""

    def provide_runtime_stats_access(
        self,
        *,
        config: GraphRAGConfig,
        existing: RuntimeStatsAccessPort | None = None,
    ) -> RuntimeStatsAccessPort:
        del config
        if existing is not None:
            return existing
        return DefaultRuntimeStatsAccess()

    def provide_runtime_diagnostics_service(
        self,
        *,
        config: GraphRAGConfig,
        existing: RuntimeDiagnosticsService | None = None,
        runtime_stats_access: RuntimeStatsAccessPort | None = None,
    ) -> RuntimeDiagnosticsService:
        if existing is not None:
            return existing
        return RuntimeDiagnosticsService(
            config,
            runtime_stats_access=runtime_stats_access,
        )


__all__ = ["DefaultDiagnosticsComponentProvider"]
