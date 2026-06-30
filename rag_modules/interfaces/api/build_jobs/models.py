"""Build-job persistence models."""

from __future__ import annotations

import copy
import re
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
_BUILD_PROGRESS_STAGE_RULES = (
    ("build_vector_index", ("building milvus vector index",)),
    ("build_documents", ("building documents and chunks",)),
    ("load_graph_data_neo4j", ("loading graph data from neo4j",)),
    ("load_graph_data", ("loading graph data",)),
    ("load_or_build_documents", ("loading or building documents and chunks",)),
    ("sync_semantic_schema", ("syncing semantic graph schema",)),
    ("semantic_schema_sync_degraded", ("semantic graph schema sync failed",)),
    ("build_inactive_collection", ("building the inactive milvus collection",)),
    ("knowledge_base_build_completed", ("knowledge base build completed",)),
    ("load_existing_knowledge_base", ("knowledge base loaded successfully",)),
    ("rebuild_stale_vector_collection", ("existing vector collection is stale",)),
    ("check_artifact_signatures", ("checking artifact signatures",)),
    ("start_new_knowledge_base", ("building a new knowledge base",)),
    ("check_knowledge_base_state", ("checking knowledge base state",)),
    ("initialize_graph_data", ("initializing graph data module",)),
    ("initialize_vector_index", ("initializing milvus vector index module",)),
    ("build_runtime_ready", ("build runtime assembled",)),
)
_SAFE_BUILD_PROGRESS_LOG_PATTERN = re.compile(
    r"^stage=(?P<stage>[a-z0-9_]+) elapsed=(?P<elapsed>\d+\.\d{3})s "
    r'message="(?P<message>[^"]*)"\Z'
)


def _safe_build_progress_stage(value: object) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip().lower()
    text = re.sub(r"^\[(ok|warn)\]\s*", "", text)
    for stage, markers in _BUILD_PROGRESS_STAGE_RULES:
        if all(marker in text for marker in markers):
            return stage
    return "build_progress"


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


def format_build_progress_log(value: object, *, elapsed_seconds: float) -> str:
    stage = _safe_build_progress_stage(value)
    elapsed = max(0.0, float(elapsed_seconds))
    message = _SAFE_BUILD_PROGRESS_MESSAGES[stage]
    return f'stage={stage} elapsed={elapsed:.3f}s message="{message}"'


def _safe_build_log(value: object) -> str:
    text = str(value or "")
    safe_progress_log = _safe_progress_log(text)
    if safe_progress_log:
        return safe_progress_log
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
