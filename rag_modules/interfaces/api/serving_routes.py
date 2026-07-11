"""Serving route registration helpers."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.responses import StreamingResponse

from .answer_models import (
    AnswerRequestModel,
    AnswerResponseModel,
    AnswerStreamRequestModel,
    PublicAnswerResponseModel,
)
from .operational_routes import register_serving_operational_routes
from .route_handlers import (
    build_answer_http_response,
    build_answer_stream_http_response,
)
from .services import GraphRAGServingApiService
from .versioning import API_PREFIX

_SSE_EXAMPLE = (
    "event: message\n"
    'data: {"message":"progress message"}\n\n'
    "event: chunk\n"
    'data: {"content":"first token"}\n\n'
    "event: result\n"
    'data: {"response":{"summary":{"answer":"..."}}}\n\n'
    "event: done\n"
    'data: {"ok":true}\n\n'
)


def register_serving_routes(app: FastAPI, api_service: GraphRAGServingApiService) -> None:
    register_serving_operational_routes(app, api_service)
    _register_serving_answer_request_routes(app, api_service)
    _register_serving_answer_stream_routes(app, api_service)


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


__all__ = [
    "register_serving_routes",
]
