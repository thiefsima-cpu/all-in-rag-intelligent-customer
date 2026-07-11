"""Build-job repository event and key helpers."""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timedelta

from rag_modules.contracts.build_jobs import (
    BuildJobEvent,
    BuildJobEventType,
    BuildJobLease,
    BuildJobRepositorySettings,
    BuildJobSnapshot,
    BuildJobStatus,
    JobClaimed,
    JobInterrupted,
    JobQueued,
    SubmitBuildJob,
    WorkerIdentity,
)

_IDEMPOTENCY_KEY_PATTERN = re.compile(r"[!-~]{1,128}\Z", flags=re.ASCII)
_IDEMPOTENCY_FORBIDDEN_CHARS = frozenset({"/", "\\"})

TERMINAL_STATUSES = frozenset(
    {
        BuildJobStatus.SUCCEEDED,
        BuildJobStatus.FAILED,
        BuildJobStatus.CANCELLED,
        BuildJobStatus.INTERRUPTED,
    }
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


def claimed_event(
    snapshot: BuildJobSnapshot,
    *,
    worker: WorkerIdentity,
    lease_token: str,
    lease_expires_at: datetime,
    occurred_at: datetime,
) -> BuildJobEvent:
    return BuildJobEvent(
        event_id=f"{snapshot.job_id}:{snapshot.revision + 1}",
        job_id=snapshot.job_id,
        revision=snapshot.revision + 1,
        event_type=BuildJobEventType.CLAIMED,
        schema_version=1,
        occurred_at=occurred_at,
        request_id=snapshot.request_id,
        payload=JobClaimed(
            worker=worker,
            lease_token=lease_token,
            lease_expires_at=lease_expires_at,
        ),
    )


def build_lease(
    snapshot: BuildJobSnapshot,
    *,
    worker: WorkerIdentity,
    lease_token: str,
    lease_expires_at: datetime,
) -> BuildJobLease:
    return BuildJobLease(
        job_id=snapshot.job_id,
        revision=snapshot.revision,
        worker=worker,
        lease_token=lease_token,
        lease_expires_at=lease_expires_at,
    )


def interrupted_event(
    snapshot: BuildJobSnapshot,
    *,
    occurred_at: datetime,
) -> BuildJobEvent:
    return BuildJobEvent(
        event_id=f"{snapshot.job_id}:{snapshot.revision + 1}",
        job_id=snapshot.job_id,
        revision=snapshot.revision + 1,
        event_type=BuildJobEventType.INTERRUPTED,
        schema_version=1,
        occurred_at=occurred_at,
        request_id=snapshot.request_id,
        payload=JobInterrupted(),
    )


def lease_expires_at(now: datetime, settings: BuildJobRepositorySettings) -> datetime:
    return now + timedelta(seconds=float(settings.lease_seconds))


__all__ = [
    "TERMINAL_STATUSES",
    "build_lease",
    "claimed_event",
    "hash_idempotency_key",
    "interrupted_event",
    "lease_expires_at",
    "new_queued_event",
    "validate_idempotency_key",
]
