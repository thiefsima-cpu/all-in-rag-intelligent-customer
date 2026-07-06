"""Typed build-job executor independent from HTTP and persistence adapters."""

from __future__ import annotations

import copy
import re
import time
from collections.abc import Callable, Mapping
from contextlib import AbstractContextManager
from dataclasses import dataclass
from typing import Any

from .events import JobProgressRecorded, JobSucceeded
from .models import BuildJobSnapshot

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

_ProgressCallback = Callable[[JobProgressRecorded], None]
_CancellationCheck = Callable[[], None]


@dataclass(frozen=True, slots=True)
class BuildJobRuntimeHooks:
    system: Any
    lifecycle_operation: Callable[[], AbstractContextManager[None]]
    operation_response: Callable[[str], Mapping[str, Any]]
    failure_snapshot: Callable[[], tuple[Mapping[str, Any], Mapping[str, Any]]]


@dataclass(frozen=True, slots=True)
class BuildJobExecutor:
    hooks: BuildJobRuntimeHooks
    perf_counter: Callable[[], float] = time.perf_counter

    def execute(
        self,
        snapshot: BuildJobSnapshot,
        *,
        progress: _ProgressCallback,
        cancellation_check: _CancellationCheck,
    ) -> JobSucceeded:
        rebuild = snapshot.job_type.value == "rebuild"
        started_at = self.perf_counter()

        def record_progress(message: object) -> None:
            cancellation_check()
            progress(
                JobProgressRecorded(
                    message=format_build_progress_log(
                        message,
                        elapsed_seconds=self.perf_counter() - started_at,
                    )
                )
            )
            cancellation_check()

        cancellation_check()
        with self.hooks.lifecycle_operation():
            cancellation_check()
            if not self.hooks.system.is_build_initialized():
                self.hooks.system.initialize_build_runtime(progress=record_progress)
            cancellation_check()
            if rebuild:
                self.hooks.system.rebuild_knowledge_base(
                    progress=record_progress,
                    request_id=snapshot.request_id,
                    build_job_id=str(snapshot.job_id),
                )
                message = "Knowledge base rebuild completed."
            else:
                self.hooks.system.build_knowledge_base(
                    progress=record_progress,
                    request_id=snapshot.request_id,
                    build_job_id=str(snapshot.job_id),
                )
                message = "Knowledge base build completed."
            cancellation_check()
            operation_result = self.hooks.operation_response(message)
        return JobSucceeded(message=message, result=_job_result_from_operation(operation_result))

    def cancelled_result(self) -> dict[str, Any]:
        return {"message": "Knowledge base build cancelled."}

    def failed_result(self) -> dict[str, Any]:
        diagnostics, stats = self.hooks.failure_snapshot()
        return {
            "message": "Knowledge base build failed.",
            "diagnostics": copy.deepcopy(dict(diagnostics)),
            "stats": copy.deepcopy(dict(stats)),
        }


def format_build_progress_log(value: object, *, elapsed_seconds: float) -> str:
    stage = _safe_build_progress_stage(value)
    elapsed = max(0.0, float(elapsed_seconds))
    message = _SAFE_BUILD_PROGRESS_MESSAGES[stage]
    return f'stage={stage} elapsed={elapsed:.3f}s message="{message}"'


def _safe_build_progress_stage(value: object) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip().lower()
    text = re.sub(r"^\[(ok|warn)\]\s*", "", text)
    for stage, markers in _BUILD_PROGRESS_STAGE_RULES:
        if all(marker in text for marker in markers):
            return stage
    return "build_progress"


def _job_result_from_operation(operation_result: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "message": str(operation_result.get("message", "")),
        "diagnostics": copy.deepcopy(operation_result.get("diagnostics")),
        "stats": copy.deepcopy(operation_result.get("stats")),
    }


__all__ = [
    "BuildJobExecutor",
    "BuildJobRuntimeHooks",
    "format_build_progress_log",
]
