"""Shared base implementation for API service orchestration."""

from __future__ import annotations

import copy
import threading
from contextlib import contextmanager
from typing import Optional

from ....app.application_protocol import GraphRAGApplication
from ....app.assembly import create_application_system
from ....configuration.models import GraphRAGConfig

_API_LOCKS_ATTR = "__graph_rag_api_service_locks__"
_API_LOCKS_CREATION_LOCK = threading.Lock()


class _GraphRAGApiServiceLocks:
    """Shared coordination state attached to one application system instance."""

    def __init__(self) -> None:
        self._state_lock = threading.RLock()
        self._state_changed = threading.Condition(self._state_lock)
        self._active_answers = 0
        self._active_inspections = 0
        self._pending_lifecycle_operations = 0
        self._lifecycle_active = False

    @contextmanager
    def lifecycle_operation(self):
        with self._state_changed:
            self._pending_lifecycle_operations += 1
            waiting_for_lifecycle = True
            try:
                while (
                    self._lifecycle_active
                    or self._active_answers > 0
                    or self._active_inspections > 0
                ):
                    self._state_changed.wait()
                self._pending_lifecycle_operations -= 1
                waiting_for_lifecycle = False
                self._lifecycle_active = True
            finally:
                if waiting_for_lifecycle:
                    self._pending_lifecycle_operations -= 1
                    self._state_changed.notify_all()
        try:
            yield
        finally:
            with self._state_changed:
                self._lifecycle_active = False
                self._state_changed.notify_all()

    @contextmanager
    def answer_operation(self):
        with self._state_changed:
            while self._lifecycle_active or self._pending_lifecycle_operations > 0:
                self._state_changed.wait()
            self._active_answers += 1
        try:
            yield
        finally:
            with self._state_changed:
                self._active_answers -= 1
                if self._active_answers == 0:
                    self._state_changed.notify_all()

    @contextmanager
    def inspection_operation(self):
        with self._state_changed:
            while self._lifecycle_active or self._pending_lifecycle_operations > 0:
                self._state_changed.wait()
            self._active_inspections += 1
        try:
            yield
        finally:
            with self._state_changed:
                self._active_inspections -= 1
                if self._active_inspections == 0:
                    self._state_changed.notify_all()

    def lifecycle_active(self) -> bool:
        with self._state_lock:
            return self._lifecycle_active


def _resolve_shared_api_locks(system: GraphRAGApplication) -> _GraphRAGApiServiceLocks:
    locks = getattr(system, _API_LOCKS_ATTR, None)
    if locks is not None:
        return locks
    with _API_LOCKS_CREATION_LOCK:
        locks = getattr(system, _API_LOCKS_ATTR, None)
        if locks is None:
            locks = _GraphRAGApiServiceLocks()
            setattr(system, _API_LOCKS_ATTR, locks)
    return locks


class _BaseGraphRAGApiService:
    """Coordinate API access with separate lifecycle and answer execution locks."""

    def __init__(
        self,
        *,
        system: GraphRAGApplication | None = None,
        config: Optional[GraphRAGConfig] = None,
    ) -> None:
        self.system = system or create_application_system(config=config)
        self._locks = _resolve_shared_api_locks(self.system)
        self._stats_cache: dict | None = None
        self._diagnostics_cache: dict[str, dict] = {}

    @contextmanager
    def _exclusive_runtime_operation(self):
        with self._locks.lifecycle_operation():
            yield

    def shutdown(self) -> None:
        with self._exclusive_runtime_operation():
            self.system.close()

    def collect_stats(self) -> dict:
        cached_stats = self._cached_stats()
        if cached_stats is not None:
            return cached_stats
        with self._locks.inspection_operation():
            return self._cache_stats(self._collect_stats_unlocked())

    def collect_startup_diagnostics(self, mode: str) -> dict:
        cached_diagnostics = self._cached_diagnostics(mode)
        if cached_diagnostics is not None:
            return cached_diagnostics
        with self._locks.inspection_operation():
            return self._cache_diagnostics(mode, self._collect_startup_diagnostics_unlocked(mode))

    def _collect_stats_unlocked(self) -> dict:
        return self.system.collect_system_stats()

    def _collect_startup_diagnostics_unlocked(self, mode: str) -> dict:
        return self.system.collect_startup_diagnostics(mode).to_dict()

    def _operation_response(self, *, message: str, mode: str) -> dict:
        return {
            "ok": True,
            "message": message,
            "diagnostics": self._cache_diagnostics(
                mode,
                self._collect_startup_diagnostics_unlocked(mode),
            ),
            "stats": self._cache_stats(self._collect_stats_unlocked()),
        }

    def _ensure_runtime_initialized(self, *, is_initialized, initializer) -> None:
        with self._locks.inspection_operation():
            if is_initialized():
                return
        with self._exclusive_runtime_operation():
            if not is_initialized():
                initializer()

    @staticmethod
    def _health_payload(diagnostics: dict) -> dict:
        return {
            "status": "ok",
            "build_initialized": diagnostics["build_initialized"],
            "serving_initialized": diagnostics["serving_initialized"],
            "artifacts_ready": diagnostics["artifacts_ready"],
            "system_ready": diagnostics["system_ready"],
            "retrieval_engines_initialized": diagnostics["retrieval_engines_initialized"],
            "manifest_health": diagnostics["manifest"]["health"],
        }

    @classmethod
    def _readiness_payload(cls, diagnostics: dict, *, ready: bool) -> dict:
        payload = cls._health_payload(diagnostics)
        payload["status"] = "ok" if ready else "not_ready"
        return payload

    def _cached_stats(self) -> dict | None:
        if not self._locks.lifecycle_active() or self._stats_cache is None:
            return None
        return copy.deepcopy(self._stats_cache)

    def _cached_diagnostics(self, mode: str) -> dict | None:
        if not self._locks.lifecycle_active():
            return None
        cached = self._diagnostics_cache.get(mode)
        if cached is None:
            return None
        return copy.deepcopy(cached)

    def _cache_stats(self, stats: dict) -> dict:
        self._stats_cache = copy.deepcopy(stats)
        return copy.deepcopy(self._stats_cache)

    def _cache_diagnostics(self, mode: str, diagnostics: dict) -> dict:
        cached = copy.deepcopy(diagnostics)
        self._diagnostics_cache[mode] = cached
        return copy.deepcopy(cached)
