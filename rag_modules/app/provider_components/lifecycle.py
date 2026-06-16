"""Lifecycle component providers."""

from __future__ import annotations

from ..services.runtime_shutdown_service import RuntimeShutdownService


class DefaultLifecycleComponentProvider:
    """Default runtime lifecycle providers."""

    def provide_runtime_shutdown_service(
        self,
        *,
        config,
        existing: RuntimeShutdownService | None = None,
    ) -> RuntimeShutdownService:
        del config
        if existing is not None:
            return existing
        return RuntimeShutdownService()


__all__ = ["DefaultLifecycleComponentProvider"]
