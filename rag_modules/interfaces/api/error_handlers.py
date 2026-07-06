"""FastAPI exception mappings for the stable public error contract."""

from __future__ import annotations

from typing import cast

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import JsonValue
from starlette.exceptions import HTTPException as StarletteHTTPException

from .error_models import ErrorCode, build_error_response
from .request_context import current_request_id
from .services import (
    AnswerFailedError,
    ApiBackpressureError,
    BuildJobConflictError,
    BuildJobNotFoundError,
    InvalidApiRequestError,
    SystemNotReadyError,
)


def _validation_details(exc: RequestValidationError) -> list[dict[str, str]]:
    details: list[dict[str, str]] = []
    for item in exc.errors():
        location = ".".join(str(part) for part in item.get("loc") or ())
        details.append(
            {
                "field": location,
                "reason": str(item.get("type") or "invalid"),
            }
        )
    return details


def register_api_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(SystemNotReadyError)
    async def system_not_ready(_: Request, __: SystemNotReadyError) -> JSONResponse:
        return build_error_response(
            ErrorCode.SYSTEM_NOT_READY,
            request_id=current_request_id(),
        )

    @app.exception_handler(BuildJobNotFoundError)
    async def build_job_not_found(_: Request, __: BuildJobNotFoundError) -> JSONResponse:
        return build_error_response(
            ErrorCode.NOT_FOUND,
            request_id=current_request_id(),
        )

    @app.exception_handler(BuildJobConflictError)
    async def build_job_conflict(_: Request, exc: BuildJobConflictError) -> JSONResponse:
        details = {
            "job_id": str(exc.job.get("job_id") or ""),
            "status": str(exc.job.get("status") or ""),
        }
        if exc.job.get("job_type"):
            details["job_type"] = str(exc.job.get("job_type") or "")
        return build_error_response(
            ErrorCode.BUILD_JOB_CONFLICT,
            request_id=current_request_id(),
            details=cast(JsonValue, details),
        )

    @app.exception_handler(InvalidApiRequestError)
    async def invalid_api_request(_: Request, exc: InvalidApiRequestError) -> JSONResponse:
        return build_error_response(
            ErrorCode.INVALID_REQUEST,
            request_id=current_request_id(),
            details=cast(JsonValue, exc.details),
        )

    @app.exception_handler(ApiBackpressureError)
    async def api_backpressure(_: Request, __: ApiBackpressureError) -> JSONResponse:
        return build_error_response(
            ErrorCode.RATE_LIMITED,
            request_id=current_request_id(),
        )

    @app.exception_handler(AnswerFailedError)
    async def answer_failed(_: Request, __: AnswerFailedError) -> JSONResponse:
        return build_error_response(
            ErrorCode.ANSWER_FAILED,
            request_id=current_request_id(),
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        return build_error_response(
            ErrorCode.VALIDATION_ERROR,
            request_id=current_request_id(),
            details=cast(JsonValue, _validation_details(exc)),
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_error(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = {
            404: ErrorCode.NOT_FOUND,
            405: ErrorCode.METHOD_NOT_ALLOWED,
        }.get(exc.status_code, ErrorCode.INVALID_REQUEST)
        return build_error_response(code, request_id=current_request_id())


__all__ = ["register_api_error_handlers"]
