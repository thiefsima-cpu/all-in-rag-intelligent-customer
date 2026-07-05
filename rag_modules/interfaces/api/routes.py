"""Route registration helpers for serving and build API surfaces."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Header, Path, Query
from fastapi.responses import JSONResponse, StreamingResponse

from .answer_models import (
    AnswerRequestModel,
    AnswerResponseModel,
    AnswerStreamRequestModel,
    PublicAnswerResponseModel,
)
from .build_models import (
    ArtifactRegistryResponseModel,
    BuildJobListResponseModel,
    BuildJobResponseModel,
)
from .diagnostics_models import (
    DiagnosticsMode,
    DiagnosticsResponseModel,
    HealthResponseModel,
    OperationResponseModel,
    StatsResponseModel,
)
from .request_context import current_request_id
from .response_builder import (
    build_artifact_registry_response,
    build_build_job_list_response,
    build_build_job_response,
    build_diagnostics_response,
    build_operation_response,
    build_stats_response,
)
from .route_handlers import (
    build_answer_http_response,
    build_answer_stream_http_response,
    build_readiness_response,
)
from .services import (
    GraphRAGBuildApiService,
    GraphRAGServingApiService,
)
from .versioning import API_PREFIX

_SSE_EXAMPLE = (
    "event: message\n"
    'data: {"message":"Running query routing..."}\n\n'
    "event: chunk\n"
    'data: {"content":"first token"}\n\n'
    "event: result\n"
    'data: {"response":{"summary":{"answer":"..."}}}\n\n'
    "event: done\n"
    'data: {"ok":true}\n\n'
)


def register_serving_routes(app: FastAPI, api_service: GraphRAGServingApiService) -> None:
    _register_serving_operational_routes(app, api_service)
    _register_serving_answer_request_routes(app, api_service)
    _register_serving_answer_stream_routes(app, api_service)


def _register_serving_operational_routes(
    app: FastAPI,
    api_service: GraphRAGServingApiService,
) -> None:
    @app.get(f"{API_PREFIX}/health", response_model=HealthResponseModel)
    def read_health() -> dict[str, Any]:
        return api_service.health()

    @app.get(f"{API_PREFIX}/health/live", response_model=HealthResponseModel)
    def read_liveness() -> dict[str, Any]:
        return api_service.health()

    @app.get(
        f"{API_PREFIX}/health/ready",
        response_model=HealthResponseModel,
        responses={503: {"description": "Serving runtime is not ready."}},
    )
    def read_readiness() -> JSONResponse:
        return build_readiness_response(api_service.readiness())

    @app.get(f"{API_PREFIX}/stats", response_model=StatsResponseModel)
    def read_stats() -> StatsResponseModel:
        return build_stats_response(api_service.collect_stats())

    @app.get(
        f"{API_PREFIX}/diagnostics",
        response_model=DiagnosticsResponseModel,
    )
    def read_diagnostics() -> DiagnosticsResponseModel:
        return build_diagnostics_response(
            api_service.collect_startup_diagnostics(DiagnosticsMode.serve.value)
        )

    @app.post(
        f"{API_PREFIX}/runtime/serving/initialize",
        response_model=OperationResponseModel,
    )
    def initialize_serving_runtime() -> OperationResponseModel:
        return build_operation_response(api_service.initialize_serving_runtime())

    @app.post(
        f"{API_PREFIX}/runtime/serving/refresh",
        response_model=OperationResponseModel,
    )
    def refresh_serving_runtime() -> OperationResponseModel:
        return build_operation_response(api_service.refresh_serving_runtime())


def _register_serving_answer_request_routes(
    app: FastAPI,
    api_service: GraphRAGServingApiService,
) -> None:
    @app.post(
        f"{API_PREFIX}/answers",
        response_model=PublicAnswerResponseModel,
        summary="Get one public answer payload",
        description=(
            "Returns the grounded answer without full trace snapshots. "
            "Use `/v1/debug/answers` when complete traces are needed."
        ),
        responses={
            200: {"description": "Public answer payload or compatibility SSE stream."},
            409: {"description": "Serving runtime is initialized but artifacts are not ready."},
        },
    )
    def answer_question_v1(
        payload: AnswerRequestModel,
    ) -> PublicAnswerResponseModel | StreamingResponse:
        return build_answer_http_response(
            api_service,
            payload,
            include_traces=False,
        )

    @app.post(
        f"{API_PREFIX}/debug/answers",
        response_model=AnswerResponseModel,
        summary="Get one debug answer payload with traces",
        description="Returns the grounded answer with complete trace snapshots.",
        responses={
            200: {"description": "Debug answer payload with complete traces."},
            409: {"description": "Serving runtime is initialized but artifacts are not ready."},
        },
    )
    def debug_answer_question_v1(
        payload: AnswerRequestModel,
    ) -> AnswerResponseModel | StreamingResponse:
        return build_answer_http_response(
            api_service,
            payload,
            include_traces=True,
        )


def _register_serving_answer_stream_routes(
    app: FastAPI,
    api_service: GraphRAGServingApiService,
) -> None:
    @app.post(
        f"{API_PREFIX}/answers/stream",
        summary="Stream public answer events over SSE",
        description=(
            "Streams question-answering progress and output without full trace snapshots. "
            "Use `/v1/debug/answers/stream` when complete traces are needed."
        ),
        response_class=StreamingResponse,
        responses={
            200: {
                "description": "Server-Sent Events stream.",
                "content": {
                    "text/event-stream": {
                        "example": _SSE_EXAMPLE,
                    }
                },
            },
            409: {"description": "Serving runtime is initialized but artifacts are not ready."},
        },
    )
    def stream_answer_question_v1(payload: AnswerStreamRequestModel) -> StreamingResponse:
        return build_answer_stream_http_response(
            api_service,
            payload,
            include_traces=False,
        )

    @app.post(
        f"{API_PREFIX}/debug/answers/stream",
        summary="Stream debug answer events over SSE with traces",
        description="Streams question-answering progress and output with complete trace snapshots.",
        response_class=StreamingResponse,
        responses={
            200: {
                "description": "Debug Server-Sent Events stream.",
                "content": {
                    "text/event-stream": {
                        "example": _SSE_EXAMPLE,
                    }
                },
            },
            409: {"description": "Serving runtime is initialized but artifacts are not ready."},
        },
    )
    def stream_debug_answer_question_v1(
        payload: AnswerStreamRequestModel,
    ) -> StreamingResponse:
        return build_answer_stream_http_response(
            api_service,
            payload,
            include_traces=True,
        )


def register_build_routes(app: FastAPI, api_service: GraphRAGBuildApiService) -> None:
    _register_build_operational_routes(app, api_service)
    _register_build_read_routes(app, api_service)
    _register_build_control_routes(app, api_service)
    _register_build_submission_routes(app, api_service)


def _register_build_operational_routes(
    app: FastAPI,
    api_service: GraphRAGBuildApiService,
) -> None:
    @app.get(f"{API_PREFIX}/health", response_model=HealthResponseModel)
    def read_health() -> dict[str, Any]:
        return api_service.health()

    @app.get(f"{API_PREFIX}/health/live", response_model=HealthResponseModel)
    def read_liveness() -> dict[str, Any]:
        return api_service.health()

    @app.get(
        f"{API_PREFIX}/health/ready",
        response_model=HealthResponseModel,
        responses={503: {"description": "Build runtime is not ready."}},
    )
    def read_readiness() -> JSONResponse:
        return build_readiness_response(api_service.readiness())

    @app.get(f"{API_PREFIX}/stats", response_model=StatsResponseModel)
    def read_stats() -> StatsResponseModel:
        return build_stats_response(api_service.collect_stats())

    @app.get(
        f"{API_PREFIX}/diagnostics",
        response_model=DiagnosticsResponseModel,
    )
    def read_diagnostics() -> DiagnosticsResponseModel:
        return build_diagnostics_response(
            api_service.collect_startup_diagnostics(DiagnosticsMode.build.value)
        )

    @app.post(
        f"{API_PREFIX}/runtime/build/initialize",
        response_model=OperationResponseModel,
    )
    def initialize_build_runtime() -> OperationResponseModel:
        return build_operation_response(api_service.initialize_build_runtime())


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
    "register_serving_routes",
]
