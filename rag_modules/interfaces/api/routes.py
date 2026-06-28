"""Route registration helpers for serving and build API surfaces."""

from __future__ import annotations

from fastapi import FastAPI, Path
from fastapi.responses import StreamingResponse

from .answer_models import (
    AnswerRequestModel,
    AnswerResponseModel,
    AnswerStreamRequestModel,
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
    build_sse_streaming_response,
    build_stats_response,
)
from .services import (
    GraphRAGBuildApiService,
    GraphRAGServingApiService,
)

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
    @app.get("/", response_model=HealthResponseModel)
    def read_root():
        return api_service.health()

    @app.get("/health", response_model=HealthResponseModel)
    def read_health():
        return api_service.health()

    @app.get("/health/live", response_model=HealthResponseModel)
    def read_liveness():
        return api_service.health()

    @app.get(
        "/health/ready",
        response_model=HealthResponseModel,
        responses={503: {"description": "Serving runtime is not ready."}},
    )
    def read_readiness():
        payload = api_service.readiness()
        return build_json_response(
            status_code=200 if payload["status"] == "ok" else 503,
            content=payload,
        )

    @app.get("/stats", response_model=StatsResponseModel)
    def read_stats():
        return build_stats_response(api_service.collect_stats())

    @app.get("/diagnostics", response_model=DiagnosticsResponseModel)
    def read_diagnostics():
        return build_diagnostics_response(
            api_service.collect_startup_diagnostics(DiagnosticsMode.serve.value)
        )

    @app.post("/runtime/serving/initialize", response_model=OperationResponseModel)
    def initialize_serving_runtime():
        return api_service.initialize_serving_runtime()

    @app.post("/runtime/serving/refresh", response_model=OperationResponseModel)
    def refresh_serving_runtime():
        return api_service.refresh_serving_runtime()

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
    def answer_question(payload: AnswerRequestModel):
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
    def stream_answer_question(payload: AnswerStreamRequestModel):
        request_id = current_request_id()
        return build_sse_streaming_response(
            api_service.stream_answer_question_events(
                question=payload.question,
                explain_routing=payload.explain_routing,
                request_id=request_id,
            )
        )


def register_build_routes(app: FastAPI, api_service: GraphRAGBuildApiService) -> None:
    @app.get("/", response_model=HealthResponseModel)
    def read_root():
        return api_service.health()

    @app.get("/health", response_model=HealthResponseModel)
    def read_health():
        return api_service.health()

    @app.get("/health/live", response_model=HealthResponseModel)
    def read_liveness():
        return api_service.health()

    @app.get(
        "/health/ready",
        response_model=HealthResponseModel,
        responses={503: {"description": "Build runtime is not ready."}},
    )
    def read_readiness():
        payload = api_service.readiness()
        return build_json_response(
            status_code=200 if payload["status"] == "ok" else 503,
            content=payload,
        )

    @app.get("/stats", response_model=StatsResponseModel)
    def read_stats():
        return build_stats_response(api_service.collect_stats())

    @app.get("/diagnostics", response_model=DiagnosticsResponseModel)
    def read_diagnostics():
        return build_diagnostics_response(
            api_service.collect_startup_diagnostics(DiagnosticsMode.build.value)
        )

    @app.post("/runtime/build/initialize", response_model=OperationResponseModel)
    def initialize_build_runtime():
        return api_service.initialize_build_runtime()

    @app.get("/jobs", response_model=BuildJobListResponseModel)
    def list_build_jobs():
        return build_build_job_list_response(api_service.list_build_jobs())

    @app.get("/artifacts", response_model=ArtifactRegistryResponseModel)
    def read_artifact_registry():
        return build_artifact_registry_response(api_service.artifact_registry_snapshot())

    @app.get("/jobs/{job_id}", response_model=BuildJobResponseModel)
    def read_build_job(
        job_id: str = Path(pattern=r"^[0-9a-f]{32}$"),
    ):
        return build_build_job_response(api_service.get_build_job(job_id))

    @app.post(
        "/jobs/build",
        response_model=BuildJobResponseModel,
        status_code=202,
        summary="Queue a build job",
        description="Queues an asynchronous knowledge-base build job and returns a job identifier.",
        responses={409: {"description": "Another build job is already in progress."}},
    )
    def queue_build_job():
        return build_build_job_response(
            api_service.submit_build_job(
                rebuild=False,
                request_id=current_request_id(),
            )
        )

    @app.post(
        "/jobs/rebuild",
        response_model=BuildJobResponseModel,
        status_code=202,
        summary="Queue a rebuild job",
        description="Queues an asynchronous knowledge-base rebuild job and returns a job identifier.",
        responses={409: {"description": "Another build job is already in progress."}},
    )
    def queue_rebuild_job():
        return build_build_job_response(
            api_service.submit_build_job(
                rebuild=True,
                request_id=current_request_id(),
            )
        )

    @app.post(
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
    def build_knowledge_base():
        return build_build_job_response(
            api_service.build_knowledge_base(
                rebuild=False,
                request_id=current_request_id(),
            )
        )

    @app.post(
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
    def rebuild_knowledge_base():
        return build_build_job_response(
            api_service.build_knowledge_base(
                rebuild=True,
                request_id=current_request_id(),
            )
        )


__all__ = [
    "register_build_routes",
    "register_serving_routes",
]
