"""Build API service implementation."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from ....app.application_protocol import GraphRAGApplication
from ....configuration.models import GraphRAGConfig
from ....runtime.artifacts import ARTIFACT_STAGE_FAILED, ArtifactManifestStore
from ....runtime.artifacts.registry import ArtifactRegistry, ArtifactRegistrySnapshot
from ....runtime.json_types import JsonObject
from ..build_job_store import (
    BuildJobListPage,
    BuildJobRepositorySettings,
    BuildJobRunnerConflictError,
    BuildJobRunnerNotFoundError,
    BuildJobRuntimeHooks,
    FileBuildJobStore,
    PersistentBuildJobRegistry,
    create_build_job_runner,
    default_build_job_store_path,
)
from ..error_models import ErrorCode
from ..request_context import normalize_or_generate_request_id
from .base import _BaseGraphRAGApiService
from .errors import BuildJobConflictError, BuildJobNotFoundError, InvalidApiRequestError


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
        resolved_config = config or getattr(self.system, "config", None)
        resolved_job_store = job_store or FileBuildJobStore(
            default_build_job_store_path(resolved_config)
        )
        self._artifact_registry = artifact_registry or ArtifactRegistry(
            ArtifactManifestStore(resolved_config)
        )
        recover_interrupted = not resolved_job_store.build_lock_held()
        api_settings = getattr(resolved_config, "api", None)
        repository_settings = BuildJobRepositorySettings(
            retention_limit=int(getattr(api_settings, "build_job_retention_limit", 100)),
            list_default_limit=int(getattr(api_settings, "build_job_list_default_limit", 50)),
            list_max_limit=int(getattr(api_settings, "build_job_list_max_limit", 100)),
        )
        job_registry = PersistentBuildJobRegistry(
            resolved_job_store,
            now=_utc_now_iso,
            recover_interrupted=recover_interrupted,
            settings=repository_settings,
        )
        self._build_job_runner = create_build_job_runner(
            backend=str(getattr(api_settings, "build_job_runner_backend", "in_process")),
            registry=job_registry,
            hooks=BuildJobRuntimeHooks(
                system=self.system,
                lifecycle_operation=self._exclusive_runtime_operation,
                operation_response=lambda message: self._operation_response(
                    message=message,
                    mode=self._MODE,
                ),
                failure_snapshot=self._snapshot_after_build_failure,
            ),
            max_workers=int(getattr(api_settings, "build_job_runner_max_workers", 1)),
        )
        if recover_interrupted:
            self._recover_interrupted_candidate_manifest()

    def _ensure_build_runtime_initialized(self) -> None:
        self._ensure_runtime_initialized(
            is_initialized=self.system.is_build_initialized,
            initializer=self.system.initialize_build_runtime,
        )

    def startup(self, *, auto_initialize_build: bool = False) -> None:
        if not auto_initialize_build:
            return
        self._ensure_build_runtime_initialized()

    def health(self) -> JsonObject:
        return self._health_payload(self.collect_startup_diagnostics(self._MODE))

    def readiness(self) -> JsonObject:
        diagnostics = self.collect_startup_diagnostics(self._MODE)
        return self._readiness_payload(
            diagnostics,
            ready=bool(diagnostics["build_initialized"]),
        )

    def _collect_startup_diagnostics_unlocked(self, mode: str) -> JsonObject:
        diagnostics = super()._collect_startup_diagnostics_unlocked(mode)
        diagnostics["build_job_store"] = self._build_job_runner.corruption_summary()
        return diagnostics

    def initialize_build_runtime(self) -> JsonObject:
        with self._exclusive_runtime_operation():
            if not self.system.is_build_initialized():
                self.system.initialize_build_runtime()
            return self._operation_response(
                message="Build runtime initialized.",
                mode=self._MODE,
            )

    def shutdown(self) -> None:
        self._build_job_runner.shutdown()
        super().shutdown()

    def build_knowledge_base(
        self,
        *,
        rebuild: bool = False,
        request_id: str = "",
        idempotency_key: str = "",
    ) -> JsonObject:
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
    ) -> JsonObject:
        self.collect_stats()
        self.collect_startup_diagnostics(self._MODE)
        try:
            return self._build_job_runner.submit(
                rebuild=rebuild,
                request_id=normalize_or_generate_request_id(request_id),
                idempotency_key=idempotency_key,
            )
        except ValueError:
            raise InvalidApiRequestError(
                "Invalid Idempotency-Key header.",
                details={"field": "Idempotency-Key", "reason": "invalid_format"},
            ) from None
        except BuildJobRunnerConflictError as exc:
            raise BuildJobConflictError(str(exc), job=exc.job) from None

    def list_build_jobs(self, *, limit: int | None = None, cursor: str = "") -> BuildJobListPage:
        resolved_limit = int(limit or self._build_job_runner.list_default_limit)
        try:
            return self._build_job_runner.list_page(limit=resolved_limit, cursor=cursor)
        except ValueError:
            raise InvalidApiRequestError(
                "Invalid build job cursor.",
                details={"field": "cursor", "reason": "invalid_cursor"},
            ) from None

    def get_build_job(self, job_id: str) -> JsonObject:
        try:
            return self._build_job_runner.get(str(job_id))
        except BuildJobRunnerNotFoundError:
            raise BuildJobNotFoundError(str(job_id))

    def cancel_build_job(self, job_id: str) -> JsonObject:
        try:
            return self._build_job_runner.cancel(str(job_id))
        except BuildJobRunnerNotFoundError:
            raise BuildJobNotFoundError(str(job_id)) from None
        except BuildJobRunnerConflictError as exc:
            raise BuildJobConflictError(str(exc), job=exc.job) from None

    def retry_build_job(self, job_id: str, *, request_id: str = "") -> JsonObject:
        try:
            return self._build_job_runner.retry(
                str(job_id),
                request_id=normalize_or_generate_request_id(request_id),
            )
        except BuildJobRunnerNotFoundError:
            raise BuildJobNotFoundError(str(job_id)) from None
        except BuildJobRunnerConflictError as exc:
            raise BuildJobConflictError(str(exc), job=exc.job) from None

    def artifact_registry_snapshot(self) -> ArtifactRegistrySnapshot:
        return self._artifact_registry.snapshot()

    def _recover_interrupted_candidate_manifest(self) -> None:
        manifest_store = self._artifact_registry.manifest_store
        load_candidate = getattr(manifest_store, "load_candidate", None)
        save_candidate = getattr(manifest_store, "save_candidate", None)
        if not callable(load_candidate) or not callable(save_candidate):
            return
        candidate = load_candidate()
        if candidate is None or not candidate.is_in_progress:
            return
        failure_code = ErrorCode.BUILD_FAILED.value
        save_candidate(
            candidate.evolve(
                stage=ARTIFACT_STAGE_FAILED,
                last_error=failure_code,
                build_metadata={
                    "failure": {
                        "code": failure_code,
                        "error_type": "ProcessInterrupted",
                    }
                },
            )
        )

    def _snapshot_after_build_failure(self) -> tuple[JsonObject, JsonObject]:
        with self._locks.inspection_operation():
            diagnostics = self._cache_diagnostics(
                self._MODE,
                self._collect_startup_diagnostics_unlocked(self._MODE),
            )
            stats = self._cache_stats(self._collect_stats_unlocked())
        return diagnostics, stats


__all__ = ["GraphRAGBuildApiService"]
