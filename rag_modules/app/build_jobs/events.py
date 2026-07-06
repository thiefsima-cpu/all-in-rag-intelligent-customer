"""Versioned build-job domain events."""

from __future__ import annotations

import copy
from collections.abc import Mapping
from dataclasses import dataclass, fields, is_dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any

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


@dataclass(frozen=True, slots=True)
class JobSucceeded:
    message: str = "Knowledge base build completed."
    result: Mapping[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class JobFailed:
    message: str = "Build failed."


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


def event_to_dict(event: BuildJobEvent) -> dict[str, Any]:
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


def event_from_dict(payload: Mapping[str, Any]) -> BuildJobEvent:
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
    schema_version = int(payload.get("schema_version", 0))
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
        revision=int(payload["revision"]),
        event_type=event_type,
        schema_version=schema_version,
        occurred_at=_datetime_from_json(payload["occurred_at"]),
        request_id=str(payload["request_id"]),
        payload=event_payload,
    )


def _payload_from_dict(
    event_type: BuildJobEventType,
    payload: Mapping[str, Any],
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
        return JobCancelled(message=str(payload.get("message") or ""))
    if payload_class is JobSucceeded:
        result = payload.get("result")
        return JobSucceeded(
            message=str(payload.get("message") or ""),
            result=copy.deepcopy(dict(result)) if isinstance(result, Mapping) else None,
        )
    if payload_class is JobFailed:
        return JobFailed(message=str(payload.get("message") or ""))
    if payload_class is JobInterrupted:
        return JobInterrupted(message=str(payload.get("message") or ""))
    raise ValueError("unknown build job event payload")


def _reject_unknown_keys(payload: Mapping[str, Any], valid_keys: set[str]) -> None:
    unknown = set(payload) - valid_keys
    if unknown:
        raise ValueError(f"unknown build job event keys: {', '.join(sorted(unknown))}")


def _value_to_json(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, BuildJobId):
        return str(value)
    if is_dataclass(value):
        return {field.name: _value_to_json(getattr(value, field.name)) for field in fields(value)}
    if isinstance(value, Mapping):
        return {str(key): _value_to_json(item) for key, item in value.items()}
    if isinstance(value, tuple | list):
        return [_value_to_json(item) for item in value]
    return copy.deepcopy(value)


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
]
