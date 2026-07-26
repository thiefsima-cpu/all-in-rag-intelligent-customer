"""File storage primitives for build-job repository records."""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from rag_modules.contracts.build_jobs import (
    BuildJobId,
    BuildJobLease,
    BuildJobLeaseLostError,
    BuildJobRepositoryError,
    BuildJobRepositoryWarning,
    BuildJobSnapshot,
    WorkerIdentity,
)
from rag_modules.runtime.artifacts import write_json_atomic

from .file_repository_codecs import datetime_from_json
from .file_repository_events import TERMINAL_STATUSES
from .locks import InterprocessFileLock
from .serialization import (
    BUILD_JOB_ENVELOPE_SCHEMA_VERSION,
    BuildJobEnvelope,
    envelope_from_dict,
    envelope_to_dict,
)

if TYPE_CHECKING:
    from .file_repository import FileBuildJobRepository


def ensure_directories(repository: FileBuildJobRepository) -> None:
    os.makedirs(repository.jobs_dir, exist_ok=True)
    os.makedirs(repository.archive_dir, exist_ok=True)
    os.makedirs(repository.idempotency_dir, exist_ok=True)
    os.makedirs(repository.leases_dir, exist_ok=True)


def ensure_v3_repository_or_empty(repository: FileBuildJobRepository) -> None:
    if not os.path.exists(repository.repository_dir):
        return
    if not os.path.exists(repository.metadata_path):
        if any(Path(repository.repository_dir).iterdir()):
            raise BuildJobRepositoryError(
                "Build job store must be migrated to V3 before repository use."
            )
        return
    try:
        with open(repository.metadata_path, "r", encoding="utf-8") as file:
            metadata = json.load(file)
        if (
            not isinstance(metadata, Mapping)
            or int(metadata.get("schema_version", 0)) != BUILD_JOB_ENVELOPE_SCHEMA_VERSION
        ):
            raise ValueError
    except (OSError, TypeError, ValueError) as exc:
        raise BuildJobRepositoryError("Invalid build job V3 metadata.") from exc


def write_metadata_if_missing(repository: FileBuildJobRepository) -> None:
    if os.path.exists(repository.metadata_path):
        return
    write_json_atomic(
        repository.metadata_path,
        {"schema_version": BUILD_JOB_ENVELOPE_SCHEMA_VERSION},
    )


@contextmanager
def store_lock(repository: FileBuildJobRepository) -> Iterator[None]:
    with repository._lock:
        with InterprocessFileLock(repository._store_lock_path):
            yield


def job_path(repository: FileBuildJobRepository, job_id: BuildJobId) -> str:
    return os.path.join(repository.jobs_dir, f"{job_id}.json")


def archived_job_path(repository: FileBuildJobRepository, job_id: BuildJobId) -> str:
    return os.path.join(repository.archive_dir, f"{job_id}.json")


def archived_at_path(repository: FileBuildJobRepository, job_id: BuildJobId) -> str:
    return os.path.join(repository.archive_dir, f"{job_id}.archived-at")


def idempotency_path(repository: FileBuildJobRepository, key_hash: str) -> str:
    return os.path.join(repository.idempotency_dir, f"{key_hash}.json")


def lease_path(repository: FileBuildJobRepository, job_id: BuildJobId) -> str:
    return os.path.join(repository.leases_dir, f"{job_id}.json")


def load_envelope(
    repository: FileBuildJobRepository,
    job_id: BuildJobId,
) -> BuildJobEnvelope | None:
    return _load_envelope(repository, job_id, job_path(repository, job_id), "job")


def load_archived_envelope(
    repository: FileBuildJobRepository,
    job_id: BuildJobId,
) -> BuildJobEnvelope | None:
    return _load_envelope(repository, job_id, archived_job_path(repository, job_id), "archive")


def _load_envelope(
    repository: FileBuildJobRepository,
    job_id: BuildJobId,
    path: str,
    component: str,
) -> BuildJobEnvelope | None:
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
        record_warning(repository, "BUILD_JOB_STORE_CORRUPT_RECORD", component, str(job_id))
        return None


def load_any_envelope(
    repository: FileBuildJobRepository,
    job_id: BuildJobId,
) -> BuildJobEnvelope | None:
    active_path = job_path(repository, job_id)
    active = load_envelope(repository, job_id)
    if active is not None or os.path.exists(active_path):
        return active
    return load_archived_envelope(repository, job_id)


def require_envelope(
    repository: FileBuildJobRepository,
    job_id: BuildJobId,
) -> BuildJobEnvelope:
    envelope = load_envelope(repository, job_id)
    if envelope is None:
        raise BuildJobRepositoryError(f"Build job not found: {job_id}")
    return envelope


def load_all_envelopes(repository: FileBuildJobRepository) -> list[BuildJobEnvelope]:
    if not os.path.isdir(repository.jobs_dir):
        return []
    envelopes: list[BuildJobEnvelope] = []
    for path in Path(repository.jobs_dir).glob("*.json"):
        try:
            job_id = BuildJobId(path.stem)
        except ValueError:
            record_warning(repository, "BUILD_JOB_STORE_CORRUPT_RECORD", "job", path.stem)
            continue
        envelope = load_envelope(repository, job_id)
        if envelope is not None:
            envelopes.append(envelope)
    return envelopes


def load_all_archived_envelopes(repository: FileBuildJobRepository) -> list[BuildJobEnvelope]:
    if not os.path.isdir(repository.archive_dir):
        return []
    envelopes: list[BuildJobEnvelope] = []
    for path in Path(repository.archive_dir).glob("*.json"):
        try:
            job_id = BuildJobId(path.stem)
        except ValueError:
            record_warning(repository, "BUILD_JOB_STORE_CORRUPT_RECORD", "archive", path.stem)
            continue
        envelope = load_archived_envelope(repository, job_id)
        if envelope is not None:
            envelopes.append(envelope)
    return envelopes


def load_all_snapshots(repository: FileBuildJobRepository) -> list[BuildJobSnapshot]:
    return [envelope.snapshot for envelope in load_all_envelopes(repository)]


def write_envelope(
    repository: FileBuildJobRepository,
    envelope: BuildJobEnvelope,
) -> None:
    write_json_atomic(job_path(repository, envelope.snapshot.job_id), envelope_to_dict(envelope))


def archive_envelope(repository: FileBuildJobRepository, job_id: BuildJobId) -> None:
    source_path = job_path(repository, job_id)
    if not os.path.exists(source_path):
        return
    os.replace(source_path, archived_job_path(repository, job_id))
    _write_text_atomic(archived_at_path(repository, job_id), repository._now().isoformat())


def load_archived_at(
    repository: FileBuildJobRepository,
    job_id: BuildJobId,
) -> datetime | None:
    path = archived_at_path(repository, job_id)
    if not os.path.exists(path):
        record_warning(repository, "BUILD_JOB_STORE_CORRUPT_RECORD", "archive", str(job_id))
        return None
    try:
        with open(path, "r", encoding="utf-8") as file:
            archived_at = datetime_from_json(file.read())
        if archived_at.tzinfo is None:
            raise ValueError
        return archived_at
    except (OSError, TypeError, ValueError):
        record_warning(repository, "BUILD_JOB_STORE_CORRUPT_RECORD", "archive", str(job_id))
        return None


def recover_missing_archived_at(repository: FileBuildJobRepository, job_id: BuildJobId) -> None:
    path = archived_at_path(repository, job_id)
    if not os.path.exists(path):
        _write_text_atomic(path, repository._now().isoformat())


def remove_archived_envelope(repository: FileBuildJobRepository, job_id: BuildJobId) -> None:
    for path in (archived_job_path(repository, job_id), archived_at_path(repository, job_id)):
        try:
            os.remove(path)
        except FileNotFoundError:
            pass


def _write_text_atomic(path: str, value: str) -> None:
    parent_dir = os.path.dirname(path) or "."
    os.makedirs(parent_dir, exist_ok=True)
    temporary_path = ""
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=parent_dir,
            prefix=f".{os.path.basename(path)}.",
            suffix=".tmp",
            delete=False,
        ) as file:
            temporary_path = file.name
            file.write(value)
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary_path, path)
    finally:
        if temporary_path and os.path.exists(temporary_path):
            os.remove(temporary_path)


def write_lease_record(
    repository: FileBuildJobRepository,
    lease: BuildJobLease,
) -> None:
    write_json_atomic(
        lease_path(repository, lease.job_id),
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


def load_lease_record(
    repository: FileBuildJobRepository,
    job_id: BuildJobId,
) -> BuildJobLease | None:
    path = lease_path(repository, job_id)
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
            lease_expires_at=datetime_from_json(payload["lease_expires_at"]),
        )
    except (OSError, TypeError, ValueError, KeyError):
        record_warning(repository, "BUILD_JOB_STORE_CORRUPT_LEASE", "lease", str(job_id))
        return None


def load_all_lease_records(repository: FileBuildJobRepository) -> list[BuildJobLease]:
    if not os.path.isdir(repository.leases_dir):
        return []
    leases: list[BuildJobLease] = []
    for path in Path(repository.leases_dir).glob("*.json"):
        try:
            job_id = BuildJobId(path.stem)
        except ValueError:
            record_warning(repository, "BUILD_JOB_STORE_CORRUPT_LEASE", "lease", path.stem)
            continue
        lease = load_lease_record(repository, job_id)
        if lease is not None:
            leases.append(lease)
    return leases


def remove_lease_record(repository: FileBuildJobRepository, job_id: BuildJobId) -> None:
    try:
        os.remove(lease_path(repository, job_id))
    except FileNotFoundError:
        pass


def active_snapshot(repository: FileBuildJobRepository) -> BuildJobSnapshot | None:
    active = [
        snapshot
        for snapshot in load_all_snapshots(repository)
        if snapshot.status not in TERMINAL_STATUSES
    ]
    if not active:
        return None
    return sorted(active, key=lambda snapshot: (snapshot.created_at, snapshot.job_id))[0]


def validate_lease(
    repository: FileBuildJobRepository,
    snapshot: BuildJobSnapshot,
    lease: BuildJobLease,
) -> None:
    record = load_lease_record(repository, snapshot.job_id)
    if (
        record is None
        or snapshot.job_id != lease.job_id
        or snapshot.lease_token != lease.lease_token
        or record.lease_token != lease.lease_token
    ):
        raise BuildJobLeaseLostError("Build job lease is no longer owned by this worker.")


def record_warning(
    repository: FileBuildJobRepository,
    code: str,
    component: str,
    identifier: str,
) -> None:
    normalized_identifier = str(identifier or "")[:24]
    warning_key = (code, component, normalized_identifier)
    if any(
        (warning.code, warning.component, warning.identifier) == warning_key
        for warning in repository._warnings
    ):
        return
    repository._warnings.append(
        BuildJobRepositoryWarning(
            code=code,
            component=component,
            identifier=normalized_identifier,
            detected_at=repository._now().isoformat(),
        )
    )


__all__ = [
    "active_snapshot",
    "archive_envelope",
    "archived_at_path",
    "archived_job_path",
    "ensure_directories",
    "ensure_v3_repository_or_empty",
    "idempotency_path",
    "job_path",
    "load_all_archived_envelopes",
    "load_all_lease_records",
    "load_all_envelopes",
    "load_all_snapshots",
    "load_any_envelope",
    "load_archived_at",
    "load_archived_envelope",
    "load_envelope",
    "load_lease_record",
    "record_warning",
    "recover_missing_archived_at",
    "remove_archived_envelope",
    "remove_lease_record",
    "require_envelope",
    "store_lock",
    "validate_lease",
    "write_envelope",
    "write_lease_record",
    "write_metadata_if_missing",
]
