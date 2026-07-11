"""Build-job repository operations backed by file storage."""

from __future__ import annotations

import os
import secrets
from dataclasses import replace
from typing import TYPE_CHECKING

from rag_modules.contracts.build_jobs import (
    BuildJobConcurrentUpdateError,
    BuildJobConflictError,
    BuildJobEvent,
    BuildJobId,
    BuildJobIdempotencyConflictError,
    BuildJobLease,
    BuildJobLeaseLostError,
    BuildJobListQuery,
    BuildJobPage,
    BuildJobRepositoryDiagnostics,
    BuildJobSnapshot,
    BuildJobStatus,
    BuildJobSubmission,
    BuildJobSubmissionDisposition,
    SubmitBuildJob,
    WorkerIdentity,
    reduce_build_job,
)

from . import file_repository_codecs as codecs
from . import file_repository_diagnostics as diagnostics_scans
from . import file_repository_idempotency as idempotency
from . import file_repository_storage as storage
from .file_repository_events import (
    TERMINAL_STATUSES,
    build_lease,
    claimed_event,
    hash_idempotency_key,
    interrupted_event,
    lease_expires_at,
    new_queued_event,
    validate_idempotency_key,
)
from .serialization import BuildJobEnvelope

if TYPE_CHECKING:
    from .file_repository import FileBuildJobRepository


def submit(
    repository: FileBuildJobRepository,
    command: SubmitBuildJob,
) -> BuildJobSubmission:
    key_hash = hash_idempotency_key(validate_idempotency_key(command.idempotency_key))
    with storage.store_lock(repository):
        replay = idempotency.find_idempotent_job(repository, key_hash)
        if replay is not None:
            if replay.job_type is not command.job_type:
                raise BuildJobIdempotencyConflictError(
                    "Idempotency key conflicts with an existing build job.",
                    replay,
                )
            return BuildJobSubmission(BuildJobSubmissionDisposition.REPLAYED, replay)
        active = storage.active_snapshot(repository)
        if active is not None:
            raise BuildJobConflictError("A build job is already in progress.", active)
        event = new_queued_event(command, key_hash=key_hash, now=repository._now())
        snapshot = reduce_build_job(None, event)
        storage.write_envelope(repository, BuildJobEnvelope.new(snapshot, event))
        idempotency.write_idempotency_index(repository, key_hash, snapshot)
        apply_retention(repository)
        return BuildJobSubmission(BuildJobSubmissionDisposition.CREATED, snapshot)


def get(
    repository: FileBuildJobRepository,
    job_id: BuildJobId,
) -> BuildJobSnapshot | None:
    with storage.store_lock(repository):
        envelope = storage.load_envelope(repository, job_id)
        return envelope.snapshot if envelope is not None else None


def list_page(
    repository: FileBuildJobRepository,
    query: BuildJobListQuery,
) -> BuildJobPage:
    with storage.store_lock(repository):
        decoded_cursor = codecs.decode_cursor(query.cursor)
        limit = query.limit or repository.settings.list_default_limit
        bounded_limit = max(1, min(int(limit), repository.settings.list_max_limit))
        snapshots = sorted(
            storage.load_all_snapshots(repository),
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
            next_cursor = codecs.encode_cursor(last.created_at.isoformat(), str(last.job_id))
        return BuildJobPage(jobs=tuple(selected), next_cursor=next_cursor)


def claim_next(
    repository: FileBuildJobRepository,
    worker: WorkerIdentity,
) -> BuildJobLease | None:
    with storage.store_lock(repository):
        snapshot = next_queued_snapshot(repository)
        if snapshot is None:
            return None
        lease_token = secrets.token_urlsafe(32)
        expires_at = lease_expires_at(repository._now(), repository.settings)
        event = claimed_event(
            snapshot,
            worker=worker,
            lease_token=lease_token,
            lease_expires_at=expires_at,
            occurred_at=repository._now(),
        )
        envelope = storage.require_envelope(repository, snapshot.job_id)
        claimed = reduce_build_job(snapshot, event)
        storage.write_envelope(repository, envelope.append(claimed, event))
        lease = build_lease(
            claimed,
            worker=worker,
            lease_token=lease_token,
            lease_expires_at=expires_at,
        )
        storage.write_lease_record(repository, lease)
        return lease


def renew_lease(
    repository: FileBuildJobRepository,
    lease: BuildJobLease,
) -> BuildJobLease:
    with storage.store_lock(repository):
        envelope = storage.load_envelope(repository, lease.job_id)
        record = storage.load_lease_record(repository, lease.job_id)
        if (
            envelope is None
            or record is None
            or record.lease_token != lease.lease_token
            or envelope.snapshot.status in TERMINAL_STATUSES
        ):
            raise BuildJobLeaseLostError("Build job lease is no longer owned by this worker.")
        renewed = replace(
            lease,
            revision=envelope.snapshot.revision,
            worker=record.worker,
            lease_expires_at=lease_expires_at(repository._now(), repository.settings),
        )
        storage.write_lease_record(repository, renewed)
        return renewed


def apply(
    repository: FileBuildJobRepository,
    event: BuildJobEvent,
    *,
    expected_revision: int,
    lease: BuildJobLease | None,
) -> BuildJobSnapshot:
    with storage.store_lock(repository):
        envelope = storage.require_envelope(repository, event.job_id)
        snapshot = envelope.snapshot
        if snapshot.revision != expected_revision:
            raise BuildJobConcurrentUpdateError(
                f"Expected revision {expected_revision}, found {snapshot.revision}."
            )
        if lease is not None:
            storage.validate_lease(repository, snapshot, lease)
        updated = reduce_build_job(snapshot, event)
        storage.write_envelope(repository, envelope.append(updated, event))
        if updated.status in TERMINAL_STATUSES:
            storage.remove_lease_record(repository, updated.job_id)
        apply_retention(repository)
        return updated


def find_dispatchable(
    repository: FileBuildJobRepository,
    *,
    limit: int,
) -> tuple[BuildJobId, ...]:
    with storage.store_lock(repository):
        queued = [snapshot.job_id for snapshot in queued_snapshots(repository)]
        return tuple(queued[: max(0, int(limit))])


def recover_expired_leases(
    repository: FileBuildJobRepository,
) -> tuple[BuildJobSnapshot, ...]:
    with storage.store_lock(repository):
        recovered: list[BuildJobSnapshot] = []
        for lease in storage.load_all_lease_records(repository):
            recovered_snapshot = recover_expired_lease(repository, lease)
            if recovered_snapshot is not None:
                recovered.append(recovered_snapshot)
        apply_retention(repository)
        return tuple(recovered)


def queued_snapshots(repository: FileBuildJobRepository) -> list[BuildJobSnapshot]:
    return [
        snapshot
        for snapshot in sorted(
            storage.load_all_snapshots(repository),
            key=lambda snapshot: (snapshot.created_at, snapshot.job_id),
        )
        if snapshot.status is BuildJobStatus.QUEUED
    ]


def next_queued_snapshot(repository: FileBuildJobRepository) -> BuildJobSnapshot | None:
    queued = queued_snapshots(repository)
    return queued[0] if queued else None


def recover_expired_lease(
    repository: FileBuildJobRepository,
    lease: BuildJobLease,
) -> BuildJobSnapshot | None:
    envelope = storage.load_envelope(repository, lease.job_id)
    if envelope is None:
        storage.remove_lease_record(repository, lease.job_id)
        return None
    snapshot = envelope.snapshot
    if snapshot.status in TERMINAL_STATUSES:
        storage.remove_lease_record(repository, lease.job_id)
        return None
    if lease.lease_expires_at > repository._now():
        return None
    event = interrupted_event(snapshot, occurred_at=repository._now())
    updated = reduce_build_job(snapshot, event)
    storage.write_envelope(repository, envelope.append(updated, event))
    storage.remove_lease_record(repository, snapshot.job_id)
    return updated


def apply_retention(repository: FileBuildJobRepository) -> None:
    terminal = [
        snapshot
        for snapshot in storage.load_all_snapshots(repository)
        if snapshot.status in TERMINAL_STATUSES
    ]
    terminal.sort(
        key=lambda snapshot: (snapshot.finished_at or snapshot.created_at, snapshot.job_id),
        reverse=True,
    )
    for snapshot in terminal[max(0, repository.settings.retention_limit) :]:
        try:
            os.remove(storage.job_path(repository, snapshot.job_id))
        except FileNotFoundError:
            pass
        storage.remove_lease_record(repository, snapshot.job_id)
        idempotency.remove_idempotency_indexes_for_job(repository, snapshot.job_id)


def diagnostics(repository: FileBuildJobRepository) -> BuildJobRepositoryDiagnostics:
    with storage.store_lock(repository):
        diagnostics_scans.scan_for_corruption(repository)
        return BuildJobRepositoryDiagnostics(warnings=tuple(repository._warnings))


__all__ = [
    "apply",
    "apply_retention",
    "claim_next",
    "diagnostics",
    "find_dispatchable",
    "get",
    "list_page",
    "recover_expired_leases",
    "submit",
]
