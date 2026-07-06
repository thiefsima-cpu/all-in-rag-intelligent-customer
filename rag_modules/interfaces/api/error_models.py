"""Stable public API errors and privacy-safe payload helpers."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from enum import Enum
from typing import Any

from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, JsonValue


class ErrorCode(str, Enum):
    INVALID_REQUEST = "INVALID_REQUEST"
    UNAUTHORIZED = "UNAUTHORIZED"
    NOT_FOUND = "NOT_FOUND"
    METHOD_NOT_ALLOWED = "METHOD_NOT_ALLOWED"
    SYSTEM_NOT_READY = "SYSTEM_NOT_READY"
    BUILD_JOB_CONFLICT = "BUILD_JOB_CONFLICT"
    REQUEST_TOO_LARGE = "REQUEST_TOO_LARGE"
    VALIDATION_ERROR = "VALIDATION_ERROR"
    RATE_LIMITED = "RATE_LIMITED"
    ANSWER_FAILED = "ANSWER_FAILED"
    BUILD_FAILED = "BUILD_FAILED"
    INTERNAL_ERROR = "INTERNAL_ERROR"
    SERVICE_MISCONFIGURED = "SERVICE_MISCONFIGURED"
    SERVICE_UNAVAILABLE = "SERVICE_UNAVAILABLE"


ERROR_MESSAGES: dict[ErrorCode, str] = {
    ErrorCode.INVALID_REQUEST: "The request is invalid.",
    ErrorCode.UNAUTHORIZED: "Authentication is required or the credentials are invalid.",
    ErrorCode.NOT_FOUND: "The requested resource was not found.",
    ErrorCode.METHOD_NOT_ALLOWED: "The request method is not allowed for this resource.",
    ErrorCode.SYSTEM_NOT_READY: "The serving system is not ready.",
    ErrorCode.BUILD_JOB_CONFLICT: "Another build job is already in progress.",
    ErrorCode.REQUEST_TOO_LARGE: "The request body is too large.",
    ErrorCode.VALIDATION_ERROR: "The request is invalid.",
    ErrorCode.RATE_LIMITED: "The service is currently at its answer concurrency limit.",
    ErrorCode.ANSWER_FAILED: "The answer could not be generated.",
    ErrorCode.BUILD_FAILED: "The knowledge-base build failed.",
    ErrorCode.INTERNAL_ERROR: "An unexpected internal error occurred.",
    ErrorCode.SERVICE_MISCONFIGURED: "The service is not configured correctly.",
    ErrorCode.SERVICE_UNAVAILABLE: "A required service is unavailable.",
}

ERROR_STATUS_CODES: dict[ErrorCode, int] = {
    ErrorCode.INVALID_REQUEST: 400,
    ErrorCode.UNAUTHORIZED: 401,
    ErrorCode.NOT_FOUND: 404,
    ErrorCode.METHOD_NOT_ALLOWED: 405,
    ErrorCode.SYSTEM_NOT_READY: 409,
    ErrorCode.BUILD_JOB_CONFLICT: 409,
    ErrorCode.REQUEST_TOO_LARGE: 413,
    ErrorCode.VALIDATION_ERROR: 422,
    ErrorCode.RATE_LIMITED: 429,
    ErrorCode.ANSWER_FAILED: 500,
    ErrorCode.INTERNAL_ERROR: 500,
    ErrorCode.SERVICE_MISCONFIGURED: 503,
    ErrorCode.SERVICE_UNAVAILABLE: 503,
}


class ErrorInfoModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: ErrorCode
    message: str
    details: JsonValue | None = None


class ErrorResponseModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ok: bool = False
    error: ErrorInfoModel
    request_id: str


def build_error_model(
    code: ErrorCode,
    *,
    request_id: str,
    details: JsonValue | None = None,
) -> ErrorResponseModel:
    return ErrorResponseModel(
        error=ErrorInfoModel(code=code, message=ERROR_MESSAGES[code], details=details),
        request_id=request_id,
    )


def build_error_payload(
    code: ErrorCode,
    *,
    request_id: str,
    details: JsonValue | None = None,
) -> dict[str, Any]:
    return build_error_model(code, request_id=request_id, details=details).model_dump(
        mode="json",
        exclude_none=True,
    )


def build_error_response(
    code: ErrorCode,
    *,
    request_id: str,
    details: JsonValue | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    return JSONResponse(
        status_code=ERROR_STATUS_CODES[code],
        content=build_error_payload(code, request_id=request_id, details=details),
        headers=headers,
    )


def error_response_openapi() -> dict[int | str, dict[str, Any]]:
    descriptions = {
        400: "Invalid request.",
        401: "Authentication failed.",
        404: "Resource not found.",
        405: "Method not allowed.",
        409: "Request conflicts with current runtime state.",
        413: "Request body too large.",
        422: "Request validation failed.",
        429: "Request admission limit reached.",
        500: "Internal request failure.",
        503: "Service unavailable or misconfigured.",
    }
    return {
        status: {"model": ErrorResponseModel, "description": description}
        for status, description in descriptions.items()
    }


_PUBLIC_ERROR_KEYS = frozenset({"error", "last_error"})


def _is_public_error_key(key: str) -> bool:
    normalized = str(key or "").strip().lower().replace("-", "_")
    return normalized in _PUBLIC_ERROR_KEYS or normalized.endswith(("_error", "_exception"))


def sanitize_public_error_fields(value: Any, *, code: ErrorCode) -> Any:
    if isinstance(value, Mapping):
        sanitized: dict[str, Any] = {}
        for raw_key, item in value.items():
            key = str(raw_key)
            if _is_public_error_key(key) and item not in (None, "", {}, []):
                if isinstance(item, Mapping) and {"code", "message"}.issubset(item):
                    sanitized[key] = sanitize_public_error_fields(item, code=code)
                else:
                    sanitized[key] = code.value
                continue
            sanitized[key] = sanitize_public_error_fields(item, code=code)
        return sanitized
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [sanitize_public_error_fields(item, code=code) for item in value]
    return value
