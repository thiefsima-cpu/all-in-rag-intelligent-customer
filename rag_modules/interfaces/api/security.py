"""Authentication and request-size enforcement for HTTP API surfaces."""

from __future__ import annotations

import hmac
import json
from typing import Any, Dict

from ...configuration.models import ApiSettings, ObservabilitySettings
from .error_models import ERROR_STATUS_CODES, ErrorCode, build_error_payload
from .request_context import current_request_id
from .versioning import API_PREFIX

_BASE_PUBLIC_PATHS = frozenset(
    {
        "/",
        "/health",
        "/health/live",
        "/health/ready",
        f"{API_PREFIX}/health",
        f"{API_PREFIX}/health/live",
        f"{API_PREFIX}/health/ready",
    }
)
_DOCS_PATHS = frozenset({"/docs", "/docs/oauth2-redirect", "/redoc"})
_BODY_METHODS = frozenset({"POST", "PUT", "PATCH"})


def public_paths_for_settings(
    *,
    api_settings: ApiSettings,
    observability_settings: ObservabilitySettings | None = None,
) -> frozenset[str]:
    """Return registered paths that are intentionally anonymous."""

    paths = set(_BASE_PUBLIC_PATHS)
    if api_settings.docs_enabled and api_settings.docs_public:
        paths.update(_DOCS_PATHS)
    if api_settings.openapi_enabled and api_settings.openapi_public:
        paths.add("/openapi.json")
    if getattr(observability_settings, "enable_prometheus", False) and getattr(
        observability_settings,
        "prometheus_public",
        False,
    ):
        paths.add("/metrics")
    return frozenset(paths)


def unauthenticated_passthrough_paths_for_settings(
    *,
    api_settings: ApiSettings,
    observability_settings: ObservabilitySettings | None = None,
) -> frozenset[str]:
    """Return anonymous paths, including disabled management routes that should 404."""

    paths = set(
        public_paths_for_settings(
            api_settings=api_settings,
            observability_settings=observability_settings,
        )
    )
    if not api_settings.docs_enabled:
        paths.update(_DOCS_PATHS)
    if not api_settings.openapi_enabled:
        paths.add("/openapi.json")
    if not getattr(observability_settings, "enable_prometheus", False):
        paths.add("/metrics")
    return frozenset(paths)


class ApiSecurityMiddleware:
    """Fail-closed API token authentication plus bounded request buffering."""

    def __init__(
        self,
        app,
        *,
        settings: ApiSettings,
        observability_settings: ObservabilitySettings | None = None,
    ) -> None:
        self.app = app
        self.settings = settings
        self.unauthenticated_paths = unauthenticated_passthrough_paths_for_settings(
            api_settings=settings,
            observability_settings=observability_settings,
        )

    async def __call__(self, scope, receive, send) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        path = str(scope.get("path") or "")
        if path not in self.unauthenticated_paths:
            auth_error = self._authentication_error(scope)
            if auth_error is not None:
                await self._send_error(
                    send,
                    code=auth_error,
                    authenticate=auth_error is ErrorCode.UNAUTHORIZED,
                )
                return

        if str(scope.get("method") or "").upper() in _BODY_METHODS:
            buffered = await self._buffer_request_body(scope, receive, send)
            if buffered is None:
                return
            receive = buffered

        await self.app(scope, receive, send)

    def _authentication_error(self, scope) -> ErrorCode | None:
        if not self.settings.auth_enabled:
            return None
        expected = str(self.settings.access_token or "")
        if not expected or len(expected) < 16:
            return ErrorCode.SERVICE_MISCONFIGURED

        headers = self._headers(scope)
        authorization = headers.get("authorization", "")
        bearer = authorization[7:].strip() if authorization.lower().startswith("bearer ") else ""
        provided = bearer or headers.get("x-api-key", "").strip()
        if not provided or not hmac.compare_digest(provided, expected):
            return ErrorCode.UNAUTHORIZED
        return None

    async def _buffer_request_body(self, scope, receive, send):
        max_bytes = int(self.settings.max_request_body_bytes)
        headers = self._headers(scope)
        content_length = headers.get("content-length")
        if content_length:
            try:
                if int(content_length) > max_bytes:
                    await self._send_error(
                        send,
                        code=ErrorCode.REQUEST_TOO_LARGE,
                        details={"max_bytes": max_bytes},
                    )
                    return None
            except ValueError:
                await self._send_error(
                    send,
                    code=ErrorCode.INVALID_REQUEST,
                )
                return None

        messages = []
        total = 0
        while True:
            message = await receive()
            messages.append(message)
            if message.get("type") == "http.disconnect":
                break
            if message.get("type") != "http.request":
                continue
            total += len(message.get("body") or b"")
            if total > max_bytes:
                await self._send_error(
                    send,
                    code=ErrorCode.REQUEST_TOO_LARGE,
                    details={"max_bytes": max_bytes},
                )
                return None
            if not message.get("more_body", False):
                break

        async def replay():
            if messages:
                return messages.pop(0)
            return await receive()

        return replay

    @staticmethod
    def _headers(scope) -> Dict[str, str]:
        return {
            key.decode("latin-1").lower(): value.decode("latin-1")
            for key, value in scope.get("headers") or []
        }

    @staticmethod
    async def _send_error(
        send,
        *,
        code: ErrorCode,
        details: Dict[str, Any] | None = None,
        authenticate: bool = False,
    ) -> None:
        payload = build_error_payload(
            code,
            request_id=current_request_id(),
            details=details,
        )
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers = [
            (b"content-type", b"application/json; charset=utf-8"),
            (b"content-length", str(len(body)).encode("ascii")),
        ]
        if authenticate:
            headers.append((b"www-authenticate", b"Bearer"))
        await send(
            {
                "type": "http.response.start",
                "status": ERROR_STATUS_CODES[code],
                "headers": headers,
            }
        )
        await send({"type": "http.response.body", "body": body})


def configure_openapi_security(
    app,
    *,
    api_settings: ApiSettings,
    observability_settings: ObservabilitySettings | None = None,
) -> None:
    original_openapi = app.openapi
    public_paths = public_paths_for_settings(
        api_settings=api_settings,
        observability_settings=observability_settings,
    )

    def secured_openapi():
        if app.openapi_schema is not None:
            return app.openapi_schema
        schema = original_openapi()
        schemes = schema.setdefault("components", {}).setdefault("securitySchemes", {})
        schemes["BearerAuth"] = {
            "type": "http",
            "scheme": "bearer",
        }
        schemes["ApiKeyAuth"] = {
            "type": "apiKey",
            "in": "header",
            "name": "X-API-Key",
        }
        schema["security"] = [{"BearerAuth": []}, {"ApiKeyAuth": []}]
        for path in public_paths:
            for operation in (schema.get("paths", {}).get(path) or {}).values():
                if isinstance(operation, dict):
                    operation["security"] = []
        app.openapi_schema = schema
        return schema

    app.openapi = secured_openapi


__all__ = [
    "ApiSecurityMiddleware",
    "configure_openapi_security",
    "public_paths_for_settings",
]
