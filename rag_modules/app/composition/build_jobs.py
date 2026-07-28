"""Internal build-job application composition."""

from __future__ import annotations

import os
from collections.abc import Callable
from datetime import datetime, timezone
from importlib import import_module
from typing import Protocol, cast

from ...configuration.models import GraphRAGConfig
from ...contracts.build_jobs import JobProgressRecorded, JobSucceeded
from ...kernel.json_types import JsonObject, coerce_json_object
from ...telemetry import get_runtime_telemetry
from ..application_protocol import GraphRAGApplication
from ..build_jobs import (
    BuildJobApplicationService,
    BuildJobExecutor,
    BuildJobRepositoryError,
    BuildJobRepositoryPort,
    BuildJobRepositorySettings,
    BuildJobRunnerPort,
    BuildJobRuntimeHooks,
    BuildJobSnapshot,
)
from ..runtime_operations import RuntimeOperationCoordinator

_BuildJobExecution = Callable[
    [BuildJobSnapshot, Callable[[JobProgressRecorded], None], Callable[[], None]],
    JobSucceeded,
]
_BuildJobResult = Callable[[], JsonObject]

_Clock = Callable[[], datetime]
BuildJobRepositoryFactory = Callable[[GraphRAGConfig], BuildJobRepositoryPort]
_BuildLeaseRecorder = Callable[[str, str, int], None]


class _BuildJobStoreMigrator(Protocol):
    def migrate(self) -> None: ...


class _BuildJobStoreMigratorFactory(Protocol):
    def __call__(self, path: str, *, now: _Clock) -> _BuildJobStoreMigrator: ...


class _FileBuildJobRepositoryFactory(Protocol):
    def __call__(
        self,
        path: str,
        *,
        now: _Clock,
        settings: BuildJobRepositorySettings,
    ) -> BuildJobRepositoryPort: ...


class _InProcessBuildJobRunnerFactory(Protocol):
    def __call__(
        self,
        *,
        repository: BuildJobRepositoryPort,
        execute_build: _BuildJobExecution,
        cancelled_result: _BuildJobResult,
        failed_result: _BuildJobResult,
        max_workers: int,
        worker_id: str,
        heartbeat_seconds: float,
        lease_recorder: _BuildLeaseRecorder | None = None,
    ) -> BuildJobRunnerPort: ...


class _ExternalBuildJobQueueRunnerFactory(Protocol):
    def __call__(self) -> BuildJobRunnerPort: ...


class BuildJobWorkerRunnerPort(BuildJobRunnerPort, Protocol):
    backend: str
    poll_interval_seconds: float

    def poll_once(self) -> None: ...


class _ExternalBuildJobWorkerRunnerFactory(Protocol):
    def __call__(
        self,
        *,
        repository: BuildJobRepositoryPort,
        execute_build: _BuildJobExecution,
        cancelled_result: _BuildJobResult,
        failed_result: _BuildJobResult,
        max_workers: int,
        worker_id: str,
        heartbeat_seconds: float,
        poll_interval_seconds: float,
        lease_recorder: _BuildLeaseRecorder | None = None,
        repository_close: Callable[[], None] | None = None,
    ) -> BuildJobWorkerRunnerPort: ...


class _RuntimeBuildJobsModule(Protocol):
    BuildJobStoreMigrator: _BuildJobStoreMigratorFactory
    FileBuildJobRepository: _FileBuildJobRepositoryFactory
    PostgresBuildJobRepository: Callable[..., BuildJobRepositoryPort]
    InProcessBuildJobRunner: _InProcessBuildJobRunnerFactory
    ExternalBuildJobQueueRunner: _ExternalBuildJobQueueRunnerFactory
    ExternalBuildJobWorkerRunner: _ExternalBuildJobWorkerRunnerFactory


def compose_build_job_application(
    *,
    system: GraphRAGApplication,
    config: GraphRAGConfig,
    coordinator: RuntimeOperationCoordinator,
    repository_factory: BuildJobRepositoryFactory | None = None,
) -> BuildJobApplicationService:
    api_settings = config.api
    runtime_build_jobs = _runtime_build_jobs_module()
    repository = _compose_repository(
        runtime_build_jobs=runtime_build_jobs,
        config=config,
        repository_factory=repository_factory,
    )
    telemetry = get_runtime_telemetry(config)
    runner = _compose_api_runner(
        runtime_build_jobs=runtime_build_jobs,
        backend=str(api_settings.build_job_runner_backend),
        repository=repository,
        executor_factory=lambda: _compose_executor(system=system, coordinator=coordinator),
        max_workers=int(api_settings.build_job_runner_max_workers),
        heartbeat_seconds=float(api_settings.build_job_heartbeat_seconds),
        lease_recorder=lambda backend, event, active_delta: telemetry.record_build_lease_event(
            backend=backend,
            event=event,
            active_delta=active_delta,
        ),
    )
    return BuildJobApplicationService(repository=repository, runner=runner, now=_utc_now)


def compose_build_job_worker(
    *,
    system: GraphRAGApplication,
    config: GraphRAGConfig,
    coordinator: RuntimeOperationCoordinator,
    worker_id: str = "external-worker",
    repository_factory: BuildJobRepositoryFactory | None = None,
) -> BuildJobWorkerRunnerPort:
    """Compose a long-running external build-job worker runner."""

    api_settings = config.api
    runtime_build_jobs = _runtime_build_jobs_module()
    repository = _compose_repository(
        runtime_build_jobs=runtime_build_jobs,
        config=config,
        repository_factory=repository_factory,
    )
    telemetry = get_runtime_telemetry(config)
    executor = _compose_executor(system=system, coordinator=coordinator)
    return runtime_build_jobs.ExternalBuildJobWorkerRunner(
        repository=repository,
        execute_build=lambda snapshot, progress, cancellation_check: executor.execute(
            snapshot,
            progress=progress,
            cancellation_check=cancellation_check,
        ),
        cancelled_result=executor.cancelled_result,
        failed_result=executor.failed_result,
        max_workers=int(api_settings.build_job_runner_max_workers),
        worker_id=worker_id,
        heartbeat_seconds=float(api_settings.build_job_heartbeat_seconds),
        poll_interval_seconds=float(api_settings.build_job_worker_poll_interval_seconds),
        lease_recorder=lambda backend, event, active_delta: telemetry.record_build_lease_event(
            backend=backend,
            event=event,
            active_delta=active_delta,
        ),
        repository_close=repository.close,
    )


def _compose_repository(
    *,
    runtime_build_jobs: _RuntimeBuildJobsModule,
    config: GraphRAGConfig,
    repository_factory: BuildJobRepositoryFactory | None,
) -> BuildJobRepositoryPort:
    if repository_factory is not None:
        return repository_factory(config)
    api_settings = config.api
    if api_settings.build_job_repository_backend == "file":
        return _compose_file_repository(runtime_build_jobs=runtime_build_jobs, config=config)
    if api_settings.build_job_repository_backend == "postgresql":
        dsn = config.storage.build_job_postgres_dsn
        if not dsn.strip():
            raise BuildJobRepositoryError("Build job PostgreSQL DSN is required.")
        return runtime_build_jobs.PostgresBuildJobRepository(
            dsn,
            now=_utc_now,
            settings=_repository_settings(config),
            pool_min_size=int(api_settings.build_job_postgres_pool_min_size),
            pool_max_size=int(api_settings.build_job_postgres_pool_max_size),
            pool_timeout_seconds=float(api_settings.build_job_postgres_pool_timeout_seconds),
        )
    raise ValueError("Unsupported build job repository backend.")


def _compose_file_repository(
    *,
    runtime_build_jobs: _RuntimeBuildJobsModule,
    config: GraphRAGConfig,
) -> BuildJobRepositoryPort:
    store_path = default_build_job_store_path(config)
    runtime_build_jobs.BuildJobStoreMigrator(store_path, now=_utc_now).migrate()
    return runtime_build_jobs.FileBuildJobRepository(
        store_path,
        now=_utc_now,
        settings=_repository_settings(config),
    )


def _repository_settings(config: GraphRAGConfig) -> BuildJobRepositorySettings:
    api_settings = config.api
    return BuildJobRepositorySettings(
        retention_limit=int(api_settings.build_job_retention_limit),
        list_default_limit=int(api_settings.build_job_list_default_limit),
        list_max_limit=int(api_settings.build_job_list_max_limit),
        lease_seconds=float(api_settings.build_job_lease_seconds),
        audit_retention_days=int(api_settings.build_job_audit_retention_days),
    )


def _compose_api_runner(
    *,
    runtime_build_jobs: _RuntimeBuildJobsModule,
    backend: str,
    repository: BuildJobRepositoryPort,
    executor_factory: Callable[[], BuildJobExecutor],
    max_workers: int,
    heartbeat_seconds: float,
    lease_recorder: _BuildLeaseRecorder | None,
) -> BuildJobRunnerPort:
    if backend == "external_worker":
        return runtime_build_jobs.ExternalBuildJobQueueRunner()
    if backend == "in_process":
        executor = executor_factory()
        return runtime_build_jobs.InProcessBuildJobRunner(
            repository=repository,
            execute_build=lambda snapshot, progress, cancellation_check: executor.execute(
                snapshot,
                progress=progress,
                cancellation_check=cancellation_check,
            ),
            cancelled_result=executor.cancelled_result,
            failed_result=executor.failed_result,
            max_workers=max_workers,
            worker_id="in_process",
            heartbeat_seconds=heartbeat_seconds,
            lease_recorder=lease_recorder,
        )
    raise ValueError(f"Unsupported build job runner backend: {backend!r}")


def _compose_executor(
    *,
    system: GraphRAGApplication,
    coordinator: RuntimeOperationCoordinator,
) -> BuildJobExecutor:
    hooks = BuildJobRuntimeHooks(
        system=system,
        lifecycle_operation=coordinator.lifecycle_operation,
        operation_response=lambda message: _operation_response(
            system,
            coordinator,
            message=message,
        ),
        failure_snapshot=lambda: _failure_snapshot(system, coordinator),
    )
    return BuildJobExecutor(hooks=hooks)


def _runtime_build_jobs_module() -> _RuntimeBuildJobsModule:
    return cast(_RuntimeBuildJobsModule, import_module("rag_modules.runtime.build_jobs"))


def default_build_job_store_path(config: GraphRAGConfig) -> str:
    storage = config.storage
    configured_path = str(storage.build_job_store_path or "")
    if configured_path:
        return configured_path
    manifest_path = str(
        storage.artifact_manifest_path
        or os.path.join("storage", "indexes", "artifact_manifest.json")
    )
    return os.path.join(os.path.dirname(manifest_path), "build_jobs.json")


def _operation_response(
    system: GraphRAGApplication,
    coordinator: RuntimeOperationCoordinator,
    *,
    message: str,
) -> dict:
    with coordinator.inspection_operation():
        return coerce_json_object(
            {
                "ok": True,
                "message": message,
                "diagnostics": system.collect_startup_diagnostics("build").to_dict(),
                "stats": system.collect_system_stats(),
            }
        )


def _failure_snapshot(
    system: GraphRAGApplication,
    coordinator: RuntimeOperationCoordinator,
) -> tuple[dict, dict]:
    with coordinator.inspection_operation():
        diagnostics = coerce_json_object(system.collect_startup_diagnostics("build").to_dict())
        stats = coerce_json_object(system.collect_system_stats())
    return diagnostics, stats


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


__all__ = [
    "BuildJobRepositoryFactory",
    "compose_build_job_application",
    "compose_build_job_worker",
    "default_build_job_store_path",
]
