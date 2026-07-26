"""Versioned build-job domain events."""

from __future__ import annotations

import copy
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, fields
from datetime import datetime
from enum import StrEnum

from pydantic import JsonValue

from ...kernel.json_types import JsonObject, coerce_int, coerce_json_object
from .models import BuildJobId, BuildJobType, WorkerIdentity

BUILD_JOB_EVENT_SCHEMA_VERSION = 1


class BuildJobEventType(StrEnum):
    QUEUED = "queued"
    CLAIMED = "claimed"
    STARTED = "started"
    PROGRESS_RECORDED = "progress_recorded"
    CANCELLATION_REQUESTED = "cancellation_requested"
    CANCELLED = "cancelled"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    INTERRUPTED = "interrupted"


@dataclass(frozen=True, slots=True)
class JobQueued:
    job_type: BuildJobType
    idempotency_key_hash: str = ""
    retry_of_job_id: BuildJobId | None = None


@dataclass(frozen=True, slots=True)
class JobClaimed:
    worker: WorkerIdentity
    lease_token: str
    lease_expires_at: datetime


@dataclass(frozen=True, slots=True)
class JobStarted:
    worker: WorkerIdentity


@dataclass(frozen=True, slots=True)
class JobProgressRecorded:
    message: str = "Build progress updated."


@dataclass(frozen=True, slots=True)
class JobCancellationRequested:
    message: str = "Build cancellation requested."


@dataclass(frozen=True, slots=True)
class JobCancelled:
    message: str = "Build cancelled."
    result: JsonObject | None = None


@dataclass(frozen=True, slots=True)
class JobSucceeded:
    message: str = "Knowledge base build completed."
    result: JsonObject | None = None


@dataclass(frozen=True, slots=True)
class JobFailed:
    message: str = "Build failed."
    result: JsonObject | None = None


@dataclass(frozen=True, slots=True)
class JobInterrupted:
    message: str = "Build interrupted by service restart."


BuildJobEventPayload = (
    JobQueued
    | JobClaimed
    | JobStarted
    | JobProgressRecorded
    | JobCancellationRequested
    | JobCancelled
    | JobSucceeded
    | JobFailed
    | JobInterrupted
)


@dataclass(frozen=True, slots=True)
class BuildJobEvent:
    event_id: str
    job_id: BuildJobId
    revision: int
    event_type: BuildJobEventType
    schema_version: int
    occurred_at: datetime
    request_id: str
    payload: BuildJobEventPayload


_PAYLOAD_BY_TYPE: dict[BuildJobEventType, type[BuildJobEventPayload]] = {
    BuildJobEventType.QUEUED: JobQueued,
    BuildJobEventType.CLAIMED: JobClaimed,
    BuildJobEventType.STARTED: JobStarted,
    BuildJobEventType.PROGRESS_RECORDED: JobProgressRecorded,
    BuildJobEventType.CANCELLATION_REQUESTED: JobCancellationRequested,
    BuildJobEventType.CANCELLED: JobCancelled,
    BuildJobEventType.SUCCEEDED: JobSucceeded,
    BuildJobEventType.FAILED: JobFailed,
    BuildJobEventType.INTERRUPTED: JobInterrupted,
}


def event_to_dict(event: BuildJobEvent) -> JsonObject:
    return {
        "event_id": event.event_id,
        "job_id": str(event.job_id),
        "revision": event.revision,
        "event_type": event.event_type.value,
        "schema_version": event.schema_version,
        "occurred_at": event.occurred_at.isoformat(),
        "request_id": event.request_id,
        "payload": _value_to_json(event.payload),
    }


def public_build_job_event(event: BuildJobEvent) -> JsonObject:
    """Return the explicit, privacy-safe public projection of an audit event."""

    payload = event.payload
    if isinstance(payload, JobQueued):
        public_payload: JsonObject = {
            "job_type": payload.job_type.value,
            "retry_of_job_id": str(payload.retry_of_job_id or ""),
        }
    elif isinstance(payload, JobClaimed):
        public_payload = {
            "worker": {
                "worker_id": payload.worker.worker_id,
                "runner_backend": payload.worker.runner_backend,
            },
            "lease_expires_at": payload.lease_expires_at.isoformat(),
        }
    elif isinstance(payload, JobStarted):
        public_payload = {
            "worker": {
                "worker_id": payload.worker.worker_id,
                "runner_backend": payload.worker.runner_backend,
            }
        }
    elif isinstance(payload, JobProgressRecorded):
        public_payload = {"message": "Build progress updated."}
    elif isinstance(payload, JobCancellationRequested):
        public_payload = {"message": "Build cancellation requested."}
    elif isinstance(payload, JobCancelled):
        public_payload = {
            "message": "Build cancelled.",
            "result": _public_terminal_result(payload.result, "Build cancelled."),
        }
    elif isinstance(payload, JobSucceeded):
        public_payload = {
            "message": "Knowledge base build completed.",
            "result": _public_terminal_result(
                payload.result,
                "Knowledge base build completed.",
            ),
        }
    elif isinstance(payload, JobFailed):
        public_payload = {
            "message": "Build failed.",
            "result": _public_terminal_result(payload.result, "Build failed."),
        }
    elif isinstance(payload, JobInterrupted):
        public_payload = {"message": "Build interrupted by service restart."}
    else:
        raise ValueError("unknown build job event payload")

    return coerce_json_object(
        {
            "event_id": event.event_id,
            "job_id": str(event.job_id),
            "revision": event.revision,
            "event_type": event.event_type.value,
            "schema_version": event.schema_version,
            "occurred_at": event.occurred_at.isoformat(),
            "request_id": event.request_id,
            "payload": public_payload,
        }
    )


def _public_terminal_result(result: JsonObject | None, message: str) -> JsonObject | None:
    if result is None:
        return None
    return {"message": message}


def event_from_dict(payload: Mapping[str, object]) -> BuildJobEvent:
    _reject_unknown_keys(
        payload,
        {
            "event_id",
            "job_id",
            "revision",
            "event_type",
            "schema_version",
            "occurred_at",
            "request_id",
            "payload",
        },
    )
    schema_version = coerce_int(payload.get("schema_version"))
    if schema_version != BUILD_JOB_EVENT_SCHEMA_VERSION:
        raise ValueError("unsupported build job event schema version")
    try:
        event_type = BuildJobEventType(str(payload["event_type"]))
    except ValueError as exc:
        raise ValueError("unknown build job event type") from exc
    payload_class = _PAYLOAD_BY_TYPE.get(event_type)
    if payload_class is None:
        raise ValueError("unknown build job event type")
    raw_event_payload = payload.get("payload")
    if not isinstance(raw_event_payload, Mapping):
        raise ValueError("build job event payload must be an object")
    event_payload = _payload_from_dict(event_type, raw_event_payload)
    return BuildJobEvent(
        event_id=str(payload["event_id"]),
        job_id=BuildJobId(str(payload["job_id"])),
        revision=coerce_int(payload["revision"]),
        event_type=event_type,
        schema_version=schema_version,
        occurred_at=_datetime_from_json(payload["occurred_at"]),
        request_id=str(payload["request_id"]),
        payload=event_payload,
    )


def _payload_from_dict(
    event_type: BuildJobEventType,
    payload: Mapping[str, object],
) -> BuildJobEventPayload:
    payload_class = _PAYLOAD_BY_TYPE[event_type]
    valid_keys = {field.name for field in fields(payload_class)}
    _reject_unknown_keys(payload, valid_keys)

    if payload_class is JobQueued:
        retry_of_job_id = payload.get("retry_of_job_id")
        return JobQueued(
            job_type=BuildJobType(str(payload["job_type"])),
            idempotency_key_hash=str(payload.get("idempotency_key_hash") or ""),
            retry_of_job_id=BuildJobId(str(retry_of_job_id)) if retry_of_job_id else None,
        )
    if payload_class is JobClaimed:
        return JobClaimed(
            worker=_worker_from_json(payload.get("worker")),
            lease_token=str(payload["lease_token"]),
            lease_expires_at=_datetime_from_json(payload["lease_expires_at"]),
        )
    if payload_class is JobStarted:
        return JobStarted(worker=_worker_from_json(payload.get("worker")))
    if payload_class is JobProgressRecorded:
        return JobProgressRecorded(message=str(payload.get("message") or ""))
    if payload_class is JobCancellationRequested:
        return JobCancellationRequested(message=str(payload.get("message") or ""))
    if payload_class is JobCancelled:
        result = payload.get("result")
        return JobCancelled(
            message=str(payload.get("message") or ""),
            result=coerce_json_object(result) if isinstance(result, Mapping) else None,
        )
    if payload_class is JobSucceeded:
        result = payload.get("result")
        return JobSucceeded(
            message=str(payload.get("message") or ""),
            result=coerce_json_object(result) if isinstance(result, Mapping) else None,
        )
    if payload_class is JobFailed:
        result = payload.get("result")
        return JobFailed(
            message=str(payload.get("message") or ""),
            result=coerce_json_object(result) if isinstance(result, Mapping) else None,
        )
    if payload_class is JobInterrupted:
        return JobInterrupted(message=str(payload.get("message") or ""))
    raise ValueError("unknown build job event payload")


def _reject_unknown_keys(payload: Mapping[str, object], valid_keys: set[str]) -> None:
    unknown = set(payload) - valid_keys
    if unknown:
        raise ValueError(f"unknown build job event keys: {', '.join(sorted(unknown))}")


def _value_to_json(value: object) -> JsonValue:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(
        value,
        (
            JobQueued,
            JobClaimed,
            JobStarted,
            JobProgressRecorded,
            JobCancellationRequested,
            JobCancelled,
            JobSucceeded,
            JobFailed,
            JobInterrupted,
        ),
    ):
        return _value_to_json(asdict(value))
    if isinstance(value, Mapping):
        return {str(key): _value_to_json(item) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_value_to_json(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return copy.deepcopy(value)
    return str(value)


def _datetime_from_json(value: object) -> datetime:
    text = str(value or "")
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    return datetime.fromisoformat(text)


def _worker_from_json(value: object) -> WorkerIdentity:
    if not isinstance(value, Mapping):
        raise ValueError("worker must be an object")
    _reject_unknown_keys(value, {"worker_id", "runner_backend"})
    return WorkerIdentity(
        worker_id=str(value["worker_id"]),
        runner_backend=str(value["runner_backend"]),
    )


__all__ = [
    "BUILD_JOB_EVENT_SCHEMA_VERSION",
    "BuildJobEvent",
    "BuildJobEventPayload",
    "BuildJobEventType",
    "JobCancellationRequested",
    "JobCancelled",
    "JobClaimed",
    "JobFailed",
    "JobInterrupted",
    "JobProgressRecorded",
    "JobQueued",
    "JobStarted",
    "JobSucceeded",
    "event_from_dict",
    "event_to_dict",
    "public_build_job_event",
]
