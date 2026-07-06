"""Small HTTP orchestration helpers for FastAPI route functions."""

from __future__ import annotations

from typing import Any, Literal, overload

from fastapi.responses import JSONResponse, StreamingResponse

from .answer_models import (
    AnswerRequestModel,
    AnswerResponseModel,
    AnswerStreamRequestModel,
    PublicAnswerResponseModel,
)
from .request_context import current_request_id
from .response_builder import (
    build_answer_response,
    build_json_response,
    build_public_answer_response,
    build_sse_streaming_response,
)
from .services import GraphRAGServingApiService


def build_readiness_response(payload: dict[str, Any]) -> JSONResponse:
    return build_json_response(
        status_code=200 if payload["status"] == "ok" else 503,
        content=payload,
    )


@overload
def build_answer_http_response(
    api_service: GraphRAGServingApiService,
    payload: AnswerRequestModel,
    *,
    include_traces: Literal[True],
) -> AnswerResponseModel | StreamingResponse: ...


@overload
def build_answer_http_response(
    api_service: GraphRAGServingApiService,
    payload: AnswerRequestModel,
    *,
    include_traces: Literal[False],
) -> PublicAnswerResponseModel | StreamingResponse: ...


@overload
def build_answer_http_response(
    api_service: GraphRAGServingApiService,
    payload: AnswerRequestModel,
    *,
    include_traces: bool,
) -> AnswerResponseModel | PublicAnswerResponseModel | StreamingResponse: ...


def build_answer_http_response(
    api_service: GraphRAGServingApiService,
    payload: AnswerRequestModel,
    *,
    include_traces: bool,
) -> AnswerResponseModel | PublicAnswerResponseModel | StreamingResponse:
    if payload.model_dump().get("stream", False):
        return build_answer_stream_http_response(
            api_service,
            payload,
            include_traces=include_traces,
        )
    response = api_service.answer_question(
        question=payload.question,
        stream=False,
        explain_routing=payload.explain_routing,
    )
    if include_traces:
        return build_answer_response(response)
    return build_public_answer_response(response)


def build_answer_stream_http_response(
    api_service: GraphRAGServingApiService,
    payload: AnswerRequestModel | AnswerStreamRequestModel,
    *,
    include_traces: bool,
) -> StreamingResponse:
    return build_sse_streaming_response(
        api_service.stream_answer_question_events(
            question=payload.question,
            explain_routing=payload.explain_routing,
            request_id=current_request_id(),
            include_traces=include_traces,
        )
    )


__all__ = [
    "build_answer_http_response",
    "build_answer_stream_http_response",
    "build_readiness_response",
]
