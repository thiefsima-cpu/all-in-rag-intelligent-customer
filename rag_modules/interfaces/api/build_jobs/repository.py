"""Directory-backed repository for asynchronous build-job state."""

from __future__ import annotations

import copy
import json
import os
import threading
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager

from ....runtime.artifacts import write_json_atomic
from .locks import _InterprocessFileLock
from .models import (
    BUILD_JOB_LOG_LIMIT,
    BUILD_JOB_STORE_SCHEMA_VERSION,
    BuildJobCorruptionWarning,
    BuildJobListPage,
    BuildJobRecord,
    BuildJobRepositorySettings,
    build_failure,
)

BUILD_JOB_REPOSITORY_SCHEMA_VERSION = "graph-rag-build-job-repository-v1"


class BuildJobRepository:
    """Persist build jobs as independent JSON records."""

    def __init__(
        self,
        path: str,
        *,
        now: Callable[[], str],
        settings: BuildJobRepositorySettings | None = None,
        recover_interrupted: bool = True,
    ) -> None:
        self.path = str(path)
        self._now = now
        self.settings = settings or BuildJobRepositorySettings()
        self._lock = threading.RLock()
        self._store_lock_path = f"{self.path}.lock"
        self._build_lock_path = f"{self.path}.flight.lock"
        self.repository_dir = self._repository_dir_for_path(self.path)
        self.jobs_dir = os.path.join(self.repository_dir, "jobs")
        self.idempotency_dir = os.path.join(self.repository_dir, "idempotency")
        self.metadata_path = os.path.join(self.repository_dir, "metadata.json")
        self._warnings: list[BuildJobCorruptionWarning] = []
        self._ensure_directories()
        with self.locked():
            self._write_metadata_unlocked()
            if recover_interrupted and not self.build_lock_held():
                self._recover_interrupted_unlocked()

    @staticmethod
    def _repository_dir_for_path(path: str) -> str:
        parent = os.path.dirname(path) or "."
        stem, _ = os.path.splitext(os.path.basename(path))
        return os.path.join(parent, f"{stem}.d")

    def _ensure_directories(self) -> None:
        os.makedirs(self.jobs_dir, exist_ok=True)
        os.makedirs(self.idempotency_dir, exist_ok=True)

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

    def create_or_active(
        self,
        *,
        job_id: str,
        request_id: str,
        job_type: str,
        message: str,
        idempotency_key: str = "",
    ) -> tuple[bool, dict | None, _InterprocessFileLock | None]:
        del idempotency_key
        with self._lock:
            with self.locked():
                active_job = self._active_unlocked()
                if active_job is not None:
                    if self.build_lock_held():
                        return False, active_job.to_dict(), None
                    self._mark_interrupted_unlocked(active_job)
                build_lock = self.try_acquire_build_lock()
                if build_lock is None:
                    active_job = self._active_unlocked()
                    return False, active_job.to_dict() if active_job is not None else None, None
                job = BuildJobRecord(
                    job_id=job_id,
                    request_id=request_id,
                    job_type=job_type,
                    status="queued",
                    created_at=self._now(),
                    message=message,
                )
                self._write_job_unlocked(job)
                return True, job.to_dict(), build_lock

    def get(self, job_id: str) -> dict | None:
        with self._lock:
            with self.locked():
                job = self._load_job_unlocked(str(job_id))
                return job.to_dict() if job is not None else None

    def list_page(self, *, limit: int, cursor: str = "") -> BuildJobListPage:
        del cursor
        with self._lock:
            with self.locked():
                jobs = sorted(
                    self._load_jobs_unlocked(),
                    key=lambda item: (item.created_at, item.job_id),
                    reverse=True,
                )
                return BuildJobListPage(
                    jobs=[job.to_dict() for job in jobs[: int(limit)]],
                    next_cursor="",
                )

    def append_log(self, job_id: str, message: str) -> None:
        with self._lock:
            with self.locked():
                job = self._load_job_unlocked(job_id)
                if job is None:
                    return
                job.logs.append(str(message))
                if len(job.logs) > BUILD_JOB_LOG_LIMIT:
                    job.logs = job.logs[-BUILD_JOB_LOG_LIMIT:]
                self._write_job_unlocked(job)

    def mark_running(self, job_id: str, *, message: str) -> None:
        with self._lock:
            with self.locked():
                job = self._require_job_unlocked(job_id)
                job.status = "running"
                job.started_at = self._now()
                job.message = message
                self._write_job_unlocked(job)

    def mark_succeeded(self, job_id: str, *, result: dict) -> None:
        with self._lock:
            with self.locked():
                job = self._require_job_unlocked(job_id)
                job.status = "succeeded"
                job.finished_at = self._now()
                job.message = str(result.get("message", "Knowledge base build completed."))
                job.result = copy.deepcopy(result)
                self._write_job_unlocked(job)

    def mark_failed(self, job_id: str, *, result: dict) -> None:
        with self._lock:
            with self.locked():
                job = self._require_job_unlocked(job_id)
                job.status = "failed"
                job.finished_at = self._now()
                job.error = build_failure(job.request_id)
                job.message = "Knowledge base build failed."
                job.result = copy.deepcopy(result)
                self._write_job_unlocked(job)

    def corruption_summary(self) -> dict:
        warnings = [warning.to_dict() for warning in self._warnings]
        codes = sorted({warning["code"] for warning in warnings})
        return {"warning_count": len(warnings), "warning_codes": codes, "warnings": warnings}

    def _job_path(self, job_id: str) -> str:
        return os.path.join(self.jobs_dir, f"{job_id}.json")

    def _load_job_unlocked(self, job_id: str) -> BuildJobRecord | None:
        path = self._job_path(job_id)
        if not os.path.exists(path):
            return None
        try:
            with open(path, "r", encoding="utf-8") as file:
                payload = json.load(file)
            if not isinstance(payload, Mapping):
                self._record_warning_unlocked("BUILD_JOB_STORE_CORRUPT_RECORD", "job", job_id)
                return None
            job = BuildJobRecord.from_dict(payload)
            return job if job.job_id else None
        except (OSError, TypeError, ValueError):
            self._record_warning_unlocked("BUILD_JOB_STORE_CORRUPT_RECORD", "job", job_id)
            return None

    def _load_jobs_unlocked(self) -> list[BuildJobRecord]:
        if not os.path.isdir(self.jobs_dir):
            return []
        jobs: list[BuildJobRecord] = []
        for filename in os.listdir(self.jobs_dir):
            if not filename.endswith(".json"):
                continue
            job = self._load_job_unlocked(filename[:-5])
            if job is not None:
                jobs.append(job)
        return jobs

    def _require_job_unlocked(self, job_id: str) -> BuildJobRecord:
        job = self._load_job_unlocked(job_id)
        if job is None:
            raise KeyError(job_id)
        return job

    def _write_job_unlocked(self, job: BuildJobRecord) -> None:
        write_json_atomic(self._job_path(job.job_id), job.to_dict())

    def _active_unlocked(self) -> BuildJobRecord | None:
        for job in self._load_jobs_unlocked():
            if job.status in {"queued", "running"}:
                return job
        return None

    def _recover_interrupted_unlocked(self) -> None:
        for job in self._load_jobs_unlocked():
            if job.status in {"queued", "running"}:
                self._mark_interrupted_unlocked(job)

    def _mark_interrupted_unlocked(self, job: BuildJobRecord) -> None:
        job.status = "failed"
        job.finished_at = self._now()
        job.error = build_failure(job.request_id)
        job.message = "Knowledge base build interrupted by service restart."
        job.logs.append("Build interrupted by service restart.")
        self._write_job_unlocked(job)

    def _write_metadata_unlocked(self) -> None:
        write_json_atomic(
            self.metadata_path,
            {
                "schema_version": BUILD_JOB_REPOSITORY_SCHEMA_VERSION,
                "legacy_schema_version": BUILD_JOB_STORE_SCHEMA_VERSION,
                "legacy_path": self.path,
            },
        )

    def _record_warning_unlocked(self, code: str, component: str, identifier: str) -> None:
        warning = BuildJobCorruptionWarning(
            code=code,
            component=component,
            identifier=str(identifier)[:24],
            detected_at=self._now(),
        )
        if warning not in self._warnings:
            self._warnings.append(warning)


__all__ = ["BUILD_JOB_REPOSITORY_SCHEMA_VERSION", "BuildJobRepository"]
