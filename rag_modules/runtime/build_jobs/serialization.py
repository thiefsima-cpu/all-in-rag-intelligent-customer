"""V3 build-job repository serialization."""

from __future__ import annotations

import copy
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from rag_modules.contracts.build_jobs import (
    BuildJobEvent,
    BuildJobId,
    BuildJobSnapshot,
    BuildJobStatus,
    BuildJobType,
    WorkerIdentity,
    event_from_dict,
    event_to_dict,
    reduce_build_job,
)

BUILD_JOB_ENVELOPE_SCHEMA_VERSION = 3

_ENVELOPE_KEYS = frozenset({"schema_version", "revision", "baseline", "snapshot", "events"})
_SNAPSHOT_KEYS = frozenset(
    {
        "job_id",
        "request_id",
        "job_type",
        "status",
        "revision",
        "created_at",
        "started_at",
        "finished_at",
        "message",
        "error",
        "logs",
        "result",
        "retry_of_job_id",
        "idempotency_key_hash",
        "worker",
        "lease_token",
        "lease_expires_at",
    }
)


@dataclass(frozen=True, slots=True)
class BuildJobEnvelope:
    revision: int
    baseline: BuildJobSnapshot | None
    snapshot: BuildJobSnapshot
    events: tuple[BuildJobEvent, ...]

    @classmethod
    def new(cls, snapshot: BuildJobSnapshot, event: BuildJobEvent) -> "BuildJobEnvelope":
        if snapshot.revision != event.revision:
            raise ValueError("snapshot revision must match event revision")
        return cls(revision=snapshot.revision, baseline=None, snapshot=snapshot, events=(event,))

    def append(self, snapshot: BuildJobSnapshot, event: BuildJobEvent) -> "BuildJobEnvelope":
        if event.revision != self.revision + 1:
            raise ValueError("event revision must follow envelope revision")
        if snapshot.revision != event.revision:
            raise ValueError("snapshot revision must match event revision")
        return BuildJobEnvelope(
            revision=snapshot.revision,
            baseline=self.baseline,
            snapshot=snapshot,
            events=(*self.events, event),
        )


def snapshot_to_dict(snapshot: BuildJobSnapshot) -> dict[str, Any]:
    return {
        "job_id": str(snapshot.job_id),
        "request_id": snapshot.request_id,
        "job_type": snapshot.job_type.value,
        "status": snapshot.status.value,
        "revision": snapshot.revision,
        "created_at": _datetime_to_json(snapshot.created_at),
        "started_at": _datetime_to_json(snapshot.started_at),
        "finished_at": _datetime_to_json(snapshot.finished_at),
        "message": snapshot.message,
        "error": copy.deepcopy(dict(snapshot.error)) if snapshot.error is not None else None,
        "logs": list(snapshot.logs),
        "result": copy.deepcopy(dict(snapshot.result)) if snapshot.result is not None else None,
        "retry_of_job_id": str(snapshot.retry_of_job_id or ""),
        "idempotency_key_hash": snapshot.idempotency_key_hash,
        "worker": _worker_to_dict(snapshot.worker),
        "lease_token": snapshot.lease_token,
        "lease_expires_at": _datetime_to_json(snapshot.lease_expires_at),
    }


def snapshot_from_dict(payload: Mapping[str, Any]) -> BuildJobSnapshot:
    _reject_unknown_keys(payload, _SNAPSHOT_KEYS, "build job snapshot")
    error = payload.get("error")
    result = payload.get("result")
    retry_of_job_id = str(payload.get("retry_of_job_id") or "")
    return BuildJobSnapshot(
        job_id=BuildJobId(str(payload["job_id"])),
        request_id=str(payload["request_id"]),
        job_type=BuildJobType(str(payload["job_type"])),
        status=BuildJobStatus(str(payload["status"])),
        revision=int(payload["revision"]),
        created_at=_datetime_from_json(payload["created_at"]),
        started_at=_optional_datetime_from_json(payload.get("started_at")),
        finished_at=_optional_datetime_from_json(payload.get("finished_at")),
        message=str(payload.get("message") or ""),
        error=copy.deepcopy(dict(error)) if isinstance(error, Mapping) else None,
        logs=tuple(str(item) for item in list(payload.get("logs") or [])),
        result=copy.deepcopy(dict(result)) if isinstance(result, Mapping) else None,
        retry_of_job_id=BuildJobId(retry_of_job_id) if retry_of_job_id else None,
        idempotency_key_hash=str(payload.get("idempotency_key_hash") or ""),
        worker=_optional_worker_from_dict(payload.get("worker")),
        lease_token=str(payload.get("lease_token") or ""),
        lease_expires_at=_optional_datetime_from_json(payload.get("lease_expires_at")),
    )


def envelope_to_dict(envelope: BuildJobEnvelope) -> dict[str, Any]:
    return {
        "schema_version": BUILD_JOB_ENVELOPE_SCHEMA_VERSION,
        "revision": envelope.revision,
        "baseline": snapshot_to_dict(envelope.baseline) if envelope.baseline is not None else None,
        "snapshot": snapshot_to_dict(envelope.snapshot),
        "events": [event_to_dict(event) for event in envelope.events],
    }


def envelope_from_dict(payload: Mapping[str, Any]) -> BuildJobEnvelope:
    _reject_unknown_keys(payload, _ENVELOPE_KEYS, "build job envelope")
    if int(payload.get("schema_version", 0)) != BUILD_JOB_ENVELOPE_SCHEMA_VERSION:
        raise ValueError("unsupported build job envelope schema version")

    raw_baseline = payload.get("baseline")
    if raw_baseline is not None and not isinstance(raw_baseline, Mapping):
        raise ValueError("build job envelope baseline must be an object or null")
    raw_snapshot = payload.get("snapshot")
    if not isinstance(raw_snapshot, Mapping):
        raise ValueError("build job envelope snapshot must be an object")
    raw_events = payload.get("events")
    if not isinstance(raw_events, list):
        raise ValueError("build job envelope events must be a list")

    baseline = snapshot_from_dict(raw_baseline) if isinstance(raw_baseline, Mapping) else None
    snapshot = snapshot_from_dict(raw_snapshot)
    events = tuple(
        event_from_dict(event) if isinstance(event, Mapping) else _raise_invalid_event()
        for event in raw_events
    )
    revision = int(payload["revision"])
    if revision != snapshot.revision:
        raise ValueError("build job envelope revision does not match snapshot")
    _validate_event_revisions(baseline, events)

    reduced: BuildJobSnapshot | None = baseline
    for event in events:
        reduced = reduce_build_job(reduced, event)
    if reduced is None:
        raise ValueError("build job envelope must contain a baseline or events")
    if snapshot_to_dict(reduced) != snapshot_to_dict(snapshot):
        raise ValueError("build job envelope snapshot does not match reduced events")
    return BuildJobEnvelope(
        revision=revision,
        baseline=baseline,
        snapshot=snapshot,
        events=events,
    )


def _validate_event_revisions(
    baseline: BuildJobSnapshot | None,
    events: tuple[BuildJobEvent, ...],
) -> None:
    expected_revision = 1 if baseline is None else baseline.revision + 1
    for event in events:
        if event.revision != expected_revision:
            raise ValueError("build job envelope events must be contiguous")
        expected_revision += 1


def _reject_unknown_keys(
    payload: Mapping[str, Any], valid_keys: frozenset[str], label: str
) -> None:
    unknown = set(payload) - valid_keys
    if unknown:
        raise ValueError(f"unknown {label} keys: {', '.join(sorted(unknown))}")


def _datetime_to_json(value: datetime | None) -> str:
    return value.isoformat() if value is not None else ""


def _datetime_from_json(value: object) -> datetime:
    text = str(value or "")
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    return datetime.fromisoformat(text)


def _optional_datetime_from_json(value: object) -> datetime | None:
    return _datetime_from_json(value) if value else None


def _worker_to_dict(worker: WorkerIdentity | None) -> dict[str, str] | None:
    if worker is None:
        return None
    return {"worker_id": worker.worker_id, "runner_backend": worker.runner_backend}


def _optional_worker_from_dict(value: object) -> WorkerIdentity | None:
    if value in (None, ""):
        return None
    if not isinstance(value, Mapping):
        raise ValueError("build job snapshot worker must be an object or null")
    _reject_unknown_keys(value, frozenset({"worker_id", "runner_backend"}), "worker")
    return WorkerIdentity(
        worker_id=str(value["worker_id"]),
        runner_backend=str(value["runner_backend"]),
    )


def _raise_invalid_event() -> BuildJobEvent:
    raise ValueError("build job envelope events must be objects")


__all__ = [
    "BUILD_JOB_ENVELOPE_SCHEMA_VERSION",
    "BuildJobEnvelope",
    "envelope_from_dict",
    "envelope_to_dict",
    "snapshot_from_dict",
    "snapshot_to_dict",
]
