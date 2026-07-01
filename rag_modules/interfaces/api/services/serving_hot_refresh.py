"""Hot-refresh coordination for serving-runtime artifacts."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from contextlib import AbstractContextManager
from typing import TypeVar

from ....app.application_protocol import GraphRAGApplication
from ....runtime.artifacts.registry import ArtifactRegistry

_T = TypeVar("_T")


class ServingHotRefreshCoordinator:
    """Throttle and execute serving-runtime refreshes for newer active manifests."""

    def __init__(
        self,
        *,
        system: GraphRAGApplication,
        artifact_registry: ArtifactRegistry | None,
        enabled: bool,
        interval_seconds: float,
        exclusive_runtime_operation: Callable[[], AbstractContextManager[None]],
        invalidate_runtime_cache: Callable[[], None],
    ) -> None:
        self.system = system
        self.artifact_registry = artifact_registry
        self.enabled = bool(enabled)
        self.interval_seconds = max(0.1, float(interval_seconds or 0.0))
        self._exclusive_runtime_operation = exclusive_runtime_operation
        self._invalidate_runtime_cache = invalidate_runtime_cache
        self._last_check = 0.0
        self._check_lock = threading.Lock()

    def refresh_if_stale(self, *, force_check: bool = False) -> bool:
        if not self.enabled or self.artifact_registry is None:
            return False
        now = time.monotonic()
        with self._check_lock:
            if not force_check and now - self._last_check < self.interval_seconds:
                return False
            self._last_check = now
        current_manifest = getattr(self.system, "artifact_manifest", None)
        if not self.artifact_registry.has_newer_active(current_manifest):
            return False
        refresher = getattr(self.system, "refresh_serving_runtime", None)
        if not callable(refresher):
            return False
        with self._exclusive_runtime_operation():
            current_manifest = getattr(self.system, "artifact_manifest", None)
            if not self.artifact_registry.has_newer_active(current_manifest):
                return False
            refresher(force=True)
            self._invalidate_runtime_cache()
        return True

    def refresh_runtime(self, *, after_refresh: Callable[[], _T]) -> _T:
        refresher = getattr(self.system, "refresh_serving_runtime", None)
        if not callable(refresher):
            raise RuntimeError("Application does not support serving-runtime refresh.")
        with self._exclusive_runtime_operation():
            refresher(force=True)
            self._invalidate_runtime_cache()
            return after_refresh()


__all__ = ["ServingHotRefreshCoordinator"]
