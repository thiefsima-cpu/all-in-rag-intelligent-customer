"""Internal build-job application composition."""

from __future__ import annotations

import os
from importlib import import_module
from typing import Any

from ...configuration.models import GraphRAGConfig
from ...kernel.json_types import coerce_json_object
from ..application_protocol import GraphRAGApplication
from ..build_jobs import (
    BuildJobApplicationService,
    BuildJobExecutor,
    BuildJobRepositorySettings,
    BuildJobRuntimeHooks,
)
from ..runtime_operations import RuntimeOperationCoordinator


def compose_build_job_application(
    *,
    system: GraphRAGApplication,
    config: GraphRAGConfig,
    coordinator: RuntimeOperationCoordinator,
) -> BuildJobApplicationService:
    api_settings = config.api
    if api_settings.build_job_runner_backend != "in_process":
        raise ValueError(
            f"Unsupported build job runner backend: {api_settings.build_job_runner_backend!r}"
    )
    store_path = default_build_job_store_path(config)
    runtime_build_jobs = _runtime_build_jobs_module()
    runtime_build_jobs.BuildJobStoreMigrator(store_path, now=_utc_now).migrate()
    repository = runtime_build_jobs.FileBuildJobRepository(
        store_path,
        now=_utc_now,
        settings=BuildJobRepositorySettings(
            retention_limit=int(api_settings.build_job_retention_limit),
            list_default_limit=int(api_settings.build_job_list_default_limit),
            list_max_limit=int(api_settings.build_job_list_max_limit),
            lease_seconds=float(getattr(api_settings, "build_job_lease_seconds", 30.0)),
        ),
    )
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
    executor = BuildJobExecutor(hooks=hooks)
    runner = runtime_build_jobs.InProcessBuildJobRunner(
        repository=repository,
        executor=executor,
        max_workers=int(api_settings.build_job_runner_max_workers),
        worker_id="in_process",
        heartbeat_seconds=float(getattr(api_settings, "build_job_heartbeat_seconds", 10.0)),
    )
    return BuildJobApplicationService(repository=repository, runner=runner, now=_utc_now)


def _runtime_build_jobs_module():
    return import_module("rag_modules.runtime.build_jobs")


def default_build_job_store_path(config: Any) -> str:
    storage = getattr(config, "storage", None)
    configured_path = str(getattr(storage, "build_job_store_path", "") or "")
    if configured_path:
        return configured_path
    manifest_path = str(
        getattr(storage, "artifact_manifest_path", "")
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


def _utc_now():
    from datetime import datetime, timezone

    return datetime.now(timezone.utc)


__all__ = ["compose_build_job_application", "default_build_job_store_path"]
