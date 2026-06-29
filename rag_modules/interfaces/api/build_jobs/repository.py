"""Directory-backed repository for asynchronous build-job state."""

from __future__ import annotations

import base64
import copy
import hashlib
import json
import os
import re
import threading
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from typing import Any

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
_IDEMPOTENCY_KEY_PATTERN = re.compile(r"[!-~]{1,128}\Z", flags=re.ASCII)
_IDEMPOTENCY_FORBIDDEN_CHARS = frozenset({"/", "\\"})


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
        self._ensure_directories()
        with self.locked():
            self._import_legacy_store_once_unlocked()
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

    @staticmethod
    def validate_idempotency_key(value: str) -> str:
        key = str(value or "")
        if not key:
            return ""
        if not _IDEMPOTENCY_KEY_PATTERN.fullmatch(key):
            raise ValueError("invalid Idempotency-Key")
        if any(character in key for character in _IDEMPOTENCY_FORBIDDEN_CHARS):
            raise ValueError("invalid Idempotency-Key")
        return key

    @staticmethod
    def idempotency_key_hash(value: str) -> str:
        key = BuildJobRepository.validate_idempotency_key(value)
        if not key:
            return ""
        return hashlib.sha256(key.encode("utf-8")).hexdigest()

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
                key_hash = self.idempotency_key_hash(idempotency_key)
                if key_hash:
                    idempotency = self._load_idempotency_unlocked(key_hash)
                    if idempotency is not None:
                        existing_job = self._load_job_unlocked(str(idempotency.get("job_id") or ""))
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
                    repaired_job = self._repair_idempotency_from_jobs_unlocked(key_hash)
                    if repaired_job is not None:
                        if repaired_job.job_type == job_type:
                            payload = repaired_job.to_dict()
                            payload["_idempotency_replayed"] = True
                            return False, payload, None
                        raise BuildJobIdempotencyConflictError(repaired_job.to_dict())
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
                    idempotency_key_hash=key_hash,
                )
                self._write_job_unlocked(job)
                if key_hash:
                    self._write_idempotency_unlocked(
                        key_hash=key_hash,
                        job_id=job_id,
                        job_type=job_type,
                    )
                self._apply_retention_unlocked()
                return True, job.to_dict(), build_lock

    def active(self) -> dict | None:
        with self._lock:
            with self.locked():
                job = self._active_unlocked()
                return job.to_dict() if job is not None else None

    def get(self, job_id: str) -> dict | None:
        with self._lock:
            with self.locked():
                job = self._load_job_unlocked(str(job_id))
                return job.to_dict() if job is not None else None

    def list_all(self) -> list[dict]:
        with self._lock:
            with self.locked():
                jobs = sorted(
                    self._load_jobs_unlocked(),
                    key=lambda item: (item.created_at, item.job_id),
                )
                return [job.to_dict() for job in jobs]

    def list_page(self, *, limit: int, cursor: str = "") -> BuildJobListPage:
        with self._lock:
            with self.locked():
                decoded_cursor = self._decode_cursor(cursor)
                jobs = sorted(
                    self._load_jobs_unlocked(),
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
                self._apply_retention_unlocked()

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
                self._apply_retention_unlocked()

    def corruption_summary(self) -> dict:
        warnings = [warning.to_dict() for warning in self._warnings]
        codes = sorted({warning["code"] for warning in warnings})
        return {"warning_count": len(warnings), "warning_codes": codes, "warnings": warnings}

    def _job_path(self, job_id: str) -> str:
        return os.path.join(self.jobs_dir, f"{job_id}.json")

    def _idempotency_path(self, key_hash: str) -> str:
        return os.path.join(self.idempotency_dir, f"{key_hash}.json")

    def _load_idempotency_unlocked(self, key_hash: str) -> dict[str, Any] | None:
        path = self._idempotency_path(key_hash)
        if not os.path.exists(path):
            return None
        try:
            with open(path, "r", encoding="utf-8") as file:
                payload = json.load(file)
            return dict(payload) if isinstance(payload, Mapping) else None
        except (OSError, TypeError, ValueError):
            self._record_warning_unlocked(
                "BUILD_JOB_STORE_CORRUPT_IDEMPOTENCY",
                "idempotency",
                key_hash[:12],
            )
            return None

    def _write_idempotency_unlocked(
        self,
        *,
        key_hash: str,
        job_id: str,
        job_type: str,
    ) -> None:
        write_json_atomic(
            self._idempotency_path(key_hash),
            {
                "key_hash": key_hash,
                "job_id": job_id,
                "job_type": job_type,
                "created_at": self._now(),
            },
        )

    def _remove_idempotency_for_job_unlocked(self, job_id: str) -> None:
        if not os.path.isdir(self.idempotency_dir):
            return
        for filename in os.listdir(self.idempotency_dir):
            if not filename.endswith(".json"):
                continue
            path = os.path.join(self.idempotency_dir, filename)
            try:
                with open(path, "r", encoding="utf-8") as file:
                    payload = json.load(file)
                if isinstance(payload, Mapping) and str(payload.get("job_id") or "") == job_id:
                    os.remove(path)
            except (OSError, TypeError, ValueError):
                self._record_warning_unlocked(
                    "BUILD_JOB_STORE_CORRUPT_IDEMPOTENCY",
                    "idempotency",
                    filename[:-5][:12],
                )

    def _apply_retention_unlocked(self) -> None:
        terminal_jobs = [
            job for job in self._load_jobs_unlocked() if job.status not in {"queued", "running"}
        ]
        terminal_jobs.sort(key=lambda item: (item.created_at, item.job_id), reverse=True)
        for job in terminal_jobs[self.settings.retention_limit :]:
            try:
                os.remove(self._job_path(job.job_id))
            except FileNotFoundError:
                pass
            self._remove_idempotency_for_job_unlocked(job.job_id)

    def _repair_idempotency_from_jobs_unlocked(
        self,
        key_hash: str,
    ) -> BuildJobRecord | None:
        for job in self._load_jobs_unlocked():
            if job.idempotency_key_hash != key_hash:
                continue
            self._write_idempotency_unlocked(
                key_hash=key_hash,
                job_id=job.job_id,
                job_type=job.job_type,
            )
            return job
        return None

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
            if job.job_id != job_id:
                self._record_warning_unlocked("BUILD_JOB_STORE_CORRUPT_RECORD", "job", job_id)
                return None
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
        write_json_atomic(self._job_path(job.job_id), job.to_dict(include_internal=True))

    def _replace_jobs_unlocked(self, jobs: Sequence[Mapping[str, object]]) -> None:
        replacements: dict[str, BuildJobRecord] = {}
        saw_invalid_entry = False
        for item in jobs:
            if not isinstance(item, Mapping):
                saw_invalid_entry = True
                continue
            job = BuildJobRecord.from_dict(item)
            if not job.job_id:
                saw_invalid_entry = True
                continue
            replacements[job.job_id] = job
        if os.path.isdir(self.jobs_dir):
            for filename in os.listdir(self.jobs_dir):
                if not filename.endswith(".json"):
                    continue
                job_id = filename[:-5]
                if job_id in replacements:
                    continue
                try:
                    os.remove(self._job_path(job_id))
                except FileNotFoundError:
                    pass
        for job in replacements.values():
            self._write_job_unlocked(job)
        self._apply_retention_unlocked()
        if saw_invalid_entry:
            self._record_warning_unlocked(
                "BUILD_JOB_STORE_CORRUPT_LEGACY",
                "legacy",
                os.path.basename(self.path),
            )

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
        self._apply_retention_unlocked()

    def _import_legacy_store_once_unlocked(self) -> None:
        metadata = self._load_metadata_unlocked()
        imports = [
            dict(item)
            for item in list(metadata.get("legacy_imports") or [])
            if isinstance(item, Mapping)
        ]
        if any(item.get("path") == self.path for item in imports):
            return
        if not os.path.exists(self.path):
            self._write_metadata_unlocked(legacy_imports=imports)
            return
        try:
            with open(self.path, "r", encoding="utf-8") as file:
                payload = json.load(file)
            jobs = payload.get("jobs") if isinstance(payload, Mapping) else None
            if not isinstance(jobs, list):
                self._record_warning_unlocked(
                    "BUILD_JOB_STORE_CORRUPT_LEGACY",
                    "legacy",
                    os.path.basename(self.path),
                )
                imports.append({"path": self.path, "status": "corrupt"})
                self._write_metadata_unlocked(legacy_imports=imports)
                return
            for item in jobs:
                if not isinstance(item, Mapping):
                    self._record_warning_unlocked(
                        "BUILD_JOB_STORE_CORRUPT_LEGACY",
                        "legacy",
                        os.path.basename(self.path),
                    )
                    continue
                try:
                    job = BuildJobRecord.from_dict(item)
                except (TypeError, ValueError):
                    self._record_warning_unlocked(
                        "BUILD_JOB_STORE_CORRUPT_LEGACY",
                        "legacy",
                        os.path.basename(self.path),
                    )
                    continue
                if not job.job_id:
                    self._record_warning_unlocked(
                        "BUILD_JOB_STORE_CORRUPT_LEGACY",
                        "legacy",
                        os.path.basename(self.path),
                    )
                    continue
                if not os.path.exists(self._job_path(job.job_id)):
                    self._write_job_unlocked(job)
            self._apply_retention_unlocked()
            imports.append({"path": self.path, "status": "imported"})
            self._write_metadata_unlocked(legacy_imports=imports)
        except (OSError, TypeError, ValueError):
            self._record_warning_unlocked(
                "BUILD_JOB_STORE_CORRUPT_LEGACY",
                "legacy",
                os.path.basename(self.path),
            )
            imports.append({"path": self.path, "status": "corrupt"})
            self._write_metadata_unlocked(legacy_imports=imports)

    def _load_metadata_unlocked(self) -> dict:
        if not os.path.exists(self.metadata_path):
            return {}
        try:
            with open(self.metadata_path, "r", encoding="utf-8") as file:
                payload = json.load(file)
            if not isinstance(payload, Mapping):
                self._record_warning_unlocked(
                    "BUILD_JOB_STORE_CORRUPT_METADATA",
                    "metadata",
                    os.path.basename(self.metadata_path),
                )
                return {}
            metadata = dict(payload)
            legacy_imports = metadata.get("legacy_imports")
            if legacy_imports is None:
                return metadata
            if not isinstance(legacy_imports, list):
                self._record_warning_unlocked(
                    "BUILD_JOB_STORE_CORRUPT_METADATA",
                    "metadata",
                    os.path.basename(self.metadata_path),
                )
                metadata["legacy_imports"] = []
                return metadata
            valid_imports: list[dict[str, object]] = []
            for item in legacy_imports:
                if not isinstance(item, Mapping) or not item.get("path"):
                    self._record_warning_unlocked(
                        "BUILD_JOB_STORE_CORRUPT_METADATA",
                        "metadata",
                        os.path.basename(self.metadata_path),
                    )
                    continue
                valid_imports.append(dict(item))
            metadata["legacy_imports"] = valid_imports
            return metadata
        except (OSError, TypeError, ValueError):
            self._record_warning_unlocked(
                "BUILD_JOB_STORE_CORRUPT_METADATA",
                "metadata",
                os.path.basename(self.metadata_path),
            )
            return {}

    def _write_metadata_unlocked(
        self,
        *,
        legacy_imports: Sequence[Mapping[str, object]] | None = None,
    ) -> None:
        write_json_atomic(
            self.metadata_path,
            {
                "schema_version": BUILD_JOB_REPOSITORY_SCHEMA_VERSION,
                "legacy_schema_version": BUILD_JOB_STORE_SCHEMA_VERSION,
                "legacy_path": self.path,
                "legacy_imports": [dict(item) for item in legacy_imports or []],
            },
        )

    def _record_warning_unlocked(self, code: str, component: str, identifier: str) -> None:
        warning = BuildJobCorruptionWarning(
            code=code,
            component=component,
            identifier=str(identifier)[:24],
            detected_at=self._now(),
        )
        warning_key = (warning.code, warning.component, warning.identifier)
        if all(
            (item.code, item.component, item.identifier) != warning_key for item in self._warnings
        ):
            self._warnings.append(warning)


__all__ = [
    "BUILD_JOB_REPOSITORY_SCHEMA_VERSION",
    "BuildJobIdempotencyConflictError",
    "BuildJobRepository",
]
