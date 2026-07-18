"""Runtime readiness guard for serving API workflows."""

from __future__ import annotations

from collections.abc import Callable

from ....app.application_protocol import GraphRAGApplication
from ....kernel.json_types import JsonObject
from .errors import SystemNotReadyError


class ServingRuntimeReadinessGuard:
    """Own serving runtime initialization and system-ready checks."""

    def __init__(
        self,
        *,
        system: GraphRAGApplication,
        ensure_runtime_initialized: Callable[..., None],
        collect_startup_diagnostics: Callable[[str], JsonObject],
        mode: str,
        state_recorder: Callable[[bool], None] | None = None,
    ) -> None:
        self.system = system
        self._ensure_runtime_initialized = ensure_runtime_initialized
        self._collect_startup_diagnostics = collect_startup_diagnostics
        self._mode = mode
        self._state_recorder = state_recorder or (lambda _ready: None)

    def ensure_initialized(self) -> None:
        self._ensure_runtime_initialized(
            is_initialized=self.system.is_serving_initialized,
            initializer=self.system.initialize_serving_runtime,
        )
        self.record_current_state()

    def record_current_state(self) -> bool:
        ready = bool(self.system.system_ready)
        self._state_recorder(ready)
        return ready

    def raise_if_system_not_ready(self) -> None:
        if self.record_current_state():
            return
        raise SystemNotReadyError(
            "Serving runtime is assembled, but required artifacts are not ready. "
            "Build the knowledge base first.",
            diagnostics=self._collect_startup_diagnostics(self._mode),
        )


__all__ = ["ServingRuntimeReadinessGuard"]
