"""Build API service implementation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from ....app.application_protocol import GraphRAGApplication
from ....app.build_jobs import (
    BuildJobApplicationService,
    BuildJobId,
    BuildJobSnapshot,
)
from ....app.build_jobs import (
    BuildJobConflictError as AppBuildJobConflictError,
)
from ....app.build_jobs import (
    BuildJobNotFoundError as AppBuildJobNotFoundError,
)
from ....configuration.models import GraphRAGConfig
from ....kernel.artifacts import ARTIFACT_STAGE_FAILED
from ....kernel.json_types import JsonObject
from ....runtime.artifacts import ArtifactManifestStore
from ....runtime.artifacts.registry import ArtifactRegistry, ArtifactRegistrySnapshot
from ..error_models import ErrorCode
from ..request_context import normalize_or_generate_request_id
from .base import _BaseGraphRAGApiService
from .errors import BuildJobConflictError, BuildJobNotFoundError, InvalidApiRequestError


@dataclass(frozen=True, slots=True)
class BuildJobListPage:
    jobs: list[JsonObject]
    next_cursor: str = ""


class GraphRAGBuildApiService(_BaseGraphRAGApiService):
    """HTTP-facing build surface for offline artifact preparation."""

    _MODE = "build"

    def __init__(
        self,
        *,
        build_jobs: BuildJobApplicationService,
        system: GraphRAGApplication | None = None,
        config: Optional[GraphRAGConfig] = None,
        artifact_registry: ArtifactRegistry | None = None,
    ) -> None:
        super().__init__(system=system, config=config)
        resolved_config = config or getattr(self.system, "config", None)
        self._build_jobs = build_jobs
        self._artifact_registry = artifact_registry or ArtifactRegistry(
            ArtifactManifestStore(resolved_config)
        )

    def _ensure_build_runtime_initialized(self) -> None:
        self._ensure_runtime_initialized(
            is_initialized=self.system.is_build_initialized,
            initializer=self.system.initialize_build_runtime,
        )

    def startup(self, *, auto_initialize_build: bool = False) -> None:
        recovered = self._build_jobs.startup()
        if any(snapshot.status.value == "interrupted" for snapshot in recovered):
            self._recover_interrupted_candidate_manifest()
        if auto_initialize_build:
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
        diagnostics["build_job_store"] = self._build_jobs.diagnostics().to_public_dict()
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
        self._build_jobs.shutdown()
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
            snapshot = self._build_jobs.submit(
                rebuild=rebuild,
                request_id=normalize_or_generate_request_id(request_id),
                idempotency_key=idempotency_key,
            )
        except ValueError:
            raise InvalidApiRequestError(
                "Invalid Idempotency-Key header.",
                details={"field": "Idempotency-Key", "reason": "invalid_format"},
            ) from None
        except AppBuildJobConflictError as exc:
            raise BuildJobConflictError(str(exc), job=exc.snapshot.to_public_dict()) from None
        return _public_job(snapshot)

    def list_build_jobs(self, *, limit: int | None = None, cursor: str = "") -> BuildJobListPage:
        try:
            page = self._build_jobs.list_page(limit=limit, cursor=cursor)
        except ValueError:
            raise InvalidApiRequestError(
                "Invalid build job cursor.",
                details={"field": "cursor", "reason": "invalid_cursor"},
            ) from None
        return BuildJobListPage(
            jobs=[_public_job(snapshot) for snapshot in page.jobs],
            next_cursor=page.next_cursor,
        )

    def get_build_job(self, job_id: str) -> JsonObject:
        try:
            return _public_job(self._build_jobs.get(BuildJobId(str(job_id))))
        except AppBuildJobNotFoundError:
            raise BuildJobNotFoundError(str(job_id)) from None

    def cancel_build_job(self, job_id: str) -> JsonObject:
        try:
            return _public_job(self._build_jobs.cancel(BuildJobId(str(job_id))))
        except AppBuildJobNotFoundError:
            raise BuildJobNotFoundError(str(job_id)) from None
        except AppBuildJobConflictError as exc:
            raise BuildJobConflictError(str(exc), job=exc.snapshot.to_public_dict()) from None

    def retry_build_job(self, job_id: str, *, request_id: str = "") -> JsonObject:
        try:
            return _public_job(
                self._build_jobs.retry(
                    BuildJobId(str(job_id)),
                    request_id=normalize_or_generate_request_id(request_id),
                    idempotency_key="",
                )
            )
        except AppBuildJobNotFoundError:
            raise BuildJobNotFoundError(str(job_id)) from None
        except AppBuildJobConflictError as exc:
            raise BuildJobConflictError(str(exc), job=exc.snapshot.to_public_dict()) from None

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


def _public_job(snapshot: BuildJobSnapshot) -> JsonObject:
    return snapshot.to_public_dict()


__all__ = ["BuildJobListPage", "GraphRAGBuildApiService"]
