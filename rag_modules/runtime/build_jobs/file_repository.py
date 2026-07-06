"""File-backed implementation of the build-job repository port."""

from __future__ import annotations

import hashlib
import json
import os
import re
import threading
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from rag_modules.app.build_jobs import (
    BuildJobConcurrentUpdateError,
    BuildJobConflictError,
    BuildJobEvent,
    BuildJobEventType,
    BuildJobId,
    BuildJobIdempotencyConflictError,
    BuildJobLease,
    BuildJobLeaseLostError,
    BuildJobListQuery,
    BuildJobPage,
    BuildJobRepositoryDiagnostics,
    BuildJobRepositoryError,
    BuildJobRepositorySettings,
    BuildJobSnapshot,
    BuildJobStatus,
    BuildJobSubmission,
    BuildJobSubmissionDisposition,
    JobQueued,
    SubmitBuildJob,
    WorkerIdentity,
    reduce_build_job,
)
from rag_modules.runtime.artifacts import write_json_atomic

from .locks import InterprocessFileLock
from .serialization import (
    BUILD_JOB_ENVELOPE_SCHEMA_VERSION,
    BuildJobEnvelope,
    envelope_from_dict,
    envelope_to_dict,
)

_IDEMPOTENCY_KEY_PATTERN = re.compile(r"[!-~]{1,128}\Z", flags=re.ASCII)
_IDEMPOTENCY_FORBIDDEN_CHARS = frozenset({"/", "\\"})
_TERMINAL_STATUSES = frozenset(
    {
        BuildJobStatus.SUCCEEDED,
        BuildJobStatus.FAILED,
        BuildJobStatus.CANCELLED,
        BuildJobStatus.INTERRUPTED,
    }
)

_Now = Callable[[], datetime]


class FileBuildJobRepository:
    """Persist build jobs as V3 event envelopes under a directory."""

    def __init__(
        self,
        path: str,
        *,
        now: _Now,
        settings: BuildJobRepositorySettings | None = None,
    ) -> None:
        self.path = str(path)
        self._now = now
        self.settings = settings or BuildJobRepositorySettings()
        self.repository_dir = self._repository_dir_for_path(self.path)
        self.jobs_dir = os.path.join(self.repository_dir, "jobs")
        self.idempotency_dir = os.path.join(self.repository_dir, "idempotency")
        self.metadata_path = os.path.join(self.repository_dir, "metadata.json")
        self._store_lock_path = f"{self.path}.lock"
        self._lock = threading.RLock()
        self._ensure_directories()
        self._write_metadata_if_missing()

    @property
    def list_default_limit(self) -> int:
        return self.settings.list_default_limit

    @staticmethod
    def _repository_dir_for_path(path: str) -> str:
        parent = os.path.dirname(path) or "."
        stem, _ = os.path.splitext(os.path.basename(path))
        return os.path.join(parent, f"{stem}.d")

    def submit(self, command: SubmitBuildJob) -> BuildJobSubmission:
        key_hash = hash_idempotency_key(validate_idempotency_key(command.idempotency_key))
        with self._store_lock():
            replay = self._find_idempotent_job(key_hash)
            if replay is not None:
                if replay.job_type is not command.job_type:
                    raise BuildJobIdempotencyConflictError(
                        "Idempotency key conflicts with an existing build job.",
                        replay,
                    )
                return BuildJobSubmission(BuildJobSubmissionDisposition.REPLAYED, replay)
            active = self._active_snapshot()
            if active is not None:
                raise BuildJobConflictError("A build job is already in progress.", active)
            event = new_queued_event(command, key_hash=key_hash, now=self._now())
            snapshot = reduce_build_job(None, event)
            self._write_envelope(BuildJobEnvelope.new(snapshot, event))
            self._write_idempotency_index(key_hash, snapshot)
            self.apply_retention()
            return BuildJobSubmission(BuildJobSubmissionDisposition.CREATED, snapshot)

    def get(self, job_id: BuildJobId) -> BuildJobSnapshot | None:
        with self._store_lock():
            envelope = self._load_envelope(job_id)
            return envelope.snapshot if envelope is not None else None

    def list_page(self, query: BuildJobListQuery) -> BuildJobPage:
        with self._store_lock():
            limit = query.limit or self.settings.list_default_limit
            bounded_limit = max(1, min(int(limit), self.settings.list_max_limit))
            snapshots = sorted(
                self._load_all_snapshots(),
                key=lambda snapshot: (snapshot.created_at, snapshot.job_id),
                reverse=True,
            )
            if query.status is not None:
                snapshots = [snapshot for snapshot in snapshots if snapshot.status is query.status]
            return BuildJobPage(jobs=tuple(snapshots[:bounded_limit]), next_cursor="")

    def claim_next(self, worker: WorkerIdentity) -> BuildJobLease | None:
        raise NotImplementedError("lease claiming is implemented in the lifecycle task")

    def renew_lease(self, lease: BuildJobLease) -> BuildJobLease:
        raise NotImplementedError("lease renewal is implemented in the lifecycle task")

    def apply(
        self,
        event: BuildJobEvent,
        *,
        expected_revision: int,
        lease: BuildJobLease | None = None,
    ) -> BuildJobSnapshot:
        with self._store_lock():
            envelope = self._require_envelope(event.job_id)
            snapshot = envelope.snapshot
            if snapshot.revision != expected_revision:
                raise BuildJobConcurrentUpdateError(
                    f"Expected revision {expected_revision}, found {snapshot.revision}."
                )
            if lease is not None:
                self._validate_lease(snapshot, lease)
            updated = reduce_build_job(snapshot, event)
            self._write_envelope(envelope.append(updated, event))
            self.apply_retention()
            return updated

    def find_dispatchable(self, *, limit: int) -> tuple[BuildJobId, ...]:
        with self._store_lock():
            queued = [
                snapshot.job_id
                for snapshot in sorted(
                    self._load_all_snapshots(),
                    key=lambda snapshot: (snapshot.created_at, snapshot.job_id),
                )
                if snapshot.status is BuildJobStatus.QUEUED
            ]
            return tuple(queued[: max(0, int(limit))])

    def recover_expired_leases(self) -> tuple[BuildJobSnapshot, ...]:
        return ()

    def apply_retention(self) -> None:
        return None

    def diagnostics(self) -> BuildJobRepositoryDiagnostics:
        return BuildJobRepositoryDiagnostics()

    def _ensure_directories(self) -> None:
        os.makedirs(self.jobs_dir, exist_ok=True)
        os.makedirs(self.idempotency_dir, exist_ok=True)

    def _write_metadata_if_missing(self) -> None:
        if os.path.exists(self.metadata_path):
            return
        write_json_atomic(
            self.metadata_path,
            {"schema_version": BUILD_JOB_ENVELOPE_SCHEMA_VERSION},
        )

    @contextmanager
    def _store_lock(self) -> Iterator[None]:
        with self._lock:
            with InterprocessFileLock(self._store_lock_path):
                yield

    def _job_path(self, job_id: BuildJobId) -> str:
        return os.path.join(self.jobs_dir, f"{job_id}.json")

    def _idempotency_path(self, key_hash: str) -> str:
        return os.path.join(self.idempotency_dir, f"{key_hash}.json")

    def _load_envelope(self, job_id: BuildJobId) -> BuildJobEnvelope | None:
        path = self._job_path(job_id)
        if not os.path.exists(path):
            return None
        try:
            with open(path, "r", encoding="utf-8") as file:
                payload = json.load(file)
            if not isinstance(payload, Mapping):
                raise ValueError("build job envelope must be an object")
            envelope = envelope_from_dict(payload)
            if envelope.snapshot.job_id != job_id:
                raise ValueError("build job envelope file name does not match job id")
            return envelope
        except (OSError, TypeError, ValueError) as exc:
            raise BuildJobRepositoryError(str(exc)) from exc

    def _require_envelope(self, job_id: BuildJobId) -> BuildJobEnvelope:
        envelope = self._load_envelope(job_id)
        if envelope is None:
            raise BuildJobRepositoryError(f"Build job not found: {job_id}")
        return envelope

    def _load_all_envelopes(self) -> list[BuildJobEnvelope]:
        if not os.path.isdir(self.jobs_dir):
            return []
        envelopes: list[BuildJobEnvelope] = []
        for path in Path(self.jobs_dir).glob("*.json"):
            envelopes.append(self._require_envelope(BuildJobId(path.stem)))
        return envelopes

    def _load_all_snapshots(self) -> list[BuildJobSnapshot]:
        return [envelope.snapshot for envelope in self._load_all_envelopes()]

    def _write_envelope(self, envelope: BuildJobEnvelope) -> None:
        write_json_atomic(self._job_path(envelope.snapshot.job_id), envelope_to_dict(envelope))

    def _write_idempotency_index(self, key_hash: str, snapshot: BuildJobSnapshot) -> None:
        if not key_hash:
            return
        write_json_atomic(
            self._idempotency_path(key_hash),
            {
                "key_hash": key_hash,
                "job_id": str(snapshot.job_id),
                "job_type": snapshot.job_type.value,
                "created_at": self._now().isoformat(),
            },
        )

    def _find_idempotent_job(self, key_hash: str) -> BuildJobSnapshot | None:
        if not key_hash:
            return None
        indexed = self._find_indexed_idempotent_job(key_hash)
        if indexed is not None:
            return indexed
        for envelope in self._load_all_envelopes():
            queued = envelope.events[0].payload if envelope.events else None
            if isinstance(queued, JobQueued) and queued.idempotency_key_hash == key_hash:
                self._write_idempotency_index(key_hash, envelope.snapshot)
                return envelope.snapshot
        return None

    def _find_indexed_idempotent_job(self, key_hash: str) -> BuildJobSnapshot | None:
        path = self._idempotency_path(key_hash)
        if not os.path.exists(path):
            return None
        try:
            with open(path, "r", encoding="utf-8") as file:
                payload = json.load(file)
            if not isinstance(payload, Mapping):
                return None
            if str(payload.get("key_hash") or "") != key_hash:
                return None
            job_id = BuildJobId(str(payload.get("job_id") or ""))
            envelope = self._load_envelope(job_id)
            if envelope is None:
                return None
            queued = envelope.events[0].payload if envelope.events else None
            if not isinstance(queued, JobQueued) or queued.idempotency_key_hash != key_hash:
                return None
            return envelope.snapshot
        except (OSError, TypeError, ValueError):
            return None

    def _active_snapshot(self) -> BuildJobSnapshot | None:
        active = [
            snapshot
            for snapshot in self._load_all_snapshots()
            if snapshot.status not in _TERMINAL_STATUSES
        ]
        if not active:
            return None
        return sorted(active, key=lambda snapshot: (snapshot.created_at, snapshot.job_id))[0]

    @staticmethod
    def _validate_lease(snapshot: BuildJobSnapshot, lease: BuildJobLease) -> None:
        if (
            snapshot.job_id != lease.job_id
            or snapshot.revision != lease.revision
            or snapshot.lease_token != lease.lease_token
        ):
            raise BuildJobLeaseLostError("Build job lease is no longer owned by this worker.")


def validate_idempotency_key(value: str) -> str:
    key = str(value or "")
    if not key:
        return ""
    if not _IDEMPOTENCY_KEY_PATTERN.fullmatch(key):
        raise ValueError("invalid Idempotency-Key")
    if any(character in key for character in _IDEMPOTENCY_FORBIDDEN_CHARS):
        raise ValueError("invalid Idempotency-Key")
    return key


def hash_idempotency_key(value: str) -> str:
    key = validate_idempotency_key(value)
    if not key:
        return ""
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def new_queued_event(command: SubmitBuildJob, *, key_hash: str, now: datetime) -> BuildJobEvent:
    return BuildJobEvent(
        event_id=f"{command.job_id}:1",
        job_id=command.job_id,
        revision=1,
        event_type=BuildJobEventType.QUEUED,
        schema_version=1,
        occurred_at=now,
        request_id=command.request_id,
        payload=JobQueued(
            job_type=command.job_type,
            idempotency_key_hash=key_hash,
            retry_of_job_id=command.retry_of_job_id,
        ),
    )


__all__ = [
    "FileBuildJobRepository",
    "hash_idempotency_key",
    "new_queued_event",
    "validate_idempotency_key",
]
