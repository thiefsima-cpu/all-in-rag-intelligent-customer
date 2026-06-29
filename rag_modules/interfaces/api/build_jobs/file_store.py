"""File-backed JSON storage for build-job snapshots."""

from __future__ import annotations

import copy
import json
import os
import threading
from contextlib import contextmanager
from typing import Any, Iterator, Mapping

from ....runtime.artifacts import write_json_atomic
from .locks import _InterprocessFileLock
from .models import BUILD_JOB_STORE_SCHEMA_VERSION
from .repository import BuildJobRepository


class FileBuildJobStore:
    """Persist build jobs in one atomically replaced JSON document."""

    def __init__(self, path: str) -> None:
        self.path = str(path)
        self._lock = threading.RLock()
        self._store_lock_path = f"{self.path}.lock"
        self._build_lock_path = f"{self.path}.flight.lock"

    @contextmanager
    def locked(self) -> Iterator[None]:
        with self._lock:
            with _InterprocessFileLock(self._store_lock_path):
                yield

    def try_acquire_build_lock(self) -> _InterprocessFileLock | None:
        build_lock = _InterprocessFileLock(self._build_lock_path, blocking=False)
        if build_lock.acquire():
            return build_lock
        return None

    def build_lock_held(self) -> bool:
        build_lock = self.try_acquire_build_lock()
        if build_lock is None:
            return True
        build_lock.release()
        return False

    def load_all(self) -> list[dict[str, Any]]:
        repository = BuildJobRepository(
            self.path,
            now=lambda: "",
            recover_interrupted=False,
        )
        return repository.list_all()

    def save_all(self, jobs: list[Mapping[str, Any]]) -> None:
        with self.locked():
            self._save_all_unlocked(jobs)

    def _load_all_unlocked(self) -> list[dict[str, Any]]:
        if not os.path.exists(self.path):
            return []
        try:
            with open(self.path, "r", encoding="utf-8") as file:
                payload = json.load(file)
        except (OSError, ValueError, TypeError):
            return []
        if not isinstance(payload, Mapping):
            return []
        jobs = payload.get("jobs")
        if not isinstance(jobs, list):
            return []
        return [copy.deepcopy(dict(job)) for job in jobs if isinstance(job, Mapping)]

    def _save_all_unlocked(self, jobs: list[Mapping[str, Any]]) -> None:
        write_json_atomic(
            self.path,
            {
                "schema_version": BUILD_JOB_STORE_SCHEMA_VERSION,
                "jobs": [copy.deepcopy(dict(job)) for job in jobs],
            },
        )


__all__ = ["FileBuildJobStore"]
