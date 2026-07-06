"""Pure build-job event reducer."""

from __future__ import annotations

import copy
from dataclasses import replace

from .errors import BuildJobInvalidTransitionError
from .events import (
    BuildJobEvent,
    BuildJobEventType,
    JobCancellationRequested,
    JobCancelled,
    JobClaimed,
    JobFailed,
    JobInterrupted,
    JobProgressRecorded,
    JobQueued,
    JobStarted,
    JobSucceeded,
)
from .models import BUILD_JOB_LOG_LIMIT, BuildJobSnapshot, BuildJobStatus, build_failed_error

_ALLOWED_EVENTS = {
    BuildJobStatus.QUEUED: {
        BuildJobEventType.CLAIMED,
        BuildJobEventType.CANCELLATION_REQUESTED,
    },
    BuildJobStatus.CLAIMED: {
        BuildJobEventType.STARTED,
        BuildJobEventType.CANCELLATION_REQUESTED,
        BuildJobEventType.INTERRUPTED,
    },
    BuildJobStatus.RUNNING: {
        BuildJobEventType.PROGRESS_RECORDED,
        BuildJobEventType.CANCELLATION_REQUESTED,
        BuildJobEventType.SUCCEEDED,
        BuildJobEventType.FAILED,
        BuildJobEventType.INTERRUPTED,
    },
    BuildJobStatus.CANCEL_REQUESTED: {
        BuildJobEventType.PROGRESS_RECORDED,
        BuildJobEventType.CANCELLED,
        BuildJobEventType.SUCCEEDED,
        BuildJobEventType.FAILED,
        BuildJobEventType.INTERRUPTED,
    },
}
_TERMINAL_STATUSES = frozenset(
    {
        BuildJobStatus.SUCCEEDED,
        BuildJobStatus.FAILED,
        BuildJobStatus.CANCELLED,
        BuildJobStatus.INTERRUPTED,
    }
)


def reduce_build_job(
    snapshot: BuildJobSnapshot | None,
    event: BuildJobEvent,
) -> BuildJobSnapshot:
    if snapshot is None:
        return _reduce_initial_event(event)

    if snapshot.job_id != event.job_id:
        raise BuildJobInvalidTransitionError("event job id does not match snapshot")
    if event.revision != snapshot.revision + 1:
        raise BuildJobInvalidTransitionError("event revision must follow snapshot revision")
    if snapshot.status in _TERMINAL_STATUSES:
        raise BuildJobInvalidTransitionError("terminal build job snapshots cannot transition")
    if event.event_type not in _ALLOWED_EVENTS.get(snapshot.status, set()):
        raise BuildJobInvalidTransitionError(
            f"{event.event_type.value} is not allowed from {snapshot.status.value}"
        )

    next_snapshot = _apply_allowed_event(snapshot, event)
    return replace(next_snapshot, revision=event.revision)


def _reduce_initial_event(event: BuildJobEvent) -> BuildJobSnapshot:
    if event.revision != 1:
        raise BuildJobInvalidTransitionError("first build job event must have revision 1")
    if event.event_type is not BuildJobEventType.QUEUED or not isinstance(event.payload, JobQueued):
        raise BuildJobInvalidTransitionError("first build job event must be queued")
    return BuildJobSnapshot(
        job_id=event.job_id,
        request_id=event.request_id,
        job_type=event.payload.job_type,
        status=BuildJobStatus.QUEUED,
        revision=event.revision,
        created_at=event.occurred_at,
        retry_of_job_id=event.payload.retry_of_job_id,
        idempotency_key_hash=event.payload.idempotency_key_hash,
    )


def _apply_allowed_event(snapshot: BuildJobSnapshot, event: BuildJobEvent) -> BuildJobSnapshot:
    payload = event.payload
    if event.event_type is BuildJobEventType.CLAIMED and isinstance(payload, JobClaimed):
        return replace(
            snapshot,
            status=BuildJobStatus.CLAIMED,
            worker=payload.worker,
            lease_token=payload.lease_token,
            lease_expires_at=payload.lease_expires_at,
        )
    if event.event_type is BuildJobEventType.STARTED and isinstance(payload, JobStarted):
        return replace(
            snapshot,
            status=BuildJobStatus.RUNNING,
            started_at=snapshot.started_at or event.occurred_at,
            worker=payload.worker,
        )
    if event.event_type is BuildJobEventType.PROGRESS_RECORDED and isinstance(
        payload, JobProgressRecorded
    ):
        return replace(
            snapshot,
            message=payload.message,
            logs=_append_log(snapshot.logs, payload.message),
        )
    if event.event_type is BuildJobEventType.CANCELLATION_REQUESTED and isinstance(
        payload, JobCancellationRequested
    ):
        return replace(
            snapshot,
            status=BuildJobStatus.CANCEL_REQUESTED,
            message=payload.message,
            logs=_append_log(snapshot.logs, payload.message),
        )
    if event.event_type is BuildJobEventType.CANCELLED and isinstance(payload, JobCancelled):
        return replace(
            snapshot,
            status=BuildJobStatus.CANCELLED,
            finished_at=event.occurred_at,
            message=payload.message,
            logs=_append_log(snapshot.logs, payload.message),
            lease_token="",
            lease_expires_at=None,
        )
    if event.event_type is BuildJobEventType.SUCCEEDED and isinstance(payload, JobSucceeded):
        return replace(
            snapshot,
            status=BuildJobStatus.SUCCEEDED,
            finished_at=event.occurred_at,
            message=payload.message,
            result=copy.deepcopy(dict(payload.result)) if payload.result is not None else None,
            lease_token="",
            lease_expires_at=None,
        )
    if event.event_type is BuildJobEventType.FAILED and isinstance(payload, JobFailed):
        return replace(
            snapshot,
            status=BuildJobStatus.FAILED,
            finished_at=event.occurred_at,
            message=payload.message,
            error=build_failed_error(snapshot.request_id),
            logs=_append_log(snapshot.logs, payload.message),
            lease_token="",
            lease_expires_at=None,
        )
    if event.event_type is BuildJobEventType.INTERRUPTED and isinstance(payload, JobInterrupted):
        return replace(
            snapshot,
            status=BuildJobStatus.INTERRUPTED,
            finished_at=event.occurred_at,
            message=payload.message,
            error=build_failed_error(snapshot.request_id),
            logs=_append_log(snapshot.logs, payload.message),
            lease_token="",
            lease_expires_at=None,
        )
    raise BuildJobInvalidTransitionError("event payload does not match event type")


def _append_log(logs: tuple[str, ...], message: str) -> tuple[str, ...]:
    return (*logs, message)[-BUILD_JOB_LOG_LIMIT:]


__all__ = ["reduce_build_job"]
