"""Directory-backed repository for asynchronous build-job state."""

from __future__ import annotations

import base64
import copy
import json
import os
import threading
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager

from .idempotency_index import BuildJobIdempotencyIndex
from .locks import _InterprocessFileLock
from .models import (
    BUILD_JOB_LOG_LIMIT,
    BuildJobCorruptionWarning,
    BuildJobListPage,
    BuildJobRecord,
    BuildJobRepositorySettings,
    build_failure,
)
from .record_store import BuildJobRecordStore
from .recovery_retention import (
    BUILD_JOB_REPOSITORY_SCHEMA_VERSION,
    BuildJobRepositoryRecoveryRetention,
)


class BuildJobIdempotencyConflictError(ValueError):
    """Raised when an idempotency key points to a different build job type."""

    def __init__(self, job: dict) -> None:
        super().__init__(f"idempotency key already used for {str(job.get('job_type') or '')}")
        self.job = dict(job)


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
        self._record_store = BuildJobRecordStore(
            self.jobs_dir,
            legacy_identifier=os.path.basename(self.path),
            warn=self._record_warning_unlocked,
        )
        self._idempotency_index = BuildJobIdempotencyIndex(
            self.idempotency_dir,
            now=self._now,
            warn=self._record_warning_unlocked,
        )
        self._lifecycle = BuildJobRepositoryRecoveryRetention(
            path=self.path,
            metadata_path=self.metadata_path,
            settings=self.settings,
            now=self._now,
            record_store=self._record_store,
            idempotency_index=self._idempotency_index,
            warn=self._record_warning_unlocked,
        )
        self._ensure_directories()
        with self.locked():
            self._lifecycle.import_legacy_store_once()
            if recover_interrupted and not self.build_lock_held():
                self._lifecycle.recover_interrupted()

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

    @staticmethod
    def validate_idempotency_key(value: str) -> str:
        return BuildJobIdempotencyIndex.validate_key(value)

    @staticmethod
    def idempotency_key_hash(value: str) -> str:
        return BuildJobIdempotencyIndex.key_hash(value)

    @staticmethod
    def _encode_cursor(created_at: str, job_id: str) -> str:
        payload = json.dumps(
            {"created_at": created_at, "job_id": job_id},
            separators=(",", ":"),
        )
        return base64.urlsafe_b64encode(payload.encode("utf-8")).decode("ascii")

    @staticmethod
    def _decode_cursor(cursor: str) -> tuple[str, str] | None:
        if not cursor:
            return None
        try:
            raw = base64.urlsafe_b64decode(cursor.encode("ascii")).decode("utf-8")
            payload = json.loads(raw)
            if not isinstance(payload, Mapping):
                raise ValueError
            created_at = str(payload.get("created_at") or "")
            job_id = str(payload.get("job_id") or "")
            if not created_at or not job_id:
                raise ValueError
            return created_at, job_id
        except (OSError, TypeError, ValueError):
            raise ValueError("invalid build job cursor") from None

    def create_or_active(
        self,
        *,
        job_id: str,
        request_id: str,
        job_type: str,
        message: str,
        idempotency_key: str = "",
    ) -> tuple[bool, dict | None, _InterprocessFileLock | None]:
        with self._lock:
            with self.locked():
                key_hash = self._idempotency_index.key_hash(idempotency_key)
                if key_hash:
                    idempotency = self._idempotency_index.load(key_hash)
                    if idempotency is not None:
                        existing_job = self._record_store.load(str(idempotency.get("job_id") or ""))
                        existing_type = str(idempotency.get("job_type") or "")
                        trusted_index = (
                            existing_job is not None
                            and existing_job.idempotency_key_hash == key_hash
                            and existing_type == existing_job.job_type
                        )
                        if existing_job is not None and trusted_index and existing_type == job_type:
                            payload = existing_job.to_dict()
                            payload["_idempotency_replayed"] = True
                            return False, payload, None
                        if existing_job is not None and trusted_index:
                            raise BuildJobIdempotencyConflictError(existing_job.to_dict())
                    repaired_job = self._idempotency_index.repair_from_jobs(
                        key_hash,
                        self._record_store.load_all(),
                    )
                    if repaired_job is not None:
                        if repaired_job.job_type == job_type:
                            payload = repaired_job.to_dict()
                            payload["_idempotency_replayed"] = True
                            return False, payload, None
                        raise BuildJobIdempotencyConflictError(repaired_job.to_dict())
                active_job = self._lifecycle.active()
                if active_job is not None:
                    if self.build_lock_held():
                        return False, active_job.to_dict(), None
                    self._lifecycle.mark_interrupted(active_job)
                build_lock = self.try_acquire_build_lock()
                if build_lock is None:
                    active_job = self._lifecycle.active()
                    return False, active_job.to_dict() if active_job is not None else None, None
                job = BuildJobRecord(
                    job_id=job_id,
                    request_id=request_id,
                    job_type=job_type,
                    status="queued",
                    created_at=self._now(),
                    message=message,
                    idempotency_key_hash=key_hash,
                )
                self._record_store.write(job)
                if key_hash:
                    self._idempotency_index.write(
                        key_hash=key_hash,
                        job_id=job_id,
                        job_type=job_type,
                    )
                self._lifecycle.apply_retention()
                return True, job.to_dict(), build_lock

    def active(self) -> dict | None:
        with self._lock:
            with self.locked():
                job = self._lifecycle.active()
                return job.to_dict() if job is not None else None

    def get(self, job_id: str) -> dict | None:
        with self._lock:
            with self.locked():
                job = self._record_store.load(str(job_id))
                return job.to_dict() if job is not None else None

    def list_all(self) -> list[dict]:
        with self._lock:
            with self.locked():
                jobs = sorted(
                    self._record_store.load_all(),
                    key=lambda item: (item.created_at, item.job_id),
                )
                return [job.to_dict() for job in jobs]

    def list_page(self, *, limit: int, cursor: str = "") -> BuildJobListPage:
        with self._lock:
            with self.locked():
                decoded_cursor = self._decode_cursor(cursor)
                jobs = sorted(
                    self._record_store.load_all(),
                    key=lambda item: (item.created_at, item.job_id),
                    reverse=True,
                )
                if decoded_cursor is not None:
                    jobs = [job for job in jobs if (job.created_at, job.job_id) < decoded_cursor]
                bounded_limit = max(1, min(int(limit), self.settings.list_max_limit))
                selected = jobs[:bounded_limit]
                remaining = jobs[bounded_limit:]
                next_cursor = ""
                if remaining and selected:
                    last = selected[-1]
                    next_cursor = self._encode_cursor(last.created_at, last.job_id)
                return BuildJobListPage(
                    jobs=[job.to_dict() for job in selected],
                    next_cursor=next_cursor,
                )

    def append_log(self, job_id: str, message: str) -> None:
        with self._lock:
            with self.locked():
                job = self._record_store.load(job_id)
                if job is None:
                    return
                job.logs.append(str(message))
                if len(job.logs) > BUILD_JOB_LOG_LIMIT:
                    job.logs = job.logs[-BUILD_JOB_LOG_LIMIT:]
                self._record_store.write(job)

    def mark_running(self, job_id: str, *, message: str) -> None:
        with self._lock:
            with self.locked():
                job = self._record_store.require(job_id)
                job.status = "running"
                job.started_at = self._now()
                job.message = message
                self._record_store.write(job)

    def mark_succeeded(self, job_id: str, *, result: dict) -> None:
        with self._lock:
            with self.locked():
                job = self._record_store.require(job_id)
                job.status = "succeeded"
                job.finished_at = self._now()
                job.message = str(result.get("message", "Knowledge base build completed."))
                job.result = copy.deepcopy(result)
                self._record_store.write(job)
                self._lifecycle.apply_retention()

    def mark_failed(self, job_id: str, *, result: dict) -> None:
        with self._lock:
            with self.locked():
                job = self._record_store.require(job_id)
                job.status = "failed"
                job.finished_at = self._now()
                job.error = build_failure(job.request_id)
                job.message = "Knowledge base build failed."
                job.result = copy.deepcopy(result)
                self._record_store.write(job)
                self._lifecycle.apply_retention()

    def corruption_summary(self) -> dict:
        with self._lock:
            with self.locked():
                self._lifecycle.scan_for_corruption()
                warnings = [warning.to_dict() for warning in self._warnings]
                codes = sorted({warning["code"] for warning in warnings})
                return {
                    "warning_count": len(warnings),
                    "warning_codes": codes,
                    "warnings": warnings,
                }

    def _replace_jobs_unlocked(self, jobs: Sequence[Mapping[str, object]]) -> None:
        self._record_store.replace(jobs)
        self._lifecycle.apply_retention()

    def _record_warning_unlocked(self, code: str, component: str, identifier: str) -> None:
        normalized_identifier = str(identifier)[:24]
        warning_key = (code, component, normalized_identifier)
        if any(
            (item.code, item.component, item.identifier) == warning_key for item in self._warnings
        ):
            return
        warning = BuildJobCorruptionWarning(
            code=code,
            component=component,
            identifier=normalized_identifier,
            detected_at=self._now(),
        )
        self._warnings.append(warning)


__all__ = [
    "BUILD_JOB_REPOSITORY_SCHEMA_VERSION",
    "BuildJobIdempotencyConflictError",
    "BuildJobRepository",
]
