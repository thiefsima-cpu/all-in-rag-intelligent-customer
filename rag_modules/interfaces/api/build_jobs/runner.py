"""Build-job execution boundary and in-process backend."""

from __future__ import annotations

import copy
import threading
import time
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from contextlib import AbstractContextManager
from dataclasses import dataclass, field
from typing import Protocol
from uuid import uuid4

from ....app.application_protocol import GraphRAGApplication
from ....contracts import RequestCancelled, RequestControl
from ....runtime.json_types import JsonObject, coerce_json_object
from .locks import _InterprocessFileLock
from .models import BuildJobListPage, format_build_progress_log
from .registry import PersistentBuildJobRegistry
from .repository import BuildJobIdempotencyConflictError

_ACTIVE_STATUSES = frozenset({"queued", "running", "cancel_requested"})
_RETRYABLE_STATUSES = frozenset({"failed", "cancelled"})


class BuildJobRunnerConflictError(RuntimeError):
    """Raised when runner state rejects a requested build-job operation."""

    def __init__(self, message: str, *, job: dict) -> None:
        super().__init__(message)
        self.job = dict(job)


class BuildJobRunnerNotFoundError(KeyError):
    """Raised when a runner operation references an unknown job."""

    def __init__(self, job_id: str) -> None:
        super().__init__(job_id)
        self.job_id = str(job_id)


@dataclass(frozen=True, slots=True)
class BuildJobRuntimeHooks:
    """Runtime operations required by a build task without depending on the API service."""

    system: GraphRAGApplication
    lifecycle_operation: Callable[[], AbstractContextManager[None]]
    operation_response: Callable[[str], JsonObject]
    failure_snapshot: Callable[[], tuple[JsonObject, JsonObject]]


@dataclass(frozen=True, slots=True)
class BuildJobRunRequest:
    """Immutable request dispatched to one execution backend."""

    job_id: str
    job_type: str
    request_id: str
    build_lock: _InterprocessFileLock
    control: RequestControl

    @property
    def rebuild(self) -> bool:
        return self.job_type == "rebuild"


class BuildJobRunner(Protocol):
    """Submission and lifecycle contract for build-job execution backends."""

    @property
    def list_default_limit(self) -> int: ...

    def submit(
        self,
        *,
        rebuild: bool,
        request_id: str,
        idempotency_key: str,
    ) -> JsonObject: ...

    def cancel(self, job_id: str) -> JsonObject: ...

    def retry(self, job_id: str, *, request_id: str) -> JsonObject: ...

    def list_page(self, *, limit: int, cursor: str = "") -> BuildJobListPage: ...

    def get(self, job_id: str) -> JsonObject: ...

    def corruption_summary(self) -> JsonObject: ...

    def shutdown(self) -> None: ...


class BuildJobTask:
    """Execute one build or rebuild and persist every lifecycle transition."""

    def __init__(
        self,
        *,
        registry: PersistentBuildJobRegistry,
        hooks: BuildJobRuntimeHooks,
    ) -> None:
        self.registry = registry
        self.hooks = hooks

    def run(self, request: BuildJobRunRequest) -> None:
        try:
            request.control.raise_if_cancelled()
            self.registry.mark_running(
                request.job_id,
                message=(
                    "Knowledge base rebuild started."
                    if request.rebuild
                    else "Knowledge base build started."
                ),
            )
            progress_started_at = time.perf_counter()

            def progress(message: str) -> None:
                request.control.raise_if_cancelled()
                self.registry.append_log(
                    request.job_id,
                    format_build_progress_log(
                        message,
                        elapsed_seconds=time.perf_counter() - progress_started_at,
                    ),
                )
                request.control.raise_if_cancelled()

            with self.hooks.lifecycle_operation():
                request.control.raise_if_cancelled()
                if not self.hooks.system.is_build_initialized():
                    self.hooks.system.initialize_build_runtime(progress=progress)
                request.control.raise_if_cancelled()
                if request.rebuild:
                    self.hooks.system.rebuild_knowledge_base(
                        progress=progress,
                        request_id=request.request_id,
                        build_job_id=request.job_id,
                    )
                    message = "Knowledge base rebuild completed."
                else:
                    self.hooks.system.build_knowledge_base(
                        progress=progress,
                        request_id=request.request_id,
                        build_job_id=request.job_id,
                    )
                    message = "Knowledge base build completed."
                request.control.raise_if_cancelled()
                operation_result = self.hooks.operation_response(message)
            self.registry.mark_succeeded(
                request.job_id,
                result=self._job_result_from_operation(operation_result),
            )
        except RequestCancelled:
            self.registry.mark_cancelled(
                request.job_id,
                result={"message": "Knowledge base build cancelled."},
            )
        except Exception:
            self.registry.append_log(request.job_id, "Build failed.")
            diagnostics, stats = self.hooks.failure_snapshot()
            self.registry.mark_failed(
                request.job_id,
                result={
                    "message": "Knowledge base build failed.",
                    "diagnostics": diagnostics,
                    "stats": stats,
                },
            )
        finally:
            request.build_lock.release()

    @staticmethod
    def _job_result_from_operation(operation_result: JsonObject) -> JsonObject:
        return coerce_json_object(
            {
                "message": str(operation_result.get("message", "")),
                "diagnostics": copy.deepcopy(operation_result.get("diagnostics")),
                "stats": copy.deepcopy(operation_result.get("stats")),
            }
        )


@dataclass(slots=True)
class _InProcessJobHandle:
    control: RequestControl
    build_lock: _InterprocessFileLock
    future: Future[None] | None = None
    _release_lock: threading.Lock = field(default_factory=threading.Lock)
    _build_lock_released: bool = False

    def release_build_lock(self) -> None:
        with self._release_lock:
            if self._build_lock_released:
                return
            self.build_lock.release()
            self._build_lock_released = True


class InProcessBuildJobRunner:
    """Run durable build jobs in a local thread pool."""

    backend = "in_process"

    def __init__(
        self,
        *,
        registry: PersistentBuildJobRegistry,
        hooks: BuildJobRuntimeHooks,
        max_workers: int,
    ) -> None:
        self.registry = registry
        self.hooks = hooks
        self.max_workers = max(1, int(max_workers or 1))
        self._task = BuildJobTask(registry=registry, hooks=hooks)
        self._submission_lock = threading.Lock()
        self._executor: ThreadPoolExecutor | None = None
        self._executor_lock = threading.Lock()
        self._handles: dict[str, _InProcessJobHandle] = {}
        self._handles_lock = threading.Lock()

    @property
    def list_default_limit(self) -> int:
        return int(self.registry.repository.settings.list_default_limit)

    def submit(
        self,
        *,
        rebuild: bool,
        request_id: str,
        idempotency_key: str,
    ) -> JsonObject:
        return self._submit_new_job(
            job_type="rebuild" if rebuild else "build",
            request_id=request_id,
            idempotency_key=idempotency_key,
        )

    def cancel(self, job_id: str) -> JsonObject:
        job = self.get(job_id)
        status = str(job.get("status") or "")
        if status == "cancelled":
            return job
        if status not in _ACTIVE_STATUSES:
            raise BuildJobRunnerConflictError(
                "Build job cannot be cancelled from its current state.",
                job=job,
            )
        with self._handles_lock:
            handle = self._handles.get(str(job_id))
        if handle is None:
            raise BuildJobRunnerConflictError(
                "Build job is owned by another runner instance.",
                job=job,
            )

        handle.control.cancel("build_job_cancelled")
        future = handle.future
        if future is not None and future.cancel():
            self.registry.mark_cancelled(
                str(job_id),
                result={"message": "Knowledge base build cancelled."},
            )
            handle.release_build_lock()
            self._forget_handle(str(job_id))
            return self.get(job_id)

        latest = self.get(job_id)
        if str(latest.get("status") or "") in {"queued", "running"}:
            self.registry.mark_cancel_requested(
                str(job_id),
                message="Knowledge base build cancellation requested.",
            )
        return self.get(job_id)

    def retry(self, job_id: str, *, request_id: str) -> JsonObject:
        original = self.get(job_id)
        if str(original.get("status") or "") not in _RETRYABLE_STATUSES:
            raise BuildJobRunnerConflictError(
                "Build job cannot be retried from its current state.",
                job=original,
            )
        return self._submit_new_job(
            job_type=str(original.get("job_type") or "build"),
            request_id=request_id,
            idempotency_key="",
            retry_of_job_id=str(original.get("job_id") or ""),
        )

    def list_page(self, *, limit: int, cursor: str = "") -> BuildJobListPage:
        return self.registry.list_page(limit=limit, cursor=cursor)

    def get(self, job_id: str) -> JsonObject:
        job = self.registry.get(str(job_id))
        if job is None:
            raise BuildJobRunnerNotFoundError(str(job_id))
        return coerce_json_object(job)

    def corruption_summary(self) -> JsonObject:
        return coerce_json_object(self.registry.corruption_summary())

    def shutdown(self) -> None:
        with self._handles_lock:
            job_ids = list(self._handles)
        for job_id in job_ids:
            try:
                self.cancel(job_id)
            except BuildJobRunnerConflictError:
                pass
        with self._executor_lock:
            executor = self._executor
            self._executor = None
        if executor is not None:
            executor.shutdown(wait=False, cancel_futures=True)

    def _submit_new_job(
        self,
        *,
        job_type: str,
        request_id: str,
        idempotency_key: str,
        retry_of_job_id: str = "",
    ) -> JsonObject:
        with self._submission_lock:
            resolved_idempotency_key = self.registry.repository.validate_idempotency_key(
                idempotency_key
            )
            job_id = uuid4().hex
            try:
                created, job, build_lock = self.registry.create_or_active(
                    job_id=job_id,
                    request_id=request_id,
                    job_type=job_type,
                    message=(
                        f"Knowledge base {job_type} retry job queued."
                        if retry_of_job_id
                        else f"Knowledge base {job_type} job queued."
                    ),
                    idempotency_key=resolved_idempotency_key,
                    retry_of_job_id=retry_of_job_id,
                )
            except BuildJobIdempotencyConflictError as exc:
                raise BuildJobRunnerConflictError(
                    "Idempotency key conflicts with an existing build job.",
                    job=exc.job,
                ) from None
            if job is not None and bool(job.pop("_idempotency_replayed", False)):
                return coerce_json_object(job)
            if not created or job is None or build_lock is None:
                active_job = job or self.registry.active()
                if active_job is None:
                    active_job = {
                        "job_id": job_id,
                        "job_type": job_type,
                        "status": "running",
                        "created_at": "",
                        "message": "A build job is already in progress.",
                    }
                raise BuildJobRunnerConflictError(
                    "A build job is already in progress.",
                    job=active_job,
                )

            control = RequestControl(deadline=float("inf"), scope=f"build_job.{job_id}")
            handle = _InProcessJobHandle(control=control, build_lock=build_lock)
            request = BuildJobRunRequest(
                job_id=job_id,
                job_type=job_type,
                request_id=request_id,
                build_lock=build_lock,
                control=control,
            )
            with self._handles_lock:
                self._handles[job_id] = handle
            try:
                future = self._resolve_executor().submit(self._task.run, request)
                handle.future = future
                future.add_done_callback(lambda _: self._forget_handle(job_id))
            except Exception:
                handle.release_build_lock()
                self._forget_handle(job_id)
                raise
            return coerce_json_object(job)

    def _resolve_executor(self) -> ThreadPoolExecutor:
        executor = self._executor
        if executor is not None:
            return executor
        with self._executor_lock:
            executor = self._executor
            if executor is None:
                executor = ThreadPoolExecutor(
                    max_workers=self.max_workers,
                    thread_name_prefix="graph-rag-build",
                )
                self._executor = executor
        return executor

    def _forget_handle(self, job_id: str) -> None:
        with self._handles_lock:
            self._handles.pop(str(job_id), None)


def create_build_job_runner(
    *,
    backend: str,
    registry: PersistentBuildJobRegistry,
    hooks: BuildJobRuntimeHooks,
    max_workers: int,
) -> BuildJobRunner:
    """Create the configured build-job execution backend."""

    if str(backend or "") == InProcessBuildJobRunner.backend:
        return InProcessBuildJobRunner(
            registry=registry,
            hooks=hooks,
            max_workers=max_workers,
        )
    raise ValueError(f"Unsupported build job runner backend: {backend!r}")


__all__ = [
    "BuildJobRunRequest",
    "BuildJobRunner",
    "BuildJobRunnerConflictError",
    "BuildJobRunnerNotFoundError",
    "BuildJobRuntimeHooks",
    "BuildJobTask",
    "InProcessBuildJobRunner",
    "create_build_job_runner",
]
