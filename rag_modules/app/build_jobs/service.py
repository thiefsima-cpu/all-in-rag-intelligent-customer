"""Build-job application use cases orchestrated through stable ports."""

from __future__ import annotations

import copy
import re
import time
import uuid
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import datetime, timezone

from rag_modules.contracts.build_jobs import (
    BuildJobConcurrentUpdateError,
    BuildJobConflictError,
    BuildJobDispatchError,
    BuildJobEvent,
    BuildJobEventType,
    BuildJobId,
    BuildJobListQuery,
    BuildJobNotFoundError,
    BuildJobPage,
    BuildJobRepositoryDiagnostics,
    BuildJobRepositoryPort,
    BuildJobRunnerPort,
    BuildJobSnapshot,
    BuildJobStatus,
    BuildJobSubmissionDisposition,
    BuildJobType,
    JobCancellationRequested,
    JobProgressRecorded,
    JobSucceeded,
    SubmitBuildJob,
)
from rag_modules.kernel.json_types import JsonObject, coerce_json_object

from ..application_protocol import GraphRAGApplication

_Clock = Callable[[], datetime]
_IdFactory = Callable[[], str]
_DispatchWarningRecorder = Callable[[BuildJobId], None]
_RETRYABLE_STATUSES = frozenset(
    {
        BuildJobStatus.FAILED,
        BuildJobStatus.CANCELLED,
        BuildJobStatus.INTERRUPTED,
    }
)
_TERMINAL_STATUSES = frozenset(
    {
        BuildJobStatus.SUCCEEDED,
        BuildJobStatus.FAILED,
        BuildJobStatus.CANCELLED,
        BuildJobStatus.INTERRUPTED,
    }
)


class BuildJobApplicationService:
    def __init__(
        self,
        *,
        repository: BuildJobRepositoryPort,
        runner: BuildJobRunnerPort,
        new_id: _IdFactory | None = None,
        now: _Clock | None = None,
        record_dispatch_warning: _DispatchWarningRecorder | None = None,
    ) -> None:
        self._repository = repository
        self._runner = runner
        self._new_id = new_id or (lambda: uuid.uuid4().hex)
        self._now = now or (lambda: datetime.now(timezone.utc))
        self._record_dispatch_warning = record_dispatch_warning or (lambda _job_id: None)

    def submit(self, *, rebuild: bool, request_id: str, idempotency_key: str) -> BuildJobSnapshot:
        command = SubmitBuildJob(
            job_id=BuildJobId(self._new_id()),
            request_id=request_id,
            job_type=BuildJobType.REBUILD if rebuild else BuildJobType.BUILD,
            idempotency_key=idempotency_key,
        )
        return self._submit_command(command)

    def retry(
        self,
        job_id: BuildJobId,
        *,
        request_id: str,
        idempotency_key: str,
    ) -> BuildJobSnapshot:
        snapshot = self.get(job_id)
        if snapshot.status not in _RETRYABLE_STATUSES:
            raise BuildJobConflictError(
                "Only failed, cancelled, or interrupted build jobs can be retried.",
                snapshot,
            )
        command = SubmitBuildJob(
            job_id=BuildJobId(self._new_id()),
            request_id=request_id,
            job_type=snapshot.job_type,
            idempotency_key=idempotency_key,
            retry_of_job_id=snapshot.job_id,
        )
        return self._submit_command(command)

    def get(self, job_id: BuildJobId) -> BuildJobSnapshot:
        snapshot = self._repository.get(job_id)
        if snapshot is None:
            raise BuildJobNotFoundError(job_id)
        return snapshot

    def list_page(
        self,
        *,
        limit: int | None = None,
        cursor: str = "",
        status: BuildJobStatus | None = None,
    ) -> BuildJobPage:
        return self._repository.list_page(
            BuildJobListQuery(
                status=status,
                limit=limit or self._repository.list_default_limit,
                cursor=cursor,
            )
        )

    def cancel(self, job_id: BuildJobId) -> BuildJobSnapshot:
        last_conflict: BuildJobConcurrentUpdateError | None = None
        for _attempt in range(3):
            snapshot = self.get(job_id)
            if snapshot.status is BuildJobStatus.CANCELLED:
                return snapshot
            if snapshot.status is BuildJobStatus.CANCEL_REQUESTED:
                return snapshot
            if snapshot.status in _TERMINAL_STATUSES:
                raise BuildJobConflictError("Terminal build jobs cannot be cancelled.", snapshot)
            event = BuildJobEvent(
                event_id=f"{snapshot.job_id}:{snapshot.revision + 1}",
                job_id=snapshot.job_id,
                revision=snapshot.revision + 1,
                event_type=BuildJobEventType.CANCELLATION_REQUESTED,
                schema_version=1,
                occurred_at=self._now(),
                request_id=snapshot.request_id,
                payload=JobCancellationRequested(),
            )
            try:
                updated = self._repository.apply(event, expected_revision=snapshot.revision)
            except BuildJobConcurrentUpdateError as exc:
                last_conflict = exc
                continue
            self._runner.notify_cancellation(snapshot.job_id)
            return updated
        assert last_conflict is not None
        raise last_conflict

    def startup(self) -> tuple[BuildJobSnapshot, ...]:
        recovered = self._repository.recover_expired_leases()
        self._runner.start()
        return recovered

    def shutdown(self) -> None:
        self._runner.shutdown()

    def diagnostics(self) -> BuildJobRepositoryDiagnostics:
        return self._repository.diagnostics()

    def _submit_command(self, command: SubmitBuildJob) -> BuildJobSnapshot:
        submission = self._repository.submit(command)
        if submission.disposition is BuildJobSubmissionDisposition.CREATED:
            try:
                self._runner.schedule(submission.snapshot.job_id)
            except BuildJobDispatchError:
                self._record_dispatch_warning(submission.snapshot.job_id)
        return submission.snapshot


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
    system: GraphRAGApplication
    lifecycle_operation: Callable[[], AbstractContextManager[None]]
    operation_response: Callable[[str], JsonObject]
    failure_snapshot: Callable[[], tuple[JsonObject, JsonObject]]


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

    def cancelled_result(self) -> JsonObject:
        return {"message": "Knowledge base build cancelled."}

    def failed_result(self) -> JsonObject:
        diagnostics, stats = self.hooks.failure_snapshot()
        return {
            "message": "Knowledge base build failed.",
            "diagnostics": copy.deepcopy(diagnostics),
            "stats": copy.deepcopy(stats),
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


def _job_result_from_operation(operation_result: JsonObject) -> JsonObject:
    return coerce_json_object(
        {
            "message": str(operation_result.get("message", "")),
            "diagnostics": operation_result.get("diagnostics"),
            "stats": operation_result.get("stats"),
        }
    )


__all__ = [
    "BuildJobApplicationService",
    "BuildJobExecutor",
    "BuildJobRuntimeHooks",
    "format_build_progress_log",
]
