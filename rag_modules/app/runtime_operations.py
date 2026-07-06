"""Shared runtime-operation coordination for API-facing application services."""

from __future__ import annotations

import threading
from collections.abc import Iterator
from contextlib import contextmanager

from .application_protocol import GraphRAGApplication

_RUNTIME_COORDINATOR_ATTR = "__graph_rag_runtime_operation_coordinator__"
_RUNTIME_COORDINATOR_CREATION_LOCK = threading.Lock()


class RuntimeOperationCoordinator:
    """Shared coordination state attached to one application system instance."""

    def __init__(self) -> None:
        self._state_lock = threading.RLock()
        self._state_changed = threading.Condition(self._state_lock)
        self._active_answers = 0
        self._active_inspections = 0
        self._pending_lifecycle_operations = 0
        self._lifecycle_active = False
        self._lifecycle_owner: int | None = None

    @contextmanager
    def lifecycle_operation(self) -> Iterator[None]:
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
                self._lifecycle_owner = threading.get_ident()
            finally:
                if waiting_for_lifecycle:
                    self._pending_lifecycle_operations -= 1
                    self._state_changed.notify_all()
        try:
            yield
        finally:
            with self._state_changed:
                self._lifecycle_active = False
                self._lifecycle_owner = None
                self._state_changed.notify_all()

    @contextmanager
    def answer_operation(self) -> Iterator[None]:
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
    def inspection_operation(self) -> Iterator[None]:
        reentrant_lifecycle_inspection = False
        with self._state_changed:
            if self._lifecycle_active and self._lifecycle_owner == threading.get_ident():
                reentrant_lifecycle_inspection = True
            else:
                while self._lifecycle_active or self._pending_lifecycle_operations > 0:
                    self._state_changed.wait()
                self._active_inspections += 1
        try:
            yield
        finally:
            if reentrant_lifecycle_inspection:
                return
            with self._state_changed:
                self._active_inspections -= 1
                if self._active_inspections == 0:
                    self._state_changed.notify_all()

    def lifecycle_active(self) -> bool:
        with self._state_lock:
            return self._lifecycle_active


def resolve_runtime_operation_coordinator(
    system: GraphRAGApplication,
) -> RuntimeOperationCoordinator:
    coordinator = getattr(system, _RUNTIME_COORDINATOR_ATTR, None)
    if isinstance(coordinator, RuntimeOperationCoordinator):
        return coordinator
    with _RUNTIME_COORDINATOR_CREATION_LOCK:
        coordinator = getattr(system, _RUNTIME_COORDINATOR_ATTR, None)
        if not isinstance(coordinator, RuntimeOperationCoordinator):
            coordinator = RuntimeOperationCoordinator()
            setattr(system, _RUNTIME_COORDINATOR_ATTR, coordinator)
    return coordinator


__all__ = ["RuntimeOperationCoordinator", "resolve_runtime_operation_coordinator"]
