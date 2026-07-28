"""Build route registration helpers."""

from __future__ import annotations

from fastapi import FastAPI, Header, Path, Query

from .build_models import (
    ArtifactRegistryResponseModel,
    BuildJobAuditEventListResponseModel,
    BuildJobListResponseModel,
    BuildJobResponseModel,
)
from .error_models import ErrorResponseModel
from .operational_routes import register_build_operational_routes
from .request_context import current_request_id
from .response_builder import (
    build_artifact_registry_response,
    build_build_job_event_list_response,
    build_build_job_list_response,
    build_build_job_response,
)
from .services import GraphRAGBuildApiService
from .versioning import API_PREFIX


def register_build_routes(app: FastAPI, api_service: GraphRAGBuildApiService) -> None:
    register_build_operational_routes(app, api_service)
    _register_build_read_routes(app, api_service)
    _register_build_control_routes(app, api_service)
    _register_build_submission_routes(app, api_service)


def _register_build_read_routes(
    app: FastAPI,
    api_service: GraphRAGBuildApiService,
) -> None:
    @app.get(f"{API_PREFIX}/jobs", response_model=BuildJobListResponseModel)
    def list_build_jobs(
        limit: int | None = Query(default=None, ge=1),
        cursor: str = Query(default=""),
    ) -> BuildJobListResponseModel:
        page = api_service.list_build_jobs(limit=limit, cursor=cursor)
        return build_build_job_list_response(page.jobs, next_cursor=page.next_cursor)

    @app.get(
        f"{API_PREFIX}/artifacts",
        response_model=ArtifactRegistryResponseModel,
    )
    def read_artifact_registry() -> ArtifactRegistryResponseModel:
        return build_artifact_registry_response(api_service.artifact_registry_snapshot())

    @app.get(
        f"{API_PREFIX}/jobs/{{job_id}}",
        response_model=BuildJobResponseModel,
    )
    def read_build_job(
        job_id: str = Path(pattern=r"^[0-9a-f]{32}$"),
    ) -> BuildJobResponseModel:
        return build_build_job_response(api_service.get_build_job(job_id))

    @app.get(
        f"{API_PREFIX}/jobs/{{job_id}}/events",
        response_model=BuildJobAuditEventListResponseModel,
        summary="List build job audit events",
        description="Returns the privacy-safe audit history for a build job.",
        responses={
            400: {
                "model": ErrorResponseModel,
                "description": "Build job event cursor is invalid.",
            },
            404: {
                "model": ErrorResponseModel,
                "description": "Build job was not found.",
            },
            503: {
                "model": ErrorResponseModel,
                "description": "Build job store is unavailable.",
            },
        },
    )
    def list_build_job_events(
        job_id: str = Path(pattern=r"^[0-9a-f]{32}$"),
        limit: int | None = Query(default=None, ge=1),
        cursor: str = Query(default=""),
    ) -> BuildJobAuditEventListResponseModel:
        page = api_service.list_build_job_events(job_id, limit=limit, cursor=cursor)
        return build_build_job_event_list_response(page.events, next_cursor=page.next_cursor)


def _register_build_control_routes(
    app: FastAPI,
    api_service: GraphRAGBuildApiService,
) -> None:
    @app.post(
        f"{API_PREFIX}/jobs/{{job_id}}/cancel",
        response_model=BuildJobResponseModel,
        status_code=202,
        summary="Cancel a build job",
        description="Requests cooperative cancellation of a queued or running build job.",
        responses={
            404: {"description": "Build job was not found."},
            409: {"description": "Build job cannot be cancelled from its current state."},
        },
    )
    def cancel_build_job(
        job_id: str = Path(pattern=r"^[0-9a-f]{32}$"),
    ) -> BuildJobResponseModel:
        return build_build_job_response(api_service.cancel_build_job(job_id))

    @app.post(
        f"{API_PREFIX}/jobs/{{job_id}}/retry",
        response_model=BuildJobResponseModel,
        status_code=202,
        summary="Retry a build job",
        description="Queues a new build job linked to a failed or cancelled job.",
        responses={
            404: {"description": "Build job was not found."},
            409: {"description": "Build job cannot be retried from its current state."},
        },
    )
    def retry_build_job(
        job_id: str = Path(pattern=r"^[0-9a-f]{32}$"),
    ) -> BuildJobResponseModel:
        return build_build_job_response(
            api_service.retry_build_job(
                job_id,
                request_id=current_request_id(),
            )
        )


def _register_build_submission_routes(
    app: FastAPI,
    api_service: GraphRAGBuildApiService,
) -> None:
    @app.post(
        f"{API_PREFIX}/jobs/build",
        response_model=BuildJobResponseModel,
        status_code=202,
        summary="Queue a build job",
        description="Queues an asynchronous knowledge-base build job and returns a job identifier.",
        responses={409: {"description": "Another build job is already in progress."}},
    )
    def queue_build_job(
        idempotency_key: str = Header(default="", alias="Idempotency-Key"),
    ) -> BuildJobResponseModel:
        return build_build_job_response(
            api_service.submit_build_job(
                rebuild=False,
                request_id=current_request_id(),
                idempotency_key=idempotency_key,
            )
        )

    @app.post(
        f"{API_PREFIX}/jobs/rebuild",
        response_model=BuildJobResponseModel,
        status_code=202,
        summary="Queue a rebuild job",
        description="Queues an asynchronous knowledge-base rebuild job and returns a job identifier.",
        responses={409: {"description": "Another build job is already in progress."}},
    )
    def queue_rebuild_job(
        idempotency_key: str = Header(default="", alias="Idempotency-Key"),
    ) -> BuildJobResponseModel:
        return build_build_job_response(
            api_service.submit_build_job(
                rebuild=True,
                request_id=current_request_id(),
                idempotency_key=idempotency_key,
            )
        )


__all__ = [
    "register_build_routes",
]
