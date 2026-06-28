"""Build-job state transitions and durable registry snapshots."""

from __future__ import annotations

import copy
import threading

from .file_store import FileBuildJobStore
from .locks import _InterprocessFileLock
from .models import BUILD_JOB_LOG_LIMIT, BuildJobRecord, build_failure


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

    def create(self, *, job_id: str, request_id: str, job_type: str, message: str) -> dict:
        created, job, build_lock = self.create_or_active(
            job_id=job_id,
            request_id=request_id,
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
        request_id: str,
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
                    request_id=request_id,
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

    def mark_failed(self, job_id: str, *, result: dict) -> None:
        with self._lock:
            with self.store.locked():
                self._refresh_from_store_locked(recover_interrupted=False)
                job = self._jobs[job_id]
                job.status = "failed"
                job.finished_at = self._now()
                job.error = build_failure(job.request_id)
                job.message = "Knowledge base build failed."
                job.result = copy.deepcopy(result)
                self._clear_active_locked(job_id)
                self._persist_store_locked()

    def _load(self, *, recover_interrupted: bool) -> None:
        with self.store.locked():
            recovered = self._refresh_from_store_locked(recover_interrupted=recover_interrupted)
            if recovered or self._jobs:
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
        job.error = build_failure(job.request_id)
        job.message = "Knowledge base build interrupted by service restart."
        job.logs.append("Build interrupted by service restart.")

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


__all__ = ["PersistentBuildJobRegistry"]
