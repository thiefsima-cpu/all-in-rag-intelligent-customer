"""Route registration helpers for serving and build API surfaces."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Literal, TypeVar

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
    build_answer_response,
    build_artifact_registry_response,
    build_build_job_list_response,
    build_build_job_response,
    build_diagnostics_response,
    build_json_response,
    build_operation_response,
    build_public_answer_response,
    build_sse_streaming_response,
    build_stats_response,
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

_RouteMethod = Literal["get", "post"]
_RouteEndpoint = TypeVar("_RouteEndpoint", bound=Callable[..., object])


def _versioned_alias_route(
    app: FastAPI,
    method: _RouteMethod,
    path: str,
    **kwargs: Any,
) -> Callable[[_RouteEndpoint], _RouteEndpoint]:
    def decorator(endpoint: _RouteEndpoint) -> _RouteEndpoint:
        registrar = getattr(app, method)
        registrar(path, **kwargs)(endpoint)
        registrar(f"{API_PREFIX}{path}", **kwargs)(endpoint)
        return endpoint

    return decorator


def register_serving_routes(app: FastAPI, api_service: GraphRAGServingApiService) -> None:
    @app.get("/", response_model=HealthResponseModel)
    def read_root() -> dict[str, Any]:
        return api_service.health()

    @_versioned_alias_route(app, "get", "/health", response_model=HealthResponseModel)
    def read_health() -> dict[str, Any]:
        return api_service.health()

    @_versioned_alias_route(app, "get", "/health/live", response_model=HealthResponseModel)
    def read_liveness() -> dict[str, Any]:
        return api_service.health()

    @_versioned_alias_route(
        app,
        "get",
        "/health/ready",
        response_model=HealthResponseModel,
        responses={503: {"description": "Serving runtime is not ready."}},
    )
    def read_readiness() -> JSONResponse:
        payload = api_service.readiness()
        return build_json_response(
            status_code=200 if payload["status"] == "ok" else 503,
            content=payload,
        )

    @_versioned_alias_route(app, "get", "/stats", response_model=StatsResponseModel)
    def read_stats() -> StatsResponseModel:
        return build_stats_response(api_service.collect_stats())

    @_versioned_alias_route(
        app,
        "get",
        "/diagnostics",
        response_model=DiagnosticsResponseModel,
    )
    def read_diagnostics() -> DiagnosticsResponseModel:
        return build_diagnostics_response(
            api_service.collect_startup_diagnostics(DiagnosticsMode.serve.value)
        )

    @_versioned_alias_route(
        app,
        "post",
        "/runtime/serving/initialize",
        response_model=OperationResponseModel,
    )
    def initialize_serving_runtime() -> OperationResponseModel:
        return build_operation_response(api_service.initialize_serving_runtime())

    @_versioned_alias_route(
        app,
        "post",
        "/runtime/serving/refresh",
        response_model=OperationResponseModel,
    )
    def refresh_serving_runtime() -> OperationResponseModel:
        return build_operation_response(api_service.refresh_serving_runtime())

    @app.post(
        "/answers",
        response_model=AnswerResponseModel,
        summary="Get one complete answer payload",
        description=(
            "Returns the full grounded answer as one JSON payload. "
            "The `stream=true` request flag is kept for compatibility and returns SSE, "
            "but new clients should use `/answers/stream` instead."
        ),
        responses={
            200: {"description": "Full answer payload or compatibility SSE stream."},
            409: {"description": "Serving runtime is initialized but artifacts are not ready."},
        },
    )
    def answer_question(payload: AnswerRequestModel) -> AnswerResponseModel | StreamingResponse:
        payload_data = payload.model_dump()
        if payload_data.get("stream", False):
            request_id = current_request_id()
            return build_sse_streaming_response(
                api_service.stream_answer_question_events(
                    question=payload.question,
                    explain_routing=payload.explain_routing,
                    request_id=request_id,
                )
            )
        return build_answer_response(
            api_service.answer_question(
                question=payload.question,
                stream=False,
                explain_routing=payload.explain_routing,
            )
        )

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
        payload_data = payload.model_dump()
        if payload_data.get("stream", False):
            request_id = current_request_id()
            return build_sse_streaming_response(
                api_service.stream_answer_question_events(
                    question=payload.question,
                    explain_routing=payload.explain_routing,
                    request_id=request_id,
                    include_traces=False,
                )
            )
        return build_public_answer_response(
            api_service.answer_question(
                question=payload.question,
                stream=False,
                explain_routing=payload.explain_routing,
            )
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
        payload_data = payload.model_dump()
        if payload_data.get("stream", False):
            request_id = current_request_id()
            return build_sse_streaming_response(
                api_service.stream_answer_question_events(
                    question=payload.question,
                    explain_routing=payload.explain_routing,
                    request_id=request_id,
                    include_traces=True,
                )
            )
        return build_answer_response(
            api_service.answer_question(
                question=payload.question,
                stream=False,
                explain_routing=payload.explain_routing,
            )
        )

    @app.post(
        "/answers/stream",
        summary="Stream answer events over SSE",
        description=(
            "Streams question-answering progress and output as Server-Sent Events. "
            "Events are emitted as `message`, `chunk`, `result`, and `done`."
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
    def stream_answer_question(payload: AnswerStreamRequestModel) -> StreamingResponse:
        request_id = current_request_id()
        return build_sse_streaming_response(
            api_service.stream_answer_question_events(
                question=payload.question,
                explain_routing=payload.explain_routing,
                request_id=request_id,
            )
        )

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
        request_id = current_request_id()
        return build_sse_streaming_response(
            api_service.stream_answer_question_events(
                question=payload.question,
                explain_routing=payload.explain_routing,
                request_id=request_id,
                include_traces=False,
            )
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
        request_id = current_request_id()
        return build_sse_streaming_response(
            api_service.stream_answer_question_events(
                question=payload.question,
                explain_routing=payload.explain_routing,
                request_id=request_id,
                include_traces=True,
            )
        )


def register_build_routes(app: FastAPI, api_service: GraphRAGBuildApiService) -> None:
    @app.get("/", response_model=HealthResponseModel)
    def read_root() -> dict[str, Any]:
        return api_service.health()

    @_versioned_alias_route(app, "get", "/health", response_model=HealthResponseModel)
    def read_health() -> dict[str, Any]:
        return api_service.health()

    @_versioned_alias_route(app, "get", "/health/live", response_model=HealthResponseModel)
    def read_liveness() -> dict[str, Any]:
        return api_service.health()

    @_versioned_alias_route(
        app,
        "get",
        "/health/ready",
        response_model=HealthResponseModel,
        responses={503: {"description": "Build runtime is not ready."}},
    )
    def read_readiness() -> JSONResponse:
        payload = api_service.readiness()
        return build_json_response(
            status_code=200 if payload["status"] == "ok" else 503,
            content=payload,
        )

    @_versioned_alias_route(app, "get", "/stats", response_model=StatsResponseModel)
    def read_stats() -> StatsResponseModel:
        return build_stats_response(api_service.collect_stats())

    @_versioned_alias_route(
        app,
        "get",
        "/diagnostics",
        response_model=DiagnosticsResponseModel,
    )
    def read_diagnostics() -> DiagnosticsResponseModel:
        return build_diagnostics_response(
            api_service.collect_startup_diagnostics(DiagnosticsMode.build.value)
        )

    @_versioned_alias_route(
        app,
        "post",
        "/runtime/build/initialize",
        response_model=OperationResponseModel,
    )
    def initialize_build_runtime() -> OperationResponseModel:
        return build_operation_response(api_service.initialize_build_runtime())

    @_versioned_alias_route(app, "get", "/jobs", response_model=BuildJobListResponseModel)
    def list_build_jobs(
        limit: int | None = Query(default=None, ge=1),
        cursor: str = Query(default=""),
    ) -> BuildJobListResponseModel:
        page = api_service.list_build_jobs(limit=limit, cursor=cursor)
        return build_build_job_list_response(page.jobs, next_cursor=page.next_cursor)

    @_versioned_alias_route(
        app,
        "get",
        "/artifacts",
        response_model=ArtifactRegistryResponseModel,
    )
    def read_artifact_registry() -> ArtifactRegistryResponseModel:
        return build_artifact_registry_response(api_service.artifact_registry_snapshot())

    @_versioned_alias_route(
        app,
        "get",
        "/jobs/{job_id}",
        response_model=BuildJobResponseModel,
    )
    def read_build_job(
        job_id: str = Path(pattern=r"^[0-9a-f]{32}$"),
    ) -> BuildJobResponseModel:
        return build_build_job_response(api_service.get_build_job(job_id))

    @_versioned_alias_route(
        app,
        "post",
        "/jobs/build",
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

    @_versioned_alias_route(
        app,
        "post",
        "/jobs/rebuild",
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

    @_versioned_alias_route(
        app,
        "post",
        "/knowledge-base/build",
        response_model=BuildJobResponseModel,
        status_code=202,
        summary="Queue a build job (compatibility alias)",
        description=(
            "Compatibility alias for `/jobs/build`. "
            "Queues an asynchronous knowledge-base build job instead of blocking until completion."
        ),
        responses={409: {"description": "Another build job is already in progress."}},
    )
    def build_knowledge_base(
        idempotency_key: str = Header(default="", alias="Idempotency-Key"),
    ) -> BuildJobResponseModel:
        return build_build_job_response(
            api_service.build_knowledge_base(
                rebuild=False,
                request_id=current_request_id(),
                idempotency_key=idempotency_key,
            )
        )

    @_versioned_alias_route(
        app,
        "post",
        "/knowledge-base/rebuild",
        response_model=BuildJobResponseModel,
        status_code=202,
        summary="Queue a rebuild job (compatibility alias)",
        description=(
            "Compatibility alias for `/jobs/rebuild`. "
            "Queues an asynchronous knowledge-base rebuild job instead of blocking until completion."
        ),
        responses={409: {"description": "Another build job is already in progress."}},
    )
    def rebuild_knowledge_base(
        idempotency_key: str = Header(default="", alias="Idempotency-Key"),
    ) -> BuildJobResponseModel:
        return build_build_job_response(
            api_service.build_knowledge_base(
                rebuild=True,
                request_id=current_request_id(),
                idempotency_key=idempotency_key,
            )
        )


__all__ = [
    "register_build_routes",
    "register_serving_routes",
]
