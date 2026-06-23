"""Authentication and request-size enforcement for HTTP API surfaces."""

from __future__ import annotations

import hmac
import json
from typing import Any, Dict

from ...configuration.models import ApiSettings, ObservabilitySettings

_BASE_PUBLIC_PATHS = frozenset({"/", "/health", "/health/live", "/health/ready"})
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
                status_code, message = auth_error
                await self._send_json(
                    send,
                    status_code=status_code,
                    payload={"ok": False, "message": message},
                    authenticate=status_code == 401,
                )
                return

        if str(scope.get("method") or "").upper() in _BODY_METHODS:
            buffered = await self._buffer_request_body(scope, receive, send)
            if buffered is None:
                return
            receive = buffered

        await self.app(scope, receive, send)

    def _authentication_error(self, scope) -> tuple[int, str] | None:
        if not self.settings.auth_enabled:
            return None
        expected = str(self.settings.access_token or "")
        if not expected:
            return 503, "API authentication is enabled but no access token is configured."
        if len(expected) < 16:
            return 503, "API access token must contain at least 16 characters."

        headers = self._headers(scope)
        authorization = headers.get("authorization", "")
        bearer = ""
        if authorization.lower().startswith("bearer "):
            bearer = authorization[7:].strip()
        api_key = headers.get("x-api-key", "").strip()
        provided = bearer or api_key
        if not provided or not hmac.compare_digest(provided, expected):
            return 401, "Invalid or missing API credentials."
        return None

    async def _buffer_request_body(self, scope, receive, send):
        max_bytes = int(self.settings.max_request_body_bytes)
        headers = self._headers(scope)
        content_length = headers.get("content-length")
        if content_length:
            try:
                if int(content_length) > max_bytes:
                    await self._request_too_large(send, max_bytes)
                    return None
            except ValueError:
                await self._send_json(
                    send,
                    status_code=400,
                    payload={"ok": False, "message": "Invalid Content-Length header."},
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
                await self._request_too_large(send, max_bytes)
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

    async def _request_too_large(self, send, max_bytes: int) -> None:
        await self._send_json(
            send,
            status_code=413,
            payload={
                "ok": False,
                "message": f"Request body exceeds the {max_bytes}-byte limit.",
            },
        )

    @staticmethod
    async def _send_json(
        send,
        *,
        status_code: int,
        payload: Dict[str, Any],
        authenticate: bool = False,
    ) -> None:
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
                "status": status_code,
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
