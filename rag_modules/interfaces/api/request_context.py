"""Request correlation context for both API surfaces."""

from __future__ import annotations

import logging
import re
from contextvars import ContextVar
from uuid import uuid4

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from ...safe_logging import log_failure
from .error_models import ErrorCode, build_error_response

logger = logging.getLogger(__name__)

_REQUEST_ID_PATTERN = re.compile(r"[A-Za-z0-9._:-]{1,128}\Z", flags=re.ASCII)
_REQUEST_ID: ContextVar[str] = ContextVar("graph_rag_request_id", default="")


def normalize_or_generate_request_id(value: str = "") -> str:
    candidate = str(value or "")
    if _REQUEST_ID_PATTERN.fullmatch(candidate):
        return candidate
    return uuid4().hex


def current_request_id() -> str:
    return _REQUEST_ID.get()


def _incoming_request_id(scope: Scope) -> str:
    for key, value in scope.get("headers") or []:
        if key.lower() == b"x-request-id":
            return normalize_or_generate_request_id(value.decode("latin-1"))
    return normalize_or_generate_request_id()


class RequestContextMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        request_id = _incoming_request_id(scope)
        token = _REQUEST_ID.set(request_id)
        response_started = False

        async def send_with_request_id(message: Message) -> None:
            nonlocal response_started
            if message.get("type") == "http.response.start":
                response_started = True
                headers = list(message.get("headers") or [])
                headers = [item for item in headers if item[0].lower() != b"x-request-id"]
                headers.append((b"x-request-id", request_id.encode("ascii")))
                message = {**message, "headers": headers}
            await send(message)

        try:
            await self.app(scope, receive, send_with_request_id)
        except Exception as exc:
            log_failure(
                logger,
                logging.ERROR,
                "api_request_failed",
                code=ErrorCode.INTERNAL_ERROR.value,
                error=exc,
                request_id=request_id,
            )
            if response_started:
                raise
            response = build_error_response(
                ErrorCode.INTERNAL_ERROR,
                request_id=request_id,
            )
            await response(scope, receive, send_with_request_id)
        finally:
            _REQUEST_ID.reset(token)


__all__ = [
    "RequestContextMiddleware",
    "current_request_id",
    "normalize_or_generate_request_id",
]
