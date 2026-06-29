"""Build-job persistence models."""

from __future__ import annotations

import copy
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from ..error_models import ERROR_MESSAGES, ErrorCode
from ..request_context import normalize_or_generate_request_id

BUILD_JOB_STORE_SCHEMA_VERSION = "graph-rag-build-jobs-v2"
BUILD_JOB_LOG_LIMIT = 200

_SAFE_BUILD_LOGS = frozenset(
    {
        "Build progress updated.",
        "Build failed.",
        "Build interrupted by service restart.",
    }
)


def _safe_build_log(value: object) -> str:
    text = str(value or "")
    if text in _SAFE_BUILD_LOGS:
        return text
    if "error" in text.lower() or "fail" in text.lower():
        return "Build failed."
    return "Build progress updated."


def build_failure(request_id: str) -> dict[str, str]:
    return {
        "code": ErrorCode.BUILD_FAILED.value,
        "message": ERROR_MESSAGES[ErrorCode.BUILD_FAILED],
        "request_id": normalize_or_generate_request_id(request_id),
    }


@dataclass(slots=True)
class BuildJobRecord:
    job_id: str
    request_id: str
    job_type: str
    status: str
    created_at: str
    started_at: str = ""
    finished_at: str = ""
    message: str = ""
    error: dict | None = None
    logs: list[str] = field(default_factory=list)
    result: dict | None = None
    idempotency_key_hash: str = ""

    def to_dict(self, *, include_internal: bool = False) -> dict:
        payload = {
            "job_id": self.job_id,
            "request_id": self.request_id,
            "job_type": self.job_type,
            "status": self.status,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "message": self.message,
            "error": copy.deepcopy(self.error),
            "logs": [_safe_build_log(item) for item in self.logs],
            "result": copy.deepcopy(self.result),
        }
        if include_internal and self.idempotency_key_hash:
            payload["idempotency_key_hash"] = self.idempotency_key_hash
        return payload

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "BuildJobRecord":
        raw_error = payload.get("error")
        stored_request_id = str(payload.get("request_id") or "")
        if isinstance(raw_error, Mapping):
            stored_request_id = str(raw_error.get("request_id") or stored_request_id)
        request_id = normalize_or_generate_request_id(stored_request_id)
        return cls(
            job_id=str(payload.get("job_id") or ""),
            request_id=request_id,
            job_type=str(payload.get("job_type") or "build"),
            status=str(payload.get("status") or "failed"),
            created_at=str(payload.get("created_at") or ""),
            started_at=str(payload.get("started_at") or ""),
            finished_at=str(payload.get("finished_at") or ""),
            message=str(payload.get("message") or ""),
            error=build_failure(request_id) if raw_error else None,
            logs=[_safe_build_log(item) for item in list(payload.get("logs") or [])],
            result=(
                copy.deepcopy(dict(payload["result"]))
                if isinstance(payload.get("result"), Mapping)
                else None
            ),
            idempotency_key_hash=str(payload.get("idempotency_key_hash") or ""),
        )


@dataclass(frozen=True, slots=True)
class BuildJobRepositorySettings:
    retention_limit: int = 100
    list_default_limit: int = 50
    list_max_limit: int = 100


@dataclass(frozen=True, slots=True)
class BuildJobListPage:
    jobs: list[dict]
    next_cursor: str = ""


@dataclass(frozen=True, slots=True)
class BuildJobCorruptionWarning:
    code: str
    component: str
    identifier: str
    detected_at: str

    def to_dict(self) -> dict:
        return {
            "code": self.code,
            "component": self.component,
            "identifier": self.identifier,
            "detected_at": self.detected_at,
        }


__all__ = [
    "BUILD_JOB_LOG_LIMIT",
    "BUILD_JOB_STORE_SCHEMA_VERSION",
    "BuildJobCorruptionWarning",
    "BuildJobListPage",
    "BuildJobRecord",
    "BuildJobRepositorySettings",
]
