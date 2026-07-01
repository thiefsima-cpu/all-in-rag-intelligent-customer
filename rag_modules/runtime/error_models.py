"""Stable runtime error details for traces and fallback metadata."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from .json_types import JsonObject, coerce_json_object

ANSWER_FAILED = "ANSWER_FAILED"
QUERY_PROCESSING_FAILED = "QUERY_PROCESSING_FAILED"
GRAPH_OPERATION_FAILED = "GRAPH_OPERATION_FAILED"

GENERATION_PROVIDER_ERROR = "GENERATION_PROVIDER_ERROR"
GENERATION_PROVIDER_TIMEOUT = "GENERATION_PROVIDER_TIMEOUT"

CANDIDATE_SOURCE_ERROR_RETRIEVAL_FAILED = "CANDIDATE_SOURCE_RETRIEVAL_FAILED"
CANDIDATE_SOURCE_ERROR_CIRCUIT_OPEN = "CANDIDATE_SOURCE_CIRCUIT_OPEN"
CANDIDATE_SOURCE_ERROR_REQUEST_SKIPPED = "CANDIDATE_SOURCE_REQUEST_SKIPPED"
CANDIDATE_SOURCE_ERROR_DEGRADED = "CANDIDATE_SOURCE_DEGRADED"

_RETRIEVAL_REASON_DETAILS = {
    "exception": (
        CANDIDATE_SOURCE_ERROR_RETRIEVAL_FAILED,
        "candidate_source_retrieval_failed",
    ),
    "circuit_open": (
        CANDIDATE_SOURCE_ERROR_CIRCUIT_OPEN,
        "candidate_source_circuit_open",
    ),
    "request_skip": (
        CANDIDATE_SOURCE_ERROR_REQUEST_SKIPPED,
        "candidate_source_request_skipped",
    ),
}


@dataclass(frozen=True, slots=True)
class RuntimeErrorDetail:
    """Safe error detail carried by runtime traces and metadata."""

    code: str = ""
    detail: str = ""

    @classmethod
    def from_dict(cls, data: Mapping[str, object] | None) -> "RuntimeErrorDetail":
        payload = dict(data or {})
        return cls(
            code=_safe_token(payload.get("code")),
            detail=_safe_token(payload.get("detail")),
        )

    def to_dict(self) -> JsonObject:
        if not self:
            return {}
        return coerce_json_object({"code": self.code, "detail": self.detail})

    def __bool__(self) -> bool:
        return bool(self.code or self.detail)


def ensure_runtime_error_detail(value: object = None) -> RuntimeErrorDetail:
    if isinstance(value, RuntimeErrorDetail):
        return value
    if isinstance(value, Mapping):
        return RuntimeErrorDetail.from_dict(value)
    return RuntimeErrorDetail()


def runtime_error_detail(
    *,
    code: str,
    detail: str,
    error: BaseException | None = None,
) -> RuntimeErrorDetail:
    del error
    return RuntimeErrorDetail(code=_safe_token(code), detail=_safe_token(detail))


def answer_error_detail(error: BaseException | None = None) -> RuntimeErrorDetail:
    return runtime_error_detail(
        code=ANSWER_FAILED,
        detail="answer_failed",
        error=error,
    )


def routing_error_detail(error: BaseException | None = None) -> RuntimeErrorDetail:
    return runtime_error_detail(
        code=QUERY_PROCESSING_FAILED,
        detail="query_processing_failed",
        error=error,
    )


def graph_error_detail(
    error: BaseException | None = None,
    *,
    detail: str = "graph_operation_failed",
) -> RuntimeErrorDetail:
    return runtime_error_detail(
        code=GRAPH_OPERATION_FAILED,
        detail=detail,
        error=error,
    )


def retrieval_error_detail(
    reason: str,
    error: BaseException | None = None,
) -> RuntimeErrorDetail:
    del error
    code, detail = _RETRIEVAL_REASON_DETAILS.get(
        _safe_token(reason),
        (CANDIDATE_SOURCE_ERROR_DEGRADED, "candidate_source_degraded"),
    )
    return RuntimeErrorDetail(code=code, detail=detail)


def generation_error_detail(error: BaseException) -> RuntimeErrorDetail:
    explicit_detail = _safe_token(getattr(error, "failure_code", ""))
    if explicit_detail:
        return RuntimeErrorDetail(code=_detail_to_code(explicit_detail), detail=explicit_detail)
    if isinstance(error, TimeoutError) or "timeout" in type(error).__name__.lower():
        return RuntimeErrorDetail(
            code=GENERATION_PROVIDER_TIMEOUT,
            detail="generation_provider_timeout",
        )
    return RuntimeErrorDetail(
        code=GENERATION_PROVIDER_ERROR,
        detail="generation_provider_error",
    )


def _safe_token(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    normalized = []
    for char in text:
        if char.isalnum() or char in {"_", "-"}:
            normalized.append(char)
        elif char.isspace():
            normalized.append("_")
    return "".join(normalized)


def _detail_to_code(detail: str) -> str:
    return _safe_token(detail).upper()


__all__ = [
    "ANSWER_FAILED",
    "CANDIDATE_SOURCE_ERROR_CIRCUIT_OPEN",
    "CANDIDATE_SOURCE_ERROR_DEGRADED",
    "CANDIDATE_SOURCE_ERROR_REQUEST_SKIPPED",
    "CANDIDATE_SOURCE_ERROR_RETRIEVAL_FAILED",
    "GENERATION_PROVIDER_ERROR",
    "GENERATION_PROVIDER_TIMEOUT",
    "GRAPH_OPERATION_FAILED",
    "QUERY_PROCESSING_FAILED",
    "RuntimeErrorDetail",
    "answer_error_detail",
    "ensure_runtime_error_detail",
    "generation_error_detail",
    "graph_error_detail",
    "retrieval_error_detail",
    "routing_error_detail",
    "runtime_error_detail",
]
