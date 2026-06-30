"""Build API service implementation."""

from __future__ import annotations

import copy
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Any, Optional
from uuid import uuid4

from ....app.application_protocol import GraphRAGApplication
from ....configuration.models import GraphRAGConfig
from ....runtime.artifacts import ArtifactManifestStore
from ....runtime.artifacts.registry import ArtifactRegistry, ArtifactRegistrySnapshot
from ..build_job_store import (
    BuildJobIdempotencyConflictError,
    BuildJobListPage,
    BuildJobRepositorySettings,
    FileBuildJobStore,
    PersistentBuildJobRegistry,
    default_build_job_store_path,
)
from ..build_jobs.locks import _InterprocessFileLock
from ..build_jobs.models import format_build_progress_log
from ..request_context import normalize_or_generate_request_id
from .base import _BaseGraphRAGApiService
from .errors import BuildJobConflictError, BuildJobNotFoundError, InvalidApiRequestError

_BUILD_JOB_EXECUTOR_MAX_WORKERS = 1


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class GraphRAGBuildApiService(_BaseGraphRAGApiService):
    """HTTP-facing build surface for offline artifact preparation."""

    _MODE = "build"

    def __init__(
        self,
        *,
        system: GraphRAGApplication | None = None,
        config: Optional[GraphRAGConfig] = None,
        job_store: FileBuildJobStore | None = None,
        artifact_registry: ArtifactRegistry | None = None,
    ) -> None:
        super().__init__(system=system, config=config)
        self._job_submission_lock = threading.Lock()
        self._build_executor: ThreadPoolExecutor | None = None
        self._build_executor_lock = threading.Lock()
        resolved_config = config or getattr(self.system, "config", None)
        resolved_job_store = job_store or FileBuildJobStore(
            default_build_job_store_path(resolved_config)
        )
        self._artifact_registry = artifact_registry or ArtifactRegistry(
            ArtifactManifestStore(resolved_config)
        )
        api_settings = getattr(resolved_config, "api", None)
        repository_settings = BuildJobRepositorySettings(
            retention_limit=int(getattr(api_settings, "build_job_retention_limit", 100)),
            list_default_limit=int(getattr(api_settings, "build_job_list_default_limit", 50)),
            list_max_limit=int(getattr(api_settings, "build_job_list_max_limit", 100)),
        )
        self._job_registry = PersistentBuildJobRegistry(
            resolved_job_store,
            now=_utc_now_iso,
            recover_interrupted=not resolved_job_store.build_lock_held(),
            settings=repository_settings,
        )

    def _ensure_build_runtime_initialized(self) -> None:
        self._ensure_runtime_initialized(
            is_initialized=self.system.is_build_initialized,
            initializer=self.system.initialize_build_runtime,
        )

    def startup(self, *, auto_initialize_build: bool = False) -> None:
        if not auto_initialize_build:
            return
        self._ensure_build_runtime_initialized()

    def health(self) -> dict[str, Any]:
        return self._health_payload(self.collect_startup_diagnostics(self._MODE))

    def readiness(self) -> dict[str, Any]:
        diagnostics = self.collect_startup_diagnostics(self._MODE)
        return self._readiness_payload(
            diagnostics,
            ready=bool(diagnostics["build_initialized"]),
        )

    def _collect_startup_diagnostics_unlocked(self, mode: str) -> dict[str, Any]:
        diagnostics = super()._collect_startup_diagnostics_unlocked(mode)
        diagnostics["build_job_store"] = self._job_registry.corruption_summary()
        return diagnostics

    def initialize_build_runtime(self) -> dict[str, Any]:
        with self._exclusive_runtime_operation():
            if not self.system.is_build_initialized():
                self.system.initialize_build_runtime()
            return self._operation_response(
                message="Build runtime initialized.",
                mode=self._MODE,
            )

    def shutdown(self) -> None:
        executor = self._build_executor
        self._build_executor = None
        if executor is not None:
            executor.shutdown(wait=False, cancel_futures=True)
        super().shutdown()

    def build_knowledge_base(
        self,
        *,
        rebuild: bool = False,
        request_id: str = "",
        idempotency_key: str = "",
    ) -> dict[str, Any]:
        return self.submit_build_job(
            rebuild=rebuild,
            request_id=request_id,
            idempotency_key=idempotency_key,
        )

    def submit_build_job(
        self,
        *,
        rebuild: bool = False,
        request_id: str = "",
        idempotency_key: str = "",
    ) -> dict[str, Any]:
        with self._job_submission_lock:
            self.collect_stats()
            self.collect_startup_diagnostics(self._MODE)
            job_type = "rebuild" if rebuild else "build"
            job_id = uuid4().hex
            resolved_request_id = normalize_or_generate_request_id(request_id)
            try:
                resolved_idempotency_key = self._job_registry.repository.validate_idempotency_key(
                    idempotency_key
                )
            except ValueError:
                raise InvalidApiRequestError(
                    "Invalid Idempotency-Key header.",
                    details={"field": "Idempotency-Key", "reason": "invalid_format"},
                ) from None
            try:
                created, job, build_lock = self._job_registry.create_or_active(
                    job_id=job_id,
                    request_id=resolved_request_id,
                    job_type=job_type,
                    message=f"Knowledge base {job_type} job queued.",
                    idempotency_key=resolved_idempotency_key,
                )
            except BuildJobIdempotencyConflictError as exc:
                raise BuildJobConflictError(
                    "Idempotency key conflicts with an existing build job.",
                    job=exc.job,
                ) from None
            if job is not None and bool(job.pop("_idempotency_replayed", False)):
                return job
            if not created or job is None or build_lock is None:
                active_job = job or self._job_registry.active()
                if active_job is None:
                    active_job = {
                        "job_id": job_id,
                        "job_type": job_type,
                        "status": "running",
                        "created_at": _utc_now_iso(),
                        "message": "A build job is already in progress.",
                    }
                raise BuildJobConflictError(
                    "A build job is already in progress.",
                    job=active_job,
                )
            try:
                self._resolve_build_executor().submit(
                    self._run_build_job,
                    job_id,
                    rebuild,
                    build_lock,
                )
            except Exception:
                build_lock.release()
                raise
            return job

    def list_build_jobs(self, *, limit: int | None = None, cursor: str = "") -> BuildJobListPage:
        resolved_limit = int(limit or self._job_registry.repository.settings.list_default_limit)
        try:
            return self._job_registry.list_page(limit=resolved_limit, cursor=cursor)
        except ValueError:
            raise InvalidApiRequestError(
                "Invalid build job cursor.",
                details={"field": "cursor", "reason": "invalid_cursor"},
            ) from None

    def get_build_job(self, job_id: str) -> dict[str, Any]:
        job = self._job_registry.get(str(job_id))
        if job is None:
            raise BuildJobNotFoundError(str(job_id))
        return job

    def artifact_registry_snapshot(self) -> ArtifactRegistrySnapshot:
        return self._artifact_registry.snapshot()

    def _resolve_build_executor(self) -> ThreadPoolExecutor:
        executor = self._build_executor
        if executor is not None:
            return executor
        with self._build_executor_lock:
            executor = self._build_executor
            if executor is None:
                executor = ThreadPoolExecutor(
                    max_workers=_BUILD_JOB_EXECUTOR_MAX_WORKERS,
                    thread_name_prefix="graph-rag-build",
                )
                self._build_executor = executor
        return executor

    def _run_build_job(
        self,
        job_id: str,
        rebuild: bool,
        build_lock: _InterprocessFileLock,
    ) -> None:
        try:
            self._mark_job_running(
                job_id,
                message=(
                    "Knowledge base rebuild started."
                    if rebuild
                    else "Knowledge base build started."
                ),
            )

            progress_started_at = time.perf_counter()

            def progress(message: str) -> None:
                self._append_job_log(
                    job_id,
                    format_build_progress_log(
                        message,
                        elapsed_seconds=time.perf_counter() - progress_started_at,
                    ),
                )

            try:
                with self._exclusive_runtime_operation():
                    if not self.system.is_build_initialized():
                        self.system.initialize_build_runtime(progress=progress)
                    if rebuild:
                        self.system.rebuild_knowledge_base(progress=progress)
                        operation_result = self._operation_response(
                            message="Knowledge base rebuild completed.",
                            mode=self._MODE,
                        )
                    else:
                        self.system.build_knowledge_base(progress=progress)
                        operation_result = self._operation_response(
                            message="Knowledge base build completed.",
                            mode=self._MODE,
                        )
                result = self._job_result_from_operation(operation_result)
                self._mark_job_succeeded(job_id, result=result)
            except Exception:
                self._append_job_log(job_id, "Build failed.")
                diagnostics, stats = self._snapshot_after_build_failure()
                self._mark_job_failed(
                    job_id,
                    result={
                        "message": "Knowledge base build failed.",
                        "diagnostics": diagnostics,
                        "stats": stats,
                    },
                )
        finally:
            build_lock.release()

    @staticmethod
    def _job_result_from_operation(operation_result: dict[str, Any]) -> dict[str, Any]:
        return {
            "message": str(operation_result.get("message", "")),
            "diagnostics": copy.deepcopy(operation_result.get("diagnostics")),
            "stats": copy.deepcopy(operation_result.get("stats")),
        }

    def _snapshot_after_build_failure(self) -> tuple[dict[str, Any], dict[str, Any]]:
        with self._locks.inspection_operation():
            diagnostics = self._cache_diagnostics(
                self._MODE,
                self._collect_startup_diagnostics_unlocked(self._MODE),
            )
            stats = self._cache_stats(self._collect_stats_unlocked())
        return diagnostics, stats

    def _append_job_log(self, job_id: str, message: str) -> None:
        self._job_registry.append_log(job_id, message)

    def _mark_job_running(self, job_id: str, *, message: str) -> None:
        self._job_registry.mark_running(job_id, message=message)

    def _mark_job_succeeded(self, job_id: str, *, result: dict[str, Any]) -> None:
        self._job_registry.mark_succeeded(job_id, result=result)

    def _mark_job_failed(self, job_id: str, *, result: dict[str, Any]) -> None:
        self._job_registry.mark_failed(job_id, result=result)


__all__ = ["GraphRAGBuildApiService"]
