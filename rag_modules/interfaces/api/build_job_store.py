"""Persistent repository for asynchronous build-job state."""

from __future__ import annotations

import copy
import json
import os
import threading
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, BinaryIO, Iterator, Mapping, cast

from ...artifacts import write_json_atomic

BUILD_JOB_STORE_SCHEMA_VERSION = "graph-rag-build-jobs-v1"
BUILD_JOB_LOG_LIMIT = 200
_PROCESS_FILE_LOCKS: dict[str, threading.Lock] = {}
_PROCESS_FILE_LOCKS_LOCK = threading.Lock()


def _process_file_lock(path: str) -> threading.Lock:
    normalized_path = os.path.abspath(path)
    with _PROCESS_FILE_LOCKS_LOCK:
        lock = _PROCESS_FILE_LOCKS.get(normalized_path)
        if lock is None:
            lock = threading.Lock()
            _PROCESS_FILE_LOCKS[normalized_path] = lock
        return lock


class _InterprocessFileLock:
    """Small cross-platform exclusive file lock."""

    def __init__(self, path: str, *, blocking: bool = True) -> None:
        self.path = os.path.abspath(path)
        self.blocking = bool(blocking)
        self._process_lock = _process_file_lock(self.path)
        self._file: BinaryIO | None = None
        self._acquired = False

    def acquire(self) -> bool:
        if self._acquired:
            return True
        if not self._process_lock.acquire(blocking=self.blocking):
            return False
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        file = open(self.path, "a+b")
        try:
            if os.name == "nt":
                import msvcrt

                file.seek(0)
                mode = msvcrt.LK_LOCK if self.blocking else msvcrt.LK_NBLCK
                msvcrt.locking(file.fileno(), mode, 1)
            else:
                fcntl = cast(Any, __import__("fcntl"))

                flags = fcntl.LOCK_EX
                if not self.blocking:
                    flags |= fcntl.LOCK_NB
                fcntl.flock(file.fileno(), flags)
        except OSError:
            file.close()
            self._process_lock.release()
            if self.blocking:
                raise
            return False
        self._file = file
        self._acquired = True
        return True

    def release(self) -> None:
        if not self._acquired:
            return
        file = self._file
        self._file = None
        self._acquired = False
        try:
            if file is not None:
                if os.name == "nt":
                    import msvcrt

                    file.seek(0)
                    msvcrt.locking(file.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl = cast(Any, __import__("fcntl"))

                    fcntl.flock(file.fileno(), fcntl.LOCK_UN)
        finally:
            if file is not None:
                file.close()
            self._process_lock.release()

    def __enter__(self) -> "_InterprocessFileLock":
        if not self.acquire():
            raise BlockingIOError(f"Could not acquire file lock: {self.path}")
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.release()


@dataclass(slots=True)
class BuildJobRecord:
    job_id: str
    job_type: str
    status: str
    created_at: str
    started_at: str = ""
    finished_at: str = ""
    message: str = ""
    error: str = ""
    logs: list[str] = field(default_factory=list)
    result: dict | None = None

    def to_dict(self) -> dict:
        return {
            "job_id": self.job_id,
            "job_type": self.job_type,
            "status": self.status,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "message": self.message,
            "error": self.error,
            "logs": list(self.logs),
            "result": copy.deepcopy(self.result),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "BuildJobRecord":
        return cls(
            job_id=str(payload.get("job_id") or ""),
            job_type=str(payload.get("job_type") or "build"),
            status=str(payload.get("status") or "failed"),
            created_at=str(payload.get("created_at") or ""),
            started_at=str(payload.get("started_at") or ""),
            finished_at=str(payload.get("finished_at") or ""),
            message=str(payload.get("message") or ""),
            error=str(payload.get("error") or ""),
            logs=[str(item) for item in list(payload.get("logs") or [])],
            result=(
                copy.deepcopy(dict(payload["result"]))
                if isinstance(payload.get("result"), Mapping)
                else None
            ),
        )


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
        with self.locked():
            return self._load_all_unlocked()

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


class PersistentBuildJobRegistry:
    """Own build-job state transitions and durable snapshots."""

    def __init__(
        self,
        store: FileBuildJobStore,
        *,
        now,
        recover_interrupted: bool = True,
    ) -> None:
        self.store = store
        self._now = now
        self._lock = threading.RLock()
        self._jobs: dict[str, BuildJobRecord] = {}
        self._order: list[str] = []
        self._active_job_id: str | None = None
        self._load(recover_interrupted=recover_interrupted)

    def active(self) -> dict | None:
        with self._lock:
            with self.store.locked():
                self._refresh_from_store_locked(recover_interrupted=False)
            job = self._active_locked()
            return job.to_dict() if job is not None else None

    def create(self, *, job_id: str, job_type: str, message: str) -> dict:
        created, job, build_lock = self.create_or_active(
            job_id=job_id,
            job_type=job_type,
            message=message,
        )
        if build_lock is not None:
            build_lock.release()
        if not created:
            raise RuntimeError("A build job is already in progress.")
        if job is None:
            raise RuntimeError("Build job was not created.")
        return job

    def create_or_active(
        self,
        *,
        job_id: str,
        job_type: str,
        message: str,
    ) -> tuple[bool, dict | None, _InterprocessFileLock | None]:
        with self._lock:
            with self.store.locked():
                self._refresh_from_store_locked(recover_interrupted=False)
                active_job = self._active_locked()
                if active_job is not None:
                    if self.store.build_lock_held():
                        return False, active_job.to_dict(), None
                    self._recover_active_locked()

                build_lock = self.store.try_acquire_build_lock()
                if build_lock is None:
                    self._refresh_from_store_locked(recover_interrupted=False)
                    active_job = self._active_locked()
                    return (
                        False,
                        active_job.to_dict() if active_job is not None else None,
                        None,
                    )

                job = BuildJobRecord(
                    job_id=job_id,
                    job_type=job_type,
                    status="queued",
                    created_at=self._now(),
                    message=message,
                )
                self._jobs[job_id] = job
                self._order.append(job_id)
                self._active_job_id = job_id
                self._persist_store_locked()
                return True, job.to_dict(), build_lock

    def list(self) -> list[dict]:
        with self._lock:
            with self.store.locked():
                self._refresh_from_store_locked(recover_interrupted=False)
            return [self._jobs[job_id].to_dict() for job_id in reversed(self._order)]

    def get(self, job_id: str) -> dict | None:
        with self._lock:
            with self.store.locked():
                self._refresh_from_store_locked(recover_interrupted=False)
            job = self._jobs.get(str(job_id))
            return job.to_dict() if job is not None else None

    def append_log(self, job_id: str, message: str) -> None:
        with self._lock:
            with self.store.locked():
                self._refresh_from_store_locked(recover_interrupted=False)
                job = self._jobs.get(job_id)
                if job is None:
                    return
                job.logs.append(str(message))
                if len(job.logs) > BUILD_JOB_LOG_LIMIT:
                    job.logs = job.logs[-BUILD_JOB_LOG_LIMIT:]
                self._persist_store_locked()

    def mark_running(self, job_id: str, *, message: str) -> None:
        with self._lock:
            with self.store.locked():
                self._refresh_from_store_locked(recover_interrupted=False)
                job = self._jobs[job_id]
                job.status = "running"
                job.started_at = self._now()
                job.message = message
                self._persist_store_locked()

    def mark_succeeded(self, job_id: str, *, result: dict) -> None:
        with self._lock:
            with self.store.locked():
                self._refresh_from_store_locked(recover_interrupted=False)
                job = self._jobs[job_id]
                job.status = "succeeded"
                job.finished_at = self._now()
                job.message = str(result.get("message", "Knowledge base build completed."))
                job.result = copy.deepcopy(result)
                self._clear_active_locked(job_id)
                self._persist_store_locked()

    def mark_failed(self, job_id: str, *, error: str, result: dict) -> None:
        with self._lock:
            with self.store.locked():
                self._refresh_from_store_locked(recover_interrupted=False)
                job = self._jobs[job_id]
                job.status = "failed"
                job.finished_at = self._now()
                job.error = str(error)
                job.message = "Knowledge base build failed."
                job.result = copy.deepcopy(result)
                self._clear_active_locked(job_id)
                self._persist_store_locked()

    def _load(self, *, recover_interrupted: bool) -> None:
        with self.store.locked():
            recovered = self._refresh_from_store_locked(recover_interrupted=recover_interrupted)
            if recovered:
                self._persist_store_locked()

    def _refresh_from_store_locked(self, *, recover_interrupted: bool) -> bool:
        self._jobs = {}
        self._order = []
        self._active_job_id = None
        recovered = False
        for payload in self.store._load_all_unlocked():
            job = BuildJobRecord.from_dict(payload)
            if not job.job_id:
                continue
            if job.status in {"queued", "running"}:
                if recover_interrupted:
                    self._mark_interrupted(job)
                    recovered = True
                else:
                    self._active_job_id = job.job_id
            self._jobs[job.job_id] = job
            self._order.append(job.job_id)
        return recovered

    def _recover_active_locked(self) -> None:
        recovered = False
        for job_id in self._order:
            job = self._jobs[job_id]
            if job.status in {"queued", "running"}:
                self._mark_interrupted(job)
                recovered = True
        if recovered:
            self._active_job_id = None
            self._persist_store_locked()

    def _mark_interrupted(self, job: BuildJobRecord) -> None:
        job.status = "failed"
        job.finished_at = self._now()
        job.error = "Build service restarted before the job completed."
        job.message = "Knowledge base build interrupted by service restart."
        job.logs.append(f"[ERROR] {job.error}")

    def _active_locked(self) -> BuildJobRecord | None:
        if self._active_job_id is None:
            return None
        job = self._jobs.get(self._active_job_id)
        if job is not None and job.status in {"queued", "running"}:
            return job
        self._active_job_id = None
        return None

    def _clear_active_locked(self, job_id: str) -> None:
        if self._active_job_id == job_id:
            self._active_job_id = None

    def _persist_store_locked(self) -> None:
        self.store._save_all_unlocked([self._jobs[job_id].to_dict() for job_id in self._order])


def default_build_job_store_path(config: Any) -> str:
    storage = getattr(config, "storage", None)
    configured_path = str(getattr(storage, "build_job_store_path", "") or "")
    if configured_path:
        return configured_path
    manifest_path = str(
        getattr(storage, "artifact_manifest_path", "")
        or os.path.join("storage", "indexes", "artifact_manifest.json")
    )
    return os.path.join(os.path.dirname(manifest_path), "build_jobs.json")


__all__ = [
    "BUILD_JOB_LOG_LIMIT",
    "BUILD_JOB_STORE_SCHEMA_VERSION",
    "BuildJobRecord",
    "FileBuildJobStore",
    "PersistentBuildJobRegistry",
    "default_build_job_store_path",
]
