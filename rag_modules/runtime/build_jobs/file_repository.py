"""File-backed implementation of the build-job repository port."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import secrets
import threading
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from datetime import datetime, timedelta
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
    BuildJobRepositoryWarning,
    BuildJobSnapshot,
    BuildJobStatus,
    BuildJobSubmission,
    BuildJobSubmissionDisposition,
    JobClaimed,
    JobInterrupted,
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
        self.leases_dir = os.path.join(self.repository_dir, "leases")
        self.metadata_path = os.path.join(self.repository_dir, "metadata.json")
        self._store_lock_path = f"{self.path}.lock"
        self._lock = threading.RLock()
        self._warnings: list[BuildJobRepositoryWarning] = []
        self._ensure_v3_repository_or_empty()
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
            decoded_cursor = _decode_cursor(query.cursor)
            limit = query.limit or self.settings.list_default_limit
            bounded_limit = max(1, min(int(limit), self.settings.list_max_limit))
            snapshots = sorted(
                self._load_all_snapshots(),
                key=lambda snapshot: (snapshot.created_at, snapshot.job_id),
                reverse=True,
            )
            if query.status is not None:
                snapshots = [snapshot for snapshot in snapshots if snapshot.status is query.status]
            if decoded_cursor is not None:
                snapshots = [
                    snapshot
                    for snapshot in snapshots
                    if (snapshot.created_at.isoformat(), str(snapshot.job_id)) < decoded_cursor
                ]
            selected = snapshots[:bounded_limit]
            remaining = snapshots[bounded_limit:]
            next_cursor = ""
            if selected and remaining:
                last = selected[-1]
                next_cursor = _encode_cursor(last.created_at.isoformat(), str(last.job_id))
            return BuildJobPage(jobs=tuple(selected), next_cursor=next_cursor)

    def claim_next(self, worker: WorkerIdentity) -> BuildJobLease | None:
        with self._store_lock():
            queued = [
                snapshot
                for snapshot in sorted(
                    self._load_all_snapshots(),
                    key=lambda snapshot: (snapshot.created_at, snapshot.job_id),
                )
                if snapshot.status is BuildJobStatus.QUEUED
            ]
            if not queued:
                return None
            snapshot = queued[0]
            lease_token = secrets.token_urlsafe(32)
            lease_expires_at = _lease_expires_at(self._now(), self.settings)
            event = BuildJobEvent(
                event_id=f"{snapshot.job_id}:{snapshot.revision + 1}",
                job_id=snapshot.job_id,
                revision=snapshot.revision + 1,
                event_type=BuildJobEventType.CLAIMED,
                schema_version=1,
                occurred_at=self._now(),
                request_id=snapshot.request_id,
                payload=JobClaimed(
                    worker=worker,
                    lease_token=lease_token,
                    lease_expires_at=lease_expires_at,
                ),
            )
            envelope = self._require_envelope(snapshot.job_id)
            claimed = reduce_build_job(snapshot, event)
            self._write_envelope(envelope.append(claimed, event))
            lease = BuildJobLease(
                job_id=claimed.job_id,
                revision=claimed.revision,
                worker=worker,
                lease_token=lease_token,
                lease_expires_at=lease_expires_at,
            )
            self._write_lease_record(lease)
            return lease

    def renew_lease(self, lease: BuildJobLease) -> BuildJobLease:
        with self._store_lock():
            snapshot = self._load_envelope(lease.job_id)
            record = self._load_lease_record(lease.job_id)
            if (
                snapshot is None
                or record is None
                or record.lease_token != lease.lease_token
                or snapshot.snapshot.status in _TERMINAL_STATUSES
            ):
                raise BuildJobLeaseLostError("Build job lease is no longer owned by this worker.")
            renewed = BuildJobLease(
                job_id=lease.job_id,
                revision=snapshot.snapshot.revision,
                worker=record.worker,
                lease_token=lease.lease_token,
                lease_expires_at=_lease_expires_at(self._now(), self.settings),
            )
            self._write_lease_record(renewed)
            return renewed

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
            if updated.status in _TERMINAL_STATUSES:
                self._remove_lease_record(updated.job_id)
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
        with self._store_lock():
            recovered: list[BuildJobSnapshot] = []
            for lease in self._load_all_lease_records():
                envelope = self._load_envelope(lease.job_id)
                if envelope is None:
                    self._remove_lease_record(lease.job_id)
                    continue
                snapshot = envelope.snapshot
                if snapshot.status in _TERMINAL_STATUSES:
                    self._remove_lease_record(lease.job_id)
                    continue
                if lease.lease_expires_at > self._now():
                    continue
                event = BuildJobEvent(
                    event_id=f"{snapshot.job_id}:{snapshot.revision + 1}",
                    job_id=snapshot.job_id,
                    revision=snapshot.revision + 1,
                    event_type=BuildJobEventType.INTERRUPTED,
                    schema_version=1,
                    occurred_at=self._now(),
                    request_id=snapshot.request_id,
                    payload=JobInterrupted(),
                )
                updated = reduce_build_job(snapshot, event)
                self._write_envelope(envelope.append(updated, event))
                self._remove_lease_record(snapshot.job_id)
                recovered.append(updated)
            self.apply_retention()
            return tuple(recovered)

    def apply_retention(self) -> None:
        terminal = [
            snapshot
            for snapshot in self._load_all_snapshots()
            if snapshot.status in _TERMINAL_STATUSES
        ]
        terminal.sort(
            key=lambda snapshot: (snapshot.finished_at or snapshot.created_at, snapshot.job_id),
            reverse=True,
        )
        for snapshot in terminal[max(0, self.settings.retention_limit) :]:
            try:
                os.remove(self._job_path(snapshot.job_id))
            except FileNotFoundError:
                pass
            self._remove_lease_record(snapshot.job_id)
            self._remove_idempotency_indexes_for_job(snapshot.job_id)

    def diagnostics(self) -> BuildJobRepositoryDiagnostics:
        with self._store_lock():
            self._scan_for_corruption()
            return BuildJobRepositoryDiagnostics(warnings=tuple(self._warnings))

    def _ensure_directories(self) -> None:
        os.makedirs(self.jobs_dir, exist_ok=True)
        os.makedirs(self.idempotency_dir, exist_ok=True)
        os.makedirs(self.leases_dir, exist_ok=True)

    def _ensure_v3_repository_or_empty(self) -> None:
        if not os.path.exists(self.repository_dir):
            return
        if not os.path.exists(self.metadata_path):
            if any(Path(self.repository_dir).iterdir()):
                raise BuildJobRepositoryError(
                    "Build job store must be migrated to V3 before repository use."
                )
            return
        try:
            with open(self.metadata_path, "r", encoding="utf-8") as file:
                metadata = json.load(file)
            if (
                not isinstance(metadata, Mapping)
                or int(metadata.get("schema_version", 0)) != BUILD_JOB_ENVELOPE_SCHEMA_VERSION
            ):
                raise ValueError
        except (OSError, TypeError, ValueError) as exc:
            raise BuildJobRepositoryError("Invalid build job V3 metadata.") from exc

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

    def _lease_path(self, job_id: BuildJobId) -> str:
        return os.path.join(self.leases_dir, f"{job_id}.json")

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
        except (OSError, TypeError, ValueError):
            self._record_warning("BUILD_JOB_STORE_CORRUPT_RECORD", "job", str(job_id))
            return None

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

    def _write_lease_record(self, lease: BuildJobLease) -> None:
        write_json_atomic(
            self._lease_path(lease.job_id),
            {
                "job_id": str(lease.job_id),
                "revision": lease.revision,
                "worker": {
                    "worker_id": lease.worker.worker_id,
                    "runner_backend": lease.worker.runner_backend,
                },
                "lease_token": lease.lease_token,
                "lease_expires_at": lease.lease_expires_at.isoformat(),
            },
        )

    def _load_lease_record(self, job_id: BuildJobId) -> BuildJobLease | None:
        path = self._lease_path(job_id)
        if not os.path.exists(path):
            return None
        try:
            with open(path, "r", encoding="utf-8") as file:
                payload = json.load(file)
            if not isinstance(payload, Mapping):
                raise ValueError
            worker = payload.get("worker")
            if not isinstance(worker, Mapping):
                raise ValueError
            return BuildJobLease(
                job_id=BuildJobId(str(payload["job_id"])),
                revision=int(payload["revision"]),
                worker=WorkerIdentity(
                    worker_id=str(worker["worker_id"]),
                    runner_backend=str(worker["runner_backend"]),
                ),
                lease_token=str(payload["lease_token"]),
                lease_expires_at=_datetime_from_json(payload["lease_expires_at"]),
            )
        except (OSError, TypeError, ValueError, KeyError):
            self._record_warning("BUILD_JOB_STORE_CORRUPT_LEASE", "lease", str(job_id))
            return None

    def _load_all_lease_records(self) -> list[BuildJobLease]:
        if not os.path.isdir(self.leases_dir):
            return []
        leases: list[BuildJobLease] = []
        for path in Path(self.leases_dir).glob("*.json"):
            try:
                job_id = BuildJobId(path.stem)
            except ValueError:
                self._record_warning("BUILD_JOB_STORE_CORRUPT_LEASE", "lease", path.stem)
                continue
            lease = self._load_lease_record(job_id)
            if lease is not None:
                leases.append(lease)
        return leases

    def _remove_lease_record(self, job_id: BuildJobId) -> None:
        try:
            os.remove(self._lease_path(job_id))
        except FileNotFoundError:
            pass

    def _remove_idempotency_indexes_for_job(self, job_id: BuildJobId) -> None:
        if not os.path.isdir(self.idempotency_dir):
            return
        for path in Path(self.idempotency_dir).glob("*.json"):
            try:
                with open(path, "r", encoding="utf-8") as file:
                    payload = json.load(file)
                if isinstance(payload, Mapping) and str(payload.get("job_id") or "") == str(job_id):
                    os.remove(path)
            except (OSError, TypeError, ValueError):
                self._record_warning(
                    "BUILD_JOB_STORE_CORRUPT_IDEMPOTENCY",
                    "idempotency",
                    path.stem[:12],
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

    def _validate_lease(self, snapshot: BuildJobSnapshot, lease: BuildJobLease) -> None:
        record = self._load_lease_record(snapshot.job_id)
        if (
            record is None
            or snapshot.job_id != lease.job_id
            or snapshot.lease_token != lease.lease_token
            or record.lease_token != lease.lease_token
        ):
            raise BuildJobLeaseLostError("Build job lease is no longer owned by this worker.")

    def _scan_for_corruption(self) -> None:
        if not os.path.isdir(self.jobs_dir):
            return
        for path in Path(self.jobs_dir).glob("*.json"):
            try:
                job_id = BuildJobId(path.stem)
            except ValueError:
                self._record_warning("BUILD_JOB_STORE_CORRUPT_RECORD", "job", path.stem)
                continue
            self._load_envelope(job_id)

    def _record_warning(self, code: str, component: str, identifier: str) -> None:
        normalized_identifier = str(identifier or "")[:24]
        warning_key = (code, component, normalized_identifier)
        if any(
            (warning.code, warning.component, warning.identifier) == warning_key
            for warning in self._warnings
        ):
            return
        self._warnings.append(
            BuildJobRepositoryWarning(
                code=code,
                component=component,
                identifier=normalized_identifier,
                detected_at=self._now().isoformat(),
            )
        )


def validate_idempotency_key(value: str) -> str:
    key = str(value or "")
    if not key:
        return ""
    if not _IDEMPOTENCY_KEY_PATTERN.fullmatch(key):
        raise ValueError("invalid Idempotency-Key")
    if any(character in key for character in _IDEMPOTENCY_FORBIDDEN_CHARS):
        raise ValueError("invalid Idempotency-Key")
    return key


def _encode_cursor(created_at: str, job_id: str) -> str:
    payload = json.dumps(
        {"created_at": created_at, "job_id": job_id},
        separators=(",", ":"),
    )
    return base64.urlsafe_b64encode(payload.encode("utf-8")).decode("ascii")


def _decode_cursor(cursor: str) -> tuple[str, str] | None:
    if not cursor:
        return None
    try:
        raw = base64.urlsafe_b64decode(cursor.encode("ascii")).decode("utf-8")
        payload = json.loads(raw)
        if not isinstance(payload, Mapping):
            raise ValueError
        if set(payload) != {"created_at", "job_id"}:
            raise ValueError
        created_at = str(payload.get("created_at") or "")
        job_id = str(payload.get("job_id") or "")
        if not created_at or not job_id:
            raise ValueError
        return created_at, job_id
    except (OSError, TypeError, ValueError):
        raise ValueError("invalid build job cursor") from None


def _lease_expires_at(now: datetime, settings: BuildJobRepositorySettings) -> datetime:
    return now + timedelta(seconds=float(settings.lease_seconds))


def _datetime_from_json(value: object) -> datetime:
    text = str(value or "")
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    return datetime.fromisoformat(text)


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
