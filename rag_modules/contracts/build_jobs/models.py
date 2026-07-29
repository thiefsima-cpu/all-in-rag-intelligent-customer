"""Typed build-job domain models.

These models are deliberately independent from FastAPI/Pydantic so the build-job
application can later be backed by a transactional store or an external worker.
"""

from __future__ import annotations

import copy
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Self

from ...kernel.json_types import JsonObject, coerce_json_object

if TYPE_CHECKING:
    from .events import BuildJobEvent

BUILD_JOB_LOG_LIMIT = 200
_BUILD_JOB_ID_PATTERN = re.compile(r"^[0-9a-f]{32}\Z")
_PUBLIC_BUILD_JOB_REPOSITORY_BACKENDS = frozenset({"file", "postgresql", "unknown"})
_PUBLIC_BUILD_JOB_REPOSITORY_SCHEMA_VERSION_PATTERN = re.compile(r"(?:\d+|build-jobs-v\d+)\Z")

_SAFE_BUILD_LOGS = frozenset(
    {
        "Build progress updated.",
        "Build failed.",
        "Build interrupted by service restart.",
        "Build cancellation requested.",
        "Build cancelled.",
    }
)
_SAFE_BUILD_PROGRESS_MESSAGES = {
    "build_progress": "Build progress updated.",
    "initialize_graph_data": "Initializing graph data module.",
    "initialize_vector_index": "Initializing Milvus vector index module.",
    "build_runtime_ready": "Build runtime assembled.",
    "check_knowledge_base_state": "Checking knowledge base state.",
    "check_artifact_signatures": "Checking artifact signatures.",
    "load_graph_data": "Loading graph data.",
    "load_or_build_documents": "Loading or building documents and chunks.",
    "load_existing_knowledge_base": "Loading existing knowledge base.",
    "rebuild_stale_vector_collection": "Existing vector collection is stale. Rebuilding.",
    "start_new_knowledge_base": "Building a new knowledge base.",
    "load_graph_data_neo4j": "Loading graph data from Neo4j.",
    "build_documents": "Building documents and chunks.",
    "sync_semantic_schema": "Syncing semantic graph schema.",
    "semantic_schema_sync_degraded": "Semantic graph schema sync failed. Continuing startup.",
    "build_inactive_collection": "Building inactive Milvus collection.",
    "build_vector_index": "Building Milvus vector index.",
    "knowledge_base_build_completed": "Knowledge base build completed.",
}
_SAFE_BUILD_PROGRESS_LOG_PATTERN = re.compile(
    r"^stage=(?P<stage>[a-z0-9_]+) elapsed=(?P<elapsed>\d+\.\d{3})s "
    r'message="(?P<message>[^"]*)"\Z'
)


class BuildJobId(str):
    """Validated build-job identifier."""

    def __new__(cls, value: str) -> Self:
        normalized = str(value or "").strip().lower()
        if _BUILD_JOB_ID_PATTERN.fullmatch(normalized) is None:
            raise ValueError("build job id must be a 32-character lowercase hex string")
        return str.__new__(cls, normalized)


class BuildJobType(StrEnum):
    BUILD = "build"
    REBUILD = "rebuild"


class BuildJobStatus(StrEnum):
    QUEUED = "queued"
    CLAIMED = "claimed"
    RUNNING = "running"
    CANCEL_REQUESTED = "cancel_requested"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    INTERRUPTED = "interrupted"


class BuildJobSubmissionDisposition(StrEnum):
    CREATED = "created"
    REPLAYED = "replayed"


_PUBLIC_STATUS = {
    BuildJobStatus.CLAIMED: BuildJobStatus.QUEUED,
    BuildJobStatus.INTERRUPTED: BuildJobStatus.FAILED,
}


def public_status(status: BuildJobStatus) -> BuildJobStatus:
    return _PUBLIC_STATUS.get(status, status)


@dataclass(frozen=True, slots=True)
class WorkerIdentity:
    worker_id: str
    runner_backend: str


@dataclass(frozen=True, slots=True)
class SubmitBuildJob:
    job_id: BuildJobId
    request_id: str
    job_type: BuildJobType
    idempotency_key: str = ""
    retry_of_job_id: BuildJobId | None = None


@dataclass(frozen=True, slots=True)
class BuildJobSnapshot:
    job_id: BuildJobId
    request_id: str
    job_type: BuildJobType
    status: BuildJobStatus
    revision: int
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    message: str = ""
    error: Mapping[str, str] | None = None
    logs: tuple[str, ...] = field(default_factory=tuple)
    result: JsonObject | None = None
    retry_of_job_id: BuildJobId | None = None
    idempotency_key_hash: str = ""
    worker: WorkerIdentity | None = None
    lease_token: str = ""
    lease_expires_at: datetime | None = None

    def to_public_dict(self) -> JsonObject:
        """Return the stable, privacy-safe public payload."""

        return coerce_json_object(
            {
                "job_id": str(self.job_id),
                "request_id": self.request_id,
                "job_type": self.job_type.value,
                "status": public_status(self.status).value,
                "created_at": _iso_or_empty(self.created_at),
                "started_at": _iso_or_empty(self.started_at),
                "finished_at": _iso_or_empty(self.finished_at),
                "message": self.message,
                "error": build_failed_error(self.request_id) if self.error is not None else None,
                "logs": [_safe_build_log(item) for item in self.logs[-BUILD_JOB_LOG_LIMIT:]],
                "result": copy.deepcopy(self.result) if self.result is not None else None,
                "retry_of_job_id": str(self.retry_of_job_id or ""),
            }
        )


@dataclass(frozen=True, slots=True)
class BuildJobSubmission:
    disposition: BuildJobSubmissionDisposition
    snapshot: BuildJobSnapshot


@dataclass(frozen=True, slots=True)
class BuildJobListQuery:
    status: BuildJobStatus | None = None
    limit: int | None = None
    cursor: str = ""


@dataclass(frozen=True, slots=True)
class BuildJobPage:
    jobs: tuple[BuildJobSnapshot, ...]
    next_cursor: str = ""


@dataclass(frozen=True, slots=True)
class BuildJobEventListQuery:
    limit: int | None = None
    cursor: str = ""


@dataclass(frozen=True, slots=True)
class BuildJobEventPage:
    events: tuple[BuildJobEvent, ...]
    next_cursor: str = ""


@dataclass(frozen=True, slots=True)
class BuildJobLease:
    job_id: BuildJobId
    revision: int
    worker: WorkerIdentity
    lease_token: str
    lease_expires_at: datetime


@dataclass(frozen=True, slots=True)
class BuildJobRepositorySettings:
    retention_limit: int = 100
    list_default_limit: int = 50
    list_max_limit: int = 100
    lease_seconds: float = 30.0
    audit_retention_days: int = 90


@dataclass(frozen=True, slots=True)
class BuildJobRepositoryWarning:
    code: str
    component: str
    identifier: str
    detected_at: str

    def to_public_dict(self) -> dict[str, str]:
        return {
            "code": self.code,
            "component": self.component,
            "identifier": self.identifier,
            "detected_at": self.detected_at,
        }


@dataclass(frozen=True, slots=True)
class BuildJobRepositoryDiagnostics:
    backend: str = "unknown"
    ready: bool = True
    schema_version: str = ""
    warnings: tuple[BuildJobRepositoryWarning, ...] = field(default_factory=tuple)

    def to_public_dict(self) -> JsonObject:
        warnings = [warning.to_public_dict() for warning in self.warnings]
        return coerce_json_object(
            {
                "backend": _public_repository_backend(self.backend),
                "ready": self.ready,
                "schema_version": _public_repository_schema_version(self.schema_version),
                "warning_count": len(warnings),
                "warning_codes": sorted({warning["code"] for warning in warnings}),
                "warnings": warnings,
            }
        )


def build_failed_error(request_id: str) -> dict[str, str]:
    return {
        "code": "BUILD_FAILED",
        "message": "The knowledge-base build failed.",
        "request_id": str(request_id or ""),
    }


def _iso_or_empty(value: datetime | None) -> str:
    return value.isoformat() if value is not None else ""


def _public_repository_backend(value: object) -> str:
    backend = str(value or "").strip().lower()
    return backend if backend in _PUBLIC_BUILD_JOB_REPOSITORY_BACKENDS else "unknown"


def _public_repository_schema_version(value: object) -> str:
    schema_version = str(value or "").strip()
    if _PUBLIC_BUILD_JOB_REPOSITORY_SCHEMA_VERSION_PATTERN.fullmatch(schema_version) is None:
        return ""
    return schema_version


def _safe_build_log(value: object) -> str:
    text = str(value or "")
    safe_progress_log = _safe_progress_log(text)
    if safe_progress_log:
        return safe_progress_log
    if text in _SAFE_BUILD_LOGS:
        return text
    lowered = text.lower()
    if "error" in lowered or "fail" in lowered:
        return "Build failed."
    return "Build progress updated."


def _safe_progress_log(value: object) -> str:
    text = str(value or "")
    match = _SAFE_BUILD_PROGRESS_LOG_PATTERN.fullmatch(text)
    if match is None:
        return ""
    stage = match.group("stage")
    message = _SAFE_BUILD_PROGRESS_MESSAGES.get(stage)
    if message is None or message != match.group("message"):
        return ""
    elapsed = float(match.group("elapsed"))
    return f'stage={stage} elapsed={elapsed:.3f}s message="{message}"'


__all__ = [
    "BUILD_JOB_LOG_LIMIT",
    "BuildJobId",
    "BuildJobEventListQuery",
    "BuildJobEventPage",
    "BuildJobLease",
    "BuildJobListQuery",
    "BuildJobPage",
    "BuildJobRepositoryDiagnostics",
    "BuildJobRepositorySettings",
    "BuildJobRepositoryWarning",
    "BuildJobSnapshot",
    "BuildJobStatus",
    "BuildJobSubmission",
    "BuildJobSubmissionDisposition",
    "BuildJobType",
    "SubmitBuildJob",
    "WorkerIdentity",
    "build_failed_error",
    "public_status",
]
