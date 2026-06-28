# Error and Privacy Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give every HTTP and SSE failure a stable error code and request ID while preventing raw exceptions, queries, tokenized content, and secrets from entering public responses, build-job state, telemetry, or logs.

**Architecture:** Add one typed API error catalog and an outer request-context ASGI middleware, then adapt FastAPI handlers, security, answer streaming, build jobs, and response builders to that policy. Keep runtime subsystems intact, but replace content-bearing log calls with event/count metadata and route all exception logging through a narrow safe helper.

**Tech Stack:** Python 3.11, FastAPI/Starlette ASGI, Pydantic v2, `contextvars`, `unittest`/pytest, OpenTelemetry, Ruff, pre-commit.

---

## File Structure

- Create `rag_modules/interfaces/api/error_models.py` for error codes, messages, typed payloads,
  public error-field sanitization, and OpenAPI response metadata.
- Create `rag_modules/interfaces/api/request_context.py` for request ID validation, context
  propagation, response-header injection, and the final unknown-exception guard.
- Create `rag_modules/interfaces/api/error_handlers.py` for FastAPI exception-to-code mappings and
  validation issue normalization.
- Create `rag_modules/safe_logging.py` for privacy-safe failure log records.
- Create `tests/test_safe_logging.py` for runtime sentinel checks and the static logger-call policy.
- Modify API models, routes, services, response builders, and build-job persistence only where they
  cross a public or persistent boundary.
- Modify existing subsystem logger call sites without changing their retrieval, graph, generation,
  or build behavior.

### Task 1: Typed Error Catalog and Request Context

**Files:**
- Create: `rag_modules/interfaces/api/error_models.py`
- Create: `rag_modules/interfaces/api/request_context.py`
- Modify: `rag_modules/interfaces/api/app.py`
- Test: `tests/test_api_app.py`

- [ ] **Step 1: Write failing tests for the catalog and request ID policy**

Add imports and these tests to `tests/test_api_app.py`:

```python
import re

from rag_modules.interfaces.api.error_models import ErrorCode, build_error_payload


def _assert_request_id(value: str) -> None:
    assert re.fullmatch(r"[A-Za-z0-9._:-]{1,128}", value)


class ApiAppTests(unittest.TestCase):
    def test_error_catalog_builds_the_new_breaking_contract(self) -> None:
        payload = build_error_payload(
            ErrorCode.VALIDATION_ERROR,
            request_id="catalog-test",
            details=[{"field": "body.question", "reason": "string_too_long"}],
        )

        self.assertEqual(
            payload,
            {
                "ok": False,
                "error": {
                    "code": "VALIDATION_ERROR",
                    "message": "The request is invalid.",
                    "details": [
                        {"field": "body.question", "reason": "string_too_long"}
                    ],
                },
                "request_id": "catalog-test",
            },
        )

    def test_valid_client_request_id_is_preserved_on_success(self) -> None:
        app = create_serving_api_app(system=_FakeApiSystem())

        with TestClient(app) as client:
            response = client.get("/health", headers={"X-Request-ID": "client.req:42"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["x-request-id"], "client.req:42")

    def test_missing_or_invalid_request_id_is_replaced(self) -> None:
        app = create_serving_api_app(system=_FakeApiSystem())

        with TestClient(app) as client:
            missing = client.get("/health")
            invalid = client.get("/health", headers={"X-Request-ID": "bad/id secret"})

        _assert_request_id(missing.headers["x-request-id"])
        _assert_request_id(invalid.headers["x-request-id"])
        self.assertNotEqual(invalid.headers["x-request-id"], "bad/id secret")
```

- [ ] **Step 2: Run the focused tests and verify RED**

Run:

```powershell
python -m pytest tests/test_api_app.py -q -k "error_catalog or request_id"
```

Expected: collection fails because `rag_modules.interfaces.api.error_models` does not exist.

- [ ] **Step 3: Implement the typed error catalog**

Create `rag_modules/interfaces/api/error_models.py`:

```python
"""Stable public API errors and privacy-safe payload helpers."""

from __future__ import annotations

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
```

Leave the public-payload sanitizer and OpenAPI helper for Tasks 2 and 5 so this first cycle remains
focused.

- [ ] **Step 4: Implement request context and outer error guard**

Create `rag_modules/interfaces/api/request_context.py`:

```python
"""Request correlation context for both API surfaces."""

from __future__ import annotations

import re
from contextvars import ContextVar
from uuid import uuid4

from .error_models import ErrorCode, build_error_response

_REQUEST_ID_PATTERN = re.compile(r"[A-Za-z0-9._:-]{1,128}\Z", flags=re.ASCII)
_REQUEST_ID: ContextVar[str] = ContextVar("graph_rag_request_id", default="")


def normalize_or_generate_request_id(value: str = "") -> str:
    candidate = str(value or "")
    if _REQUEST_ID_PATTERN.fullmatch(candidate):
        return candidate
    return uuid4().hex


def current_request_id() -> str:
    return _REQUEST_ID.get()


def _incoming_request_id(scope) -> str:
    for key, value in scope.get("headers") or []:
        if key.lower() == b"x-request-id":
            return normalize_or_generate_request_id(value.decode("latin-1"))
    return normalize_or_generate_request_id()


class RequestContextMiddleware:
    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        request_id = _incoming_request_id(scope)
        token = _REQUEST_ID.set(request_id)
        response_started = False

        async def send_with_request_id(message) -> None:
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
        except Exception:
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
```

In each app factory in `rag_modules/interfaces/api/app.py`, add the request middleware after the
security middleware so Starlette makes it the outer user middleware:

```python
from .request_context import RequestContextMiddleware

# Existing ApiSecurityMiddleware registration remains first.
app.add_middleware(RequestContextMiddleware)
```

- [ ] **Step 5: Run the focused tests and verify GREEN**

Run:

```powershell
python -m pytest tests/test_api_app.py -q -k "error_catalog or request_id"
```

Expected: all selected tests pass.

- [ ] **Step 6: Commit the foundation**

```powershell
git add rag_modules/interfaces/api/error_models.py rag_modules/interfaces/api/request_context.py rag_modules/interfaces/api/app.py tests/test_api_app.py
git commit -m "feat: add typed API errors and request context"
```

### Task 2: Unified HTTP Handlers, Security Errors, and OpenAPI

**Files:**
- Create: `rag_modules/interfaces/api/error_handlers.py`
- Modify: `rag_modules/interfaces/api/error_models.py`
- Modify: `rag_modules/interfaces/api/security.py`
- Modify: `rag_modules/interfaces/api/routes.py`
- Modify: `rag_modules/interfaces/api/app.py`
- Test: `tests/test_api_app.py`

- [ ] **Step 1: Replace existing error assertions and add privacy regressions**

Add this helper near `_client` in `tests/test_api_app.py` and update the existing 409, 429, auth,
and request-limit assertions to use it:

```python
def _assert_error_response(
    response,
    *,
    status_code: int,
    code: str,
    request_id: str | None = None,
) -> dict:
    assert response.status_code == status_code
    payload = response.json()
    assert payload["ok"] is False
    assert payload["error"]["code"] == code
    assert "message" in payload["error"]
    assert "message" not in {key for key in payload if key != "error"}
    assert "error_type" not in payload
    assert payload["request_id"] == response.headers["x-request-id"]
    if request_id is not None:
        assert payload["request_id"] == request_id
    return payload
```

Add focused tests:

```python
def test_validation_error_does_not_echo_request_input(self) -> None:
    secret_question = "PRIVATE-QUESTION-" + "x" * MAX_QUESTION_CHARS
    app = create_serving_api_app(system=_FakeApiSystem())

    with _client(app) as client:
        response = client.post(
            "/answers",
            json={"question": secret_question},
            headers={"X-Request-ID": "validation-42"},
        )

    payload = _assert_error_response(
        response,
        status_code=422,
        code="VALIDATION_ERROR",
        request_id="validation-42",
    )
    self.assertNotIn(secret_question, json.dumps(payload, ensure_ascii=False))
    self.assertEqual(
        payload["error"]["details"],
        [{"field": "body.question", "reason": "string_too_long"}],
    )

def test_unknown_exception_returns_internal_error_without_raw_text(self) -> None:
    secret = "provider-secret-error-body"
    app = create_serving_api_app(system=_FakeApiSystem())

    @app.get("/_test/boom")
    def boom():
        raise RuntimeError(secret)

    with _client(app) as client:
        response = client.get("/_test/boom", headers={"X-Request-ID": "boom-42"})

    payload = _assert_error_response(
        response,
        status_code=500,
        code="INTERNAL_ERROR",
        request_id="boom-42",
    )
    self.assertNotIn(secret, json.dumps(payload))
    self.assertNotIn("RuntimeError", json.dumps(payload))

def test_not_found_and_method_not_allowed_use_the_common_contract(self) -> None:
    app = create_serving_api_app(system=_FakeApiSystem())

    with _client(app) as client:
        missing = client.get("/does-not-exist")
        method = client.put("/health")

    _assert_error_response(missing, status_code=404, code="NOT_FOUND")
    _assert_error_response(method, status_code=405, code="METHOD_NOT_ALLOWED")

def test_openapi_uses_the_common_error_schema(self) -> None:
    config = build_test_config(
        {"api": {"access_token": _API_TOKEN, "openapi_enabled": True}}
    )
    app = create_serving_api_app(system=_FakeApiSystem(), config=config)

    with _client(app) as client:
        schema = client.get("/openapi.json").json()

    self.assertIn("ErrorResponseModel", schema["components"]["schemas"])
    validation_schema = schema["paths"]["/answers"]["post"]["responses"]["422"]
    self.assertEqual(
        validation_schema["content"]["application/json"]["schema"]["$ref"],
        "#/components/schemas/ErrorResponseModel",
    )
```

Update the existing auth/body/not-ready/backpressure tests to expect these mappings:

```python
_assert_error_response(response, status_code=401, code="UNAUTHORIZED")
_assert_error_response(response, status_code=503, code="SERVICE_MISCONFIGURED")
_assert_error_response(response, status_code=413, code="REQUEST_TOO_LARGE")
_assert_error_response(response, status_code=409, code="SYSTEM_NOT_READY")
_assert_error_response(response, status_code=429, code="RATE_LIMITED")
```

- [ ] **Step 2: Run the HTTP error tests and verify RED**

Run:

```powershell
python -m pytest tests/test_api_app.py -q -k "validation_error or unknown_exception or not_found_and_method or protected_routes or authentication or request_body or not_ready or admission_limit or openapi_uses"
```

Expected: failures show legacy `detail`, `message`, and `error_type` shapes and the missing common
OpenAPI schema.

- [ ] **Step 3: Add the OpenAPI error response metadata**

Append to `rag_modules/interfaces/api/error_models.py`:

```python
def error_response_openapi() -> dict[int, dict[str, Any]]:
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
```

Pass `responses=error_response_openapi()` to both `FastAPI(...)` constructors in
`rag_modules/interfaces/api/app.py`.

- [ ] **Step 4: Implement the FastAPI handler registry**

Create `rag_modules/interfaces/api/error_handlers.py`:

```python
"""FastAPI exception mappings for the stable public error contract."""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

from .error_models import ErrorCode, build_error_response
from .request_context import current_request_id
from .services import (
    ApiBackpressureError,
    BuildJobConflictError,
    BuildJobNotFoundError,
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
    async def system_not_ready(_: Request, __: SystemNotReadyError):
        return build_error_response(
            ErrorCode.SYSTEM_NOT_READY,
            request_id=current_request_id(),
        )

    @app.exception_handler(BuildJobNotFoundError)
    async def build_job_not_found(_: Request, __: BuildJobNotFoundError):
        return build_error_response(
            ErrorCode.NOT_FOUND,
            request_id=current_request_id(),
        )

    @app.exception_handler(BuildJobConflictError)
    async def build_job_conflict(_: Request, exc: BuildJobConflictError):
        details = {
            "job_id": str(exc.job.get("job_id") or ""),
            "status": str(exc.job.get("status") or ""),
        }
        return build_error_response(
            ErrorCode.BUILD_JOB_CONFLICT,
            request_id=current_request_id(),
            details=details,
        )

    @app.exception_handler(ApiBackpressureError)
    async def api_backpressure(_: Request, __: ApiBackpressureError):
        return build_error_response(
            ErrorCode.RATE_LIMITED,
            request_id=current_request_id(),
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error(_: Request, exc: RequestValidationError):
        return build_error_response(
            ErrorCode.VALIDATION_ERROR,
            request_id=current_request_id(),
            details=_validation_details(exc),
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_error(_: Request, exc: StarletteHTTPException):
        code = {
            404: ErrorCode.NOT_FOUND,
            405: ErrorCode.METHOD_NOT_ALLOWED,
        }.get(exc.status_code, ErrorCode.INVALID_REQUEST)
        return build_error_response(code, request_id=current_request_id())


__all__ = ["register_api_error_handlers"]
```

Delete the three legacy registration functions from `routes.py`, remove their imports from
`app.py`, and call `register_api_error_handlers(app)` for both app factories before registering
routes.

- [ ] **Step 5: Convert security middleware errors to the common payload**

In `security.py`, import `ERROR_STATUS_CODES`, `ErrorCode`, `build_error_payload`, and
`current_request_id`. Change `_authentication_error` to return `ErrorCode | None`:

```python
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
```

Replace `_send_json` and `_request_too_large` with one safe sender:

```python
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
```

Use `INVALID_REQUEST` for malformed `Content-Length`, `REQUEST_TOO_LARGE` with
`details={"max_bytes": max_bytes}`, `UNAUTHORIZED` for credentials, and
`SERVICE_MISCONFIGURED` for invalid server auth configuration.

- [ ] **Step 6: Run API tests and verify GREEN**

Run:

```powershell
python -m pytest tests/test_api_app.py -q
```

Expected: all API tests pass with the new breaking error contract.

- [ ] **Step 7: Commit HTTP normalization**

```powershell
git add rag_modules/interfaces/api/error_handlers.py rag_modules/interfaces/api/error_models.py rag_modules/interfaces/api/security.py rag_modules/interfaces/api/routes.py rag_modules/interfaces/api/app.py tests/test_api_app.py
git commit -m "feat: normalize HTTP API failures"
```

### Task 3: Answer Failures and SSE Error Events

**Files:**
- Modify: `rag_modules/interfaces/api/services/errors.py`
- Modify: `rag_modules/interfaces/api/services/__init__.py`
- Modify: `rag_modules/interfaces/api/error_handlers.py`
- Modify: `rag_modules/interfaces/api/services/serving.py`
- Modify: `rag_modules/interfaces/api/answer_models.py`
- Modify: `rag_modules/interfaces/api/routes.py`
- Modify: `rag_modules/app/services/answer_result_factory.py`
- Test: `tests/test_api_app.py`
- Test: `tests/test_answer_workflow.py`

- [ ] **Step 1: Write failing synchronous and SSE privacy tests**

Add a failed response fixture to `tests/test_api_app.py`:

```python
class _FailedAnswerResponse(_DummyAnswerResponse):
    def __init__(self, question: str, secret: str, stream: bool) -> None:
        super().__init__(question, False, stream)
        self.secret = secret

    def to_dict(self) -> dict:
        payload = super().to_dict()
        payload["summary"].update(
            status="failed",
            answer=f"raw failure: {self.secret}",
            error=self.secret,
        )
        payload["traces"]["route_trace"]["error"] = self.secret
        return payload


class _FailedAnswerSystem(_FakeApiSystem):
    def __init__(self, secret: str) -> None:
        super().__init__()
        self.system_ready = True
        self.serving_initialized = True
        self.secret = secret

    def answer_question_response(self, question: str, *, stream=False, **kwargs):
        del kwargs
        return _FailedAnswerResponse(question, self.secret, stream)
```

Add tests:

```python
def test_failed_answer_becomes_typed_500_without_raw_exception(self) -> None:
    secret = "answer-provider-secret"
    app = create_serving_api_app(system=_FailedAnswerSystem(secret))

    with _client(app) as client:
        response = client.post(
            "/answers",
            json={"question": "safe question"},
            headers={"X-Request-ID": "answer-failed-42"},
        )

    payload = _assert_error_response(
        response,
        status_code=500,
        code="ANSWER_FAILED",
        request_id="answer-failed-42",
    )
    self.assertNotIn(secret, json.dumps(payload))

def test_sse_error_uses_common_contract_and_request_id(self) -> None:
    secret = "stream-provider-secret"
    app = create_serving_api_app(system=_FailedAnswerSystem(secret))

    with _client(app) as client:
        with client.stream(
            "POST",
            "/answers/stream",
            json={"question": "safe question"},
            headers={"X-Request-ID": "stream-failed-42"},
        ) as response:
            body = "".join(response.iter_text())

    self.assertEqual(response.status_code, 200)
    self.assertIn("event: error", body)
    self.assertIn('"code": "ANSWER_FAILED"', body)
    self.assertIn('"request_id": "stream-failed-42"', body)
    self.assertNotIn("error_type", body)
    self.assertNotIn(secret, body)
    self.assertIn("event: done", body)

def test_stream_preflight_failure_uses_http_error_contract(self) -> None:
    app = create_serving_api_app(system=_FakeApiSystem())

    with _client(app) as client:
        response = client.post(
            "/answers/stream",
            json={"question": "safe question"},
        )

    _assert_error_response(response, status_code=409, code="SYSTEM_NOT_READY")
```

In `tests/test_answer_workflow.py`, add a direct result-factory regression asserting a thrown
message is not placed in the fallback answer.

- [ ] **Step 2: Run the focused tests and verify RED**

Run:

```powershell
python -m pytest tests/test_api_app.py tests/test_answer_workflow.py -q -k "failed_answer or sse_error or stream_preflight or raw_exception"
```

Expected: failed answers return a legacy status-200 payload, SSE emits `message/error_type`, and the
fallback answer contains the secret.

- [ ] **Step 3: Add a typed answer failure and handler**

Add this class to `services/errors.py` and export it from `services/__init__.py`:

```python
class AnswerFailedError(RuntimeError):
    """Raised when an answer result reaches a terminal failed state."""
```

Register it in `error_handlers.py`:

```python
@app.exception_handler(AnswerFailedError)
async def answer_failed(_: Request, __: AnswerFailedError):
    return build_error_response(
        ErrorCode.ANSWER_FAILED,
        request_id=current_request_id(),
    )
```

- [ ] **Step 4: Make sync and streaming services detect failed answer payloads**

In `services/serving.py`, add:

```python
@staticmethod
def _answer_payload(response) -> dict:
    payload = response.to_dict()
    summary = dict(payload.get("summary") or {})
    if str(summary.get("status") or "").lower() == "failed":
        raise AnswerFailedError()
    return payload
```

Use `_answer_payload(response)` in `answer_question` instead of returning `response.to_dict()`.

Refactor `stream_answer_question_events` so its readiness checks execute eagerly before returning
an inner iterator:

```python
def stream_answer_question_events(
    self,
    *,
    question: str,
    explain_routing: bool = False,
    request_id: str = "",
) -> Iterator[AnswerStreamEventModel]:
    self._ensure_serving_runtime_initialized()
    self._refresh_serving_runtime_if_stale()
    self._raise_if_system_not_ready()
    resolved_request_id = normalize_or_generate_request_id(request_id)
    return self._iter_stream_answer_question_events(
        question=question,
        explain_routing=explain_routing,
        request_id=resolved_request_id,
    )
```

Move the current queue/runner/yield implementation into `_iter_stream_answer_question_events`.
Inside the runner, call `_answer_payload(response)` before emitting a result. Emit safe errors only:

```python
except ApiBackpressureError:
    emit(AnswerStreamEventModel.error(code=ErrorCode.RATE_LIMITED, request_id=request_id))
except SystemNotReadyError:
    emit(AnswerStreamEventModel.error(code=ErrorCode.SYSTEM_NOT_READY, request_id=request_id))
except AnswerFailedError:
    emit(AnswerStreamEventModel.error(code=ErrorCode.ANSWER_FAILED, request_id=request_id))
except Exception:
    emit(AnswerStreamEventModel.error(code=ErrorCode.ANSWER_FAILED, request_id=request_id))
```

In both answer routes, capture `current_request_id()` and pass it to the service stream method.

- [ ] **Step 5: Replace the SSE error model with the common typed model**

In `answer_models.py`, remove the legacy `AnswerStreamErrorDataModel`. Import `ErrorCode`,
`ErrorResponseModel`, and `build_error_model`; use `ErrorResponseModel` in the event union and replace
the factory:

```python
@classmethod
def error(
    cls,
    *,
    code: ErrorCode,
    request_id: str,
) -> "AnswerStreamEventModel":
    return cls(
        event=AnswerStreamEventType.error,
        data=build_error_model(code, request_id=request_id),
    )
```

Update the existing admission-limit SSE test to assert `RATE_LIMITED`, the response-header request
ID, and the absence of `error_type`.

- [ ] **Step 6: Remove exception text from internal fallback answers**

Change `QuestionAnswerResultFactory.from_error` to ignore the exception text:

```python
def from_error(
    self,
    state: AnswerPipelineState,
    *,
    latency_ms: float,
    trace_bundle: AnswerTraceBundle,
    error: Exception,
) -> QuestionAnswerResult:
    del error
    return QuestionAnswerResult(
        answer="The answer could not be generated.",
        analysis=None,
        retrieval_outcome=state.retrieval_outcome,
        answer_context=state.answer_context,
        route_resolution=state.route_resolution,
        latency_ms=latency_ms,
        route_trace=trace_bundle.route_trace,
        graph_trace=trace_bundle.graph_trace,
        generation_trace=trace_bundle.generation_trace,
        trace_event=trace_bundle.trace_event,
    )
```

- [ ] **Step 7: Run answer and SSE tests and verify GREEN**

Run:

```powershell
python -m pytest tests/test_api_app.py tests/test_answer_workflow.py -q
```

Expected: all selected files pass.

- [ ] **Step 8: Commit answer-boundary hardening**

```powershell
git add rag_modules/interfaces/api/services/errors.py rag_modules/interfaces/api/services/__init__.py rag_modules/interfaces/api/error_handlers.py rag_modules/interfaces/api/services/serving.py rag_modules/interfaces/api/answer_models.py rag_modules/interfaces/api/routes.py rag_modules/app/services/answer_result_factory.py tests/test_api_app.py tests/test_answer_workflow.py
git commit -m "feat: sanitize answer and SSE failures"
```

### Task 4: Typed and Privacy-Safe Build-Job Failures

**Files:**
- Modify: `rag_modules/interfaces/api/build_jobs/models.py`
- Modify: `rag_modules/interfaces/api/build_jobs/registry.py`
- Modify: `rag_modules/interfaces/api/services/build.py`
- Modify: `rag_modules/interfaces/api/build_models.py`
- Modify: `rag_modules/interfaces/api/routes.py`
- Test: `tests/test_build_job_persistence.py`
- Test: `tests/test_api_app.py`

- [ ] **Step 1: Write failing persistence and API tests**

Add a failing build system in `tests/test_build_job_persistence.py`:

```python
import json


class _FailingBuildSystem(_BuildSystem):
    def __init__(self, config, secret: str) -> None:
        super().__init__(config)
        self.secret = secret

    def build_knowledge_base(self, progress=None) -> None:
        if progress:
            progress(f"private progress {self.secret}")
        raise RuntimeError(self.secret)
```

Add tests:

```python
def test_failed_job_persists_typed_error_without_raw_exception_or_progress(self) -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        path = str(Path(temp_dir) / "build_jobs.json")
        config = build_test_config({"storage": {"build_job_store_path": path}})
        secret = "build-database-password"
        service = GraphRAGBuildApiService(
            system=_FailingBuildSystem(config, secret),
            job_store=FileBuildJobStore(path),
        )

        submitted = service.submit_build_job(request_id="build-submit-42")
        failed = _wait_for_service_job_status(service, submitted["job_id"], "failed")
        stored_text = Path(path).read_text(encoding="utf-8")

        self.assertEqual(
            failed["error"],
            {
                "code": "BUILD_FAILED",
                "message": "The knowledge-base build failed.",
                "request_id": "build-submit-42",
            },
        )
        self.assertEqual(failed["logs"], ["Build progress updated.", "Build failed."])
        self.assertNotIn(secret, stored_text)

def test_legacy_raw_job_errors_are_sanitized_on_load(self) -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        path = str(Path(temp_dir) / "build_jobs.json")
        store = FileBuildJobStore(path)
        store.save_all(
            [
                {
                    "job_id": "a" * 32,
                    "job_type": "build",
                    "status": "failed",
                    "created_at": "2026-06-28T00:00:00Z",
                    "error": "legacy-secret",
                    "logs": ["[ERROR] legacy-secret"],
                }
            ]
        )
        config = build_test_config({"storage": {"build_job_store_path": path}})
        service = GraphRAGBuildApiService(
            system=_BuildSystem(config),
            job_store=store,
        )

        restored = service.get_build_job("a" * 32)
        returned_text = json.dumps(restored, ensure_ascii=False)
        stored_text = Path(path).read_text(encoding="utf-8")

        self.assertEqual(restored["error"]["code"], "BUILD_FAILED")
        self.assertEqual(restored["logs"], ["Build failed."])
        self.assertNotIn("legacy-secret", returned_text)
        self.assertNotIn("legacy-secret", stored_text)
```

Add this fixture and API test to `tests/test_api_app.py`:

```python
class _FailingBuildApiSystem(_FakeApiSystem):
    def __init__(self, secret: str) -> None:
        super().__init__()
        self.build_initialized = True
        self.secret = secret

    def build_knowledge_base(self, progress=None) -> None:
        if progress:
            progress(f"private progress {self.secret}")
        raise RuntimeError(self.secret)


def test_failed_build_job_keeps_submission_request_id_without_secret(self) -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        config = build_test_config(
            {
                "api": {"access_token": _API_TOKEN},
                "storage": {
                    "artifact_manifest_path": str(Path(temp_dir) / "manifest.json"),
                    "build_job_store_path": str(Path(temp_dir) / "jobs.json"),
                },
            }
        )
        secret = "build-http-secret"
        system = _FailingBuildApiSystem(secret)
        system.config = config
        app = create_build_api_app(system=system, config=config)

        with _client(app) as client:
            submitted = client.post(
                "/jobs/build",
                headers={"X-Request-ID": "build-http-42"},
            ).json()["job"]
            failed = _wait_for_job_status(client, submitted["job_id"], "failed")

        self.assertEqual(failed["request_id"], "build-http-42")
        self.assertEqual(failed["error"]["request_id"], "build-http-42")
        self.assertEqual(failed["error"]["code"], "BUILD_FAILED")
        self.assertNotIn(secret, json.dumps(failed, ensure_ascii=False))
```

- [ ] **Step 2: Run build-job tests and verify RED**

Run:

```powershell
python -m pytest tests/test_build_job_persistence.py tests/test_api_app.py -q -k "failed_job or legacy_raw_job or build_http"
```

Expected: `submit_build_job` rejects `request_id`, persisted `error` is a string, and raw progress
and exception text appear in the store.

- [ ] **Step 3: Change the build-job record to schema v2**

In `build_jobs/models.py`, import `Mapping` from `collections.abc`, set
`BUILD_JOB_STORE_SCHEMA_VERSION = "graph-rag-build-jobs-v2"`, add `request_id: str = ""`, and
change `error` to `dict | None = None`. Add these helpers:

```python
_SAFE_BUILD_LOGS = frozenset(
    {
        "Build progress updated.",
        "Build failed.",
        "Build interrupted by service restart.",
    }
)


def _safe_build_log(value: object) -> str:
    text = str(value or "")
    if text in _SAFE_BUILD_LOGS:
        return text
    if "error" in text.lower() or "fail" in text.lower():
        return "Build failed."
    return "Build progress updated."


def build_failure(request_id: str) -> dict[str, str]:
    return {
        "code": ErrorCode.BUILD_FAILED.value,
        "message": ERROR_MESSAGES[ErrorCode.BUILD_FAILED],
        "request_id": normalize_or_generate_request_id(request_id),
    }
```

Replace `to_dict` and `from_dict` with these definitions. `to_dict` writes `request_id`, a deep
copy of `error`, and safe log strings. `from_dict` reads legacy string errors and v2 error mappings,
throws away the stored raw message, normalizes every log through `_safe_build_log`, and stores
`build_failure(request_id)` whenever the persisted record contains any non-empty error value:

```python
def to_dict(self) -> dict:
    return {
        "job_id": self.job_id,
        "request_id": self.request_id,
        "job_type": self.job_type,
        "status": self.status,
        "created_at": self.created_at,
        "started_at": self.started_at,
        "finished_at": self.finished_at,
        "message": self.message,
        "error": copy.deepcopy(self.error),
        "logs": [_safe_build_log(item) for item in self.logs],
        "result": copy.deepcopy(self.result),
    }

@classmethod
def from_dict(cls, payload: Mapping[str, Any]) -> "BuildJobRecord":
    raw_error = payload.get("error")
    stored_request_id = str(payload.get("request_id") or "")
    if isinstance(raw_error, Mapping):
        stored_request_id = str(raw_error.get("request_id") or stored_request_id)
    request_id = normalize_or_generate_request_id(stored_request_id)
    return cls(
        job_id=str(payload.get("job_id") or ""),
        request_id=request_id,
        job_type=str(payload.get("job_type") or "build"),
        status=str(payload.get("status") or "failed"),
        created_at=str(payload.get("created_at") or ""),
        started_at=str(payload.get("started_at") or ""),
        finished_at=str(payload.get("finished_at") or ""),
        message=str(payload.get("message") or ""),
        error=build_failure(request_id) if raw_error else None,
        logs=[_safe_build_log(item) for item in list(payload.get("logs") or [])],
        result=(
            copy.deepcopy(dict(payload["result"]))
            if isinstance(payload.get("result"), Mapping)
            else None
        ),
    )
```

Update `PersistentBuildJobRegistry._load` so loading any existing jobs rewrites their sanitized v2
representation immediately:

```python
def _load(self, *, recover_interrupted: bool) -> None:
    with self.store.locked():
        recovered = self._refresh_from_store_locked(
            recover_interrupted=recover_interrupted
        )
        if recovered or self._jobs:
            self._persist_store_locked()
```

- [ ] **Step 4: Thread request ID through registry and build service**

Change `PersistentBuildJobRegistry.create` and `create_or_active` to accept `request_id` and store it
on `BuildJobRecord`. Replace `mark_failed` with:

```python
def mark_failed(self, job_id: str, *, result: dict) -> None:
    with self._lock:
        with self.store.locked():
            self._refresh_from_store_locked(recover_interrupted=False)
            job = self._jobs[job_id]
            job.status = "failed"
            job.finished_at = self._now()
            job.error = build_failure(job.request_id)
            job.message = "Knowledge base build failed."
            job.result = copy.deepcopy(result)
            self._clear_active_locked(job_id)
            self._persist_store_locked()
```

Make `_mark_interrupted` assign `build_failure(job.request_id)` and append
`"Build interrupted by service restart."`.

Change `GraphRAGBuildApiService.submit_build_job` to accept `request_id: str = ""`, resolve it once,
and pass it into `create_or_active`. Change its progress callback and failure branch to:

```python
def progress(_: str) -> None:
    self._append_job_log(job_id, "Build progress updated.")

# exception branch
except Exception:
    self._append_job_log(job_id, "Build failed.")
    diagnostics, stats = self._snapshot_after_build_failure()
    self._mark_job_failed(
        job_id,
        result={
            "message": "Knowledge base build failed.",
            "diagnostics": diagnostics,
            "stats": stats,
        },
    )
```

Remove all `error=str(exc)` parameters. In build routes, call:

```python
api_service.submit_build_job(
    rebuild=False,
    request_id=current_request_id(),
)
```

Apply the same request ID forwarding to rebuild and compatibility aliases.

- [ ] **Step 5: Type the public build failure object**

In `build_models.py`, add:

```python
class BuildJobFailureModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: ErrorCode
    message: str
    request_id: str
```

Add `request_id: str` to `BuildJobPayloadModel` and change its `error` field to
`Optional[BuildJobFailureModel] = None`.

- [ ] **Step 6: Run build tests and verify GREEN**

Run:

```powershell
python -m pytest tests/test_build_job_persistence.py tests/test_api_app.py -q
```

Expected: both files pass, including v1 read sanitization and v2 persistence.

- [ ] **Step 7: Commit build-job hardening**

```powershell
git add rag_modules/interfaces/api/build_jobs/models.py rag_modules/interfaces/api/build_jobs/registry.py rag_modules/interfaces/api/services/build.py rag_modules/interfaces/api/build_models.py rag_modules/interfaces/api/routes.py tests/test_build_job_persistence.py tests/test_api_app.py
git commit -m "feat: sanitize persisted build failures"
```

### Task 5: Sanitize Error Fields in Successful Public Payloads

**Files:**
- Modify: `rag_modules/interfaces/api/error_models.py`
- Modify: `rag_modules/interfaces/api/response_builder.py`
- Modify: `rag_modules/interfaces/api/routes.py`
- Modify: `rag_modules/query_understanding/planning/service.py`
- Modify: `rag_modules/build_pipeline/workflow_schema_sync.py`
- Modify: `rag_modules/infra/milvus/client.py`
- Test: `tests/test_api_app.py`
- Test: `tests/test_query_semantics.py`

- [ ] **Step 1: Write failing diagnostics, answer-trace, and stable fallback tests**

Add these fixtures and tests to `tests/test_api_app.py`:

```python
class _PublicManifestErrorSystem(_FakeApiSystem):
    def __init__(self, secret: str) -> None:
        super().__init__()
        self.secret = secret

    def collect_startup_diagnostics(self, mode: str) -> StartupDiagnostics:
        diagnostics = super().collect_startup_diagnostics(mode)
        diagnostics.manifest.last_error = self.secret
        return diagnostics

    def collect_system_stats(self) -> dict:
        payload = super().collect_system_stats()
        payload["artifact_manifest"]["last_error"] = self.secret
        return payload


class _ErrorTraceAnswerResponse(_DummyAnswerResponse):
    def __init__(self, question: str, secret: str) -> None:
        super().__init__(question, False, False)
        self.secret = secret

    def to_dict(self) -> dict:
        payload = super().to_dict()
        payload["summary"]["error"] = self.secret
        payload["traces"]["route_trace"]["error"] = self.secret
        payload["traces"]["graph_trace"]["error"] = self.secret
        payload["traces"]["trace_event"]["error"] = self.secret
        return payload


class _PublicAnswerErrorSystem(_FakeApiSystem):
    def __init__(self, secret: str) -> None:
        super().__init__()
        self.system_ready = True
        self.serving_initialized = True
        self.secret = secret

    def answer_question_response(self, question: str, **kwargs):
        del kwargs
        return _ErrorTraceAnswerResponse(question, self.secret)


def test_manifest_error_is_sanitized_in_diagnostics_and_stats(self) -> None:
    secret = "private-manifest-error"
    app = create_serving_api_app(system=_PublicManifestErrorSystem(secret))

    with _client(app) as client:
        diagnostics = client.get("/diagnostics")
        stats = client.get("/stats")

    serialized = json.dumps(
        {"diagnostics": diagnostics.json(), "stats": stats.json()},
        ensure_ascii=False,
    )
    self.assertNotIn(secret, serialized)
    self.assertIn("BUILD_FAILED", serialized)

def test_answer_trace_error_fields_are_sanitized_on_success(self) -> None:
    secret = "private-answer-trace-error"
    app = create_serving_api_app(system=_PublicAnswerErrorSystem(secret))

    with _client(app) as client:
        response = client.post("/answers", json={"question": "safe question"})

    self.assertEqual(response.status_code, 200)
    serialized = json.dumps(response.json(), ensure_ascii=False)
    self.assertNotIn(secret, serialized)
    self.assertIn("ANSWER_FAILED", serialized)
```

Add this fake and test to `tests/test_query_semantics.py`:

```python
class _FailingPlannerClient:
    def create_completion(self, **_: object) -> None:
        raise RuntimeError("private-planner-error")


def test_planner_failure_uses_stable_fallback_reason(self) -> None:
    planner = QueryPlanner(
        _FailingPlannerClient(),
        settings=QueryPlannerRuntimeSettings(fast_rule_planning=False),
        semantic_settings=self.semantic_settings,
    )

    plan = planner.plan("recommend tofu")

    self.assertEqual(plan.fallback_reason, "query_planning_failed")
```

- [ ] **Step 2: Run the focused tests and verify RED**

Run:

```powershell
python -m pytest tests/test_api_app.py tests/test_query_semantics.py -q -k "manifest_error or answer_trace_error or fallback_reason"
```

Expected: raw error strings appear and planner fallback reason contains the exception.

- [ ] **Step 3: Add recursive public error-field sanitization**

Add `Mapping` and `Sequence` from `collections.abc`, then append to `error_models.py`:

```python
_PUBLIC_ERROR_KEYS = frozenset({"error", "last_error"})


def _is_public_error_key(key: str) -> bool:
    normalized = str(key or "").strip().lower().replace("-", "_")
    return normalized in _PUBLIC_ERROR_KEYS or normalized.endswith(
        ("_error", "_exception")
    )


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
```

- [ ] **Step 4: Apply sanitization in every response builder**

In `response_builder.py`:

```python
def build_stats_response(stats_payload: dict) -> StatsResponseModel:
    safe = sanitize_public_error_fields(stats_payload, code=ErrorCode.BUILD_FAILED)
    return StatsResponseModel.model_validate({"stats": safe})


def build_diagnostics_response(diagnostics_payload: dict) -> DiagnosticsResponseModel:
    safe = sanitize_public_error_fields(diagnostics_payload, code=ErrorCode.BUILD_FAILED)
    return DiagnosticsResponseModel.model_validate({"diagnostics": safe})


def build_operation_response(operation_payload: dict) -> OperationResponseModel:
    safe = sanitize_public_error_fields(operation_payload, code=ErrorCode.BUILD_FAILED)
    return OperationResponseModel.model_validate(safe)


def build_answer_response(answer_payload: dict) -> AnswerResponseModel:
    safe = sanitize_public_error_fields(answer_payload, code=ErrorCode.ANSWER_FAILED)
    return AnswerResponseModel.model_validate({"response": safe})
```

Add the build-job response builders below the diagnostics builder so job records are sanitized before
Pydantic validation:

```python
def build_build_job_response(job_payload: dict) -> BuildJobResponseModel:
    safe = sanitize_public_error_fields(job_payload, code=ErrorCode.BUILD_FAILED)
    return BuildJobResponseModel.model_validate({"job": safe})


def build_build_job_list_response(job_payloads: list[dict]) -> BuildJobListResponseModel:
    safe = sanitize_public_error_fields(job_payloads, code=ErrorCode.BUILD_FAILED)
    return BuildJobListResponseModel.model_validate({"jobs": safe})
```

Set `_artifact_manifest_payload`'s field directly:

```python
"last_error": ErrorCode.BUILD_FAILED.value if manifest.last_error else "",
```

Import `OperationResponseModel`, export `build_operation_response`, and wrap all three operation
routes exactly like this:

```python
def initialize_serving_runtime():
    return build_operation_response(api_service.initialize_serving_runtime())

def refresh_serving_runtime():
    return build_operation_response(api_service.refresh_serving_runtime())

def initialize_build_runtime():
    return build_operation_response(api_service.initialize_build_runtime())
```

In `rag_modules/interfaces/api/answer.py`, replace the SSE result branch with this body so the
payload is sanitized before `AnswerStreamEventModel.result(...)` validates it:

```python
safe_payload = sanitize_public_error_fields(
    self._answer_payload(response),
    code=ErrorCode.ANSWER_FAILED,
)
emit(AnswerStreamEventModel.result(safe_payload))
```

- [ ] **Step 5: Remove raw exception-derived fallback values**

Make these exact replacements:

```python
# query_understanding/planning/service.py
plan.fallback_reason = "query_planning_failed"

# build_pipeline/workflow_schema_sync.py
self._emit(progress, "[WARN] Semantic graph schema sync failed. Continuing startup.")
return SemanticGraphSchemaSyncResult(
    enabled=True,
    error="SEMANTIC_SCHEMA_SYNC_FAILED",
)

# infra/milvus/client.py get_collection_stats failure
return {"error": "MILVUS_STATS_UNAVAILABLE"}
```

Do not change `generation_failure_code`, which inspects exception text internally only to classify a
known provider failure and does not expose or log that text.

- [ ] **Step 6: Run public-payload tests and verify GREEN**

Run:

```powershell
python -m pytest tests/test_api_app.py tests/test_query_semantics.py -q
```

Expected: both files pass and all sentinels are absent.

- [ ] **Step 7: Commit response privacy**

```powershell
git add rag_modules/interfaces/api/error_models.py rag_modules/interfaces/api/response_builder.py rag_modules/interfaces/api/routes.py rag_modules/query_understanding/planning/service.py rag_modules/build_pipeline/workflow_schema_sync.py rag_modules/infra/milvus/client.py tests/test_api_app.py tests/test_query_semantics.py
git commit -m "feat: sanitize public failure details"
```

### Task 6: Safe Logging Helper and Static Privacy Gate

**Files:**
- Create: `rag_modules/safe_logging.py`
- Create: `tests/test_safe_logging.py`

- [ ] **Step 1: Write failing helper and AST policy tests**

Create `tests/test_safe_logging.py`:

```python
from __future__ import annotations

import ast
import logging
import unittest
from pathlib import Path

from rag_modules.safe_logging import log_failure

_LOGGER_METHODS = {"debug", "info", "warning", "error", "exception", "critical"}
_FORBIDDEN_NAMES = {
    "access_token",
    "api_key",
    "authorization",
    "cookie",
    "e",
    "error",
    "exc",
    "fallback_exc",
    "password",
    "plan",
    "prompt",
    "query",
    "question",
    "secret",
    "text",
    "tokenized_query",
    "tokens",
    "constraints",
    "source_entities",
    "target_entities",
}


class SafeLoggingTests(unittest.TestCase):
    def test_log_failure_omits_exception_message(self) -> None:
        logger = logging.getLogger("tests.safe_logging")
        secret = "provider-api-key-secret"

        with self.assertLogs(logger, level="ERROR") as captured:
            log_failure(
                logger,
                logging.ERROR,
                "answer_failed",
                code="ANSWER_FAILED",
                error=RuntimeError(secret),
                request_id="request-42",
            )

        output = "\n".join(captured.output)
        self.assertIn("ANSWER_FAILED", output)
        self.assertIn("RuntimeError", output)
        self.assertIn("request-42", output)
        self.assertNotIn(secret, output)

    def test_production_logger_calls_do_not_receive_sensitive_objects(self) -> None:
        violations: list[str] = []
        for path in Path("rag_modules").rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                    continue
                if not isinstance(node.func.value, ast.Name) or node.func.value.id != "logger":
                    continue
                if node.func.attr not in _LOGGER_METHODS:
                    continue
                if node.func.attr == "exception":
                    violations.append(f"{path}:{node.lineno}: logger.exception")
                for argument in [*node.args[1:], *(item.value for item in node.keywords)]:
                    for child in ast.walk(argument):
                        name = ""
                        if isinstance(child, ast.Name):
                            name = child.id
                        elif isinstance(child, ast.Attribute):
                            name = child.attr
                        if name in _FORBIDDEN_NAMES:
                            violations.append(f"{path}:{node.lineno}: {name}")
        self.assertEqual([], sorted(set(violations)))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the new test and verify RED**

Run:

```powershell
python -m pytest tests/test_safe_logging.py -q
```

Expected: collection fails because `rag_modules.safe_logging` is missing; after adding only the
helper, the AST test still reports all current unsafe call sites.

- [ ] **Step 3: Implement the narrow failure logger**

Create `rag_modules/safe_logging.py`:

```python
"""Privacy-safe structured failure logging."""

from __future__ import annotations

import logging


def log_failure(
    logger: logging.Logger,
    level: int,
    event: str,
    *,
    code: str,
    error: BaseException,
    request_id: str = "",
) -> None:
    logger.log(
        level,
        "%s code=%s request_id=%s exception_type=%s",
        event,
        str(code),
        str(request_id or "-"),
        type(error).__name__,
    )


__all__ = ["log_failure"]
```

- [ ] **Step 4: Run only the helper test and verify GREEN**

Run:

```powershell
python -m pytest tests/test_safe_logging.py::SafeLoggingTests::test_log_failure_omits_exception_message -q
```

Expected: one test passes.

- [ ] **Step 5: Commit the helper and red static gate**

Do not commit while the repository test is red. Tasks 7 and 8 complete the static gate before the
next commit; keep these two new files in the working tree.

### Task 7: Remove Query-Derived and Sensitive Content from Logs

**Files:**
- Modify: `rag_modules/domain/shared/query_constraints.py`
- Modify: `rag_modules/routing/workflow_service.py`
- Modify: `rag_modules/query_understanding/planning/service.py`
- Modify: `rag_modules/graph/retrieval_executor.py`
- Modify: `rag_modules/graph/evidence_orchestrator.py`
- Modify: `rag_modules/retrieval/dual_level_retriever.py`
- Modify: `rag_modules/retrieval/hybrid_search_service.py`
- Modify: `rag_modules/retrieval/adapters/bm25_retriever.py`
- Modify: `rag_modules/infra/neo4j/connection.py`
- Modify: `rag_modules/infra/milvus/client.py`
- Modify: `rag_modules/infra/milvus/schema.py`
- Modify: `rag_modules/build_pipeline/document_artifacts/cache.py`
- Modify: `rag_modules/build_pipeline/graph_preparation/module.py`
- Modify: `rag_modules/build_pipeline/graph_preparation/document_builder.py`
- Modify: `rag_modules/generation/service.py`
- Modify: `rag_modules/retrieval_cache.py`
- Test: `tests/test_safe_logging.py`

- [ ] **Step 1: Add runtime sentinel tests for query and token logs**

Extend `tests/test_safe_logging.py` with a real BM25 test:

```python
from langchain_core.documents import Document

from rag_modules.retrieval.adapters.bm25_retriever import BM25Retriever


def test_bm25_log_contains_counts_but_not_query_or_tokens(self) -> None:
    secret = "private_query_token_7281"
    retriever = BM25Retriever()
    retriever.build([Document(page_content=secret, metadata={"recipe_name": "safe"})])

    with self.assertLogs(
        "rag_modules.retrieval.adapters.bm25_retriever",
        level="INFO",
    ) as captured:
        retriever.search(secret, top_k=1)

    output = "\n".join(captured.output)
    self.assertIn("returned=", output)
    self.assertNotIn(secret, output)
```

- [ ] **Step 2: Run the sentinel test and verify RED**

Run:

```powershell
python -m pytest tests/test_safe_logging.py -q -k "bm25_log"
```

Expected: the BM25 log contains `private_query_token_7281`.

- [ ] **Step 3: Replace content-bearing logs with safe metadata**

Apply these exact event replacements:

| File | Replacement |
| --- | --- |
| `domain/shared/query_constraints.py` | assign `has_constraints = constraints.has_constraints()`, then log `logger.info("Query constraints parsed: present=%s", has_constraints)` |
| `routing/workflow_service.py` | `logger.info("Query routing started: top_k=%s", top_k)` |
| `query_understanding/planning/service.py` | fixed cache-hit/join messages; assign `planner_mode = plan.planner_mode` and `strategy = plan.strategy` before logging `logger.info("Query plan created: mode=%s strategy=%s", planner_mode, strategy)` |
| `graph/retrieval_executor.py` | `logger.info("Starting GraphRAG retrieval: top_k=%s", request.top_k)`; cache-ready log keeps entity/relation counts and drops the absolute path argument |
| `graph/evidence_orchestrator.py` | use the exact count-only plan call below; subgraph log becomes `logger.info("Extracting knowledge subgraph: source_count=%s", source_count)` after assigning `source_count = len(retrieval_plan.source_entities)` |
| `retrieval/dual_level_retriever.py` | `logger.info("Starting dual-level retrieval: candidate_k=%s", request.effective_candidate_k)` |
| `retrieval/hybrid_search_service.py` | `logger.info("Starting hybrid retrieval: rrf_k=%s top_k=%s", self.fusion_ranker.rrf_k, request.top_k)` |
| `retrieval/adapters/bm25_retriever.py` | completion log is `logger.info("BM25 search complete: returned=%d", len(docs))` |
| `infra/neo4j/connection.py` | connection log becomes `logger.info("Neo4j connection established")` |
| `infra/milvus/client.py` | connection log becomes `logger.info("Milvus connection established")`; collection-list log uses `len(collections)`; embedding initialization uses a fixed message; collection mutation logs use fixed success/not-found events |
| `infra/milvus/schema.py` | create/drop/existence logs become fixed events without `target_collection` |
| `build_pipeline/document_artifacts/cache.py` | candidate and active manifest save logs become fixed events without filesystem paths |
| `build_pipeline/graph_preparation/module.py` | Neo4j connection log becomes a fixed event without `uri` |
| `build_pipeline/graph_preparation/document_builder.py` | replace `logger.warning("Failed to process recipe %s (%s)", recipe.get("name"), recipe.get("id"), exc_info=True)` with `logger.warning("Document recipe processing failed", exc_info=True)` |
| `generation/service.py` | initialization log becomes a fixed event without `model_name` |
| `retrieval_cache.py` | cache-save log becomes a fixed event without `path` |

Also replace `logger.info("Loaded jieba custom dictionary: %s", dict_path)` with
`logger.info("Loaded jieba custom dictionary")`, and remove the graph-cache stats file path argument
from `graph/retrieval_executor.py`.

For the graph plan, use this exact safe call:

```python
logger.info(
    "Executing graph retrieval plan: type=%s source_count=%s target_count=%s linked_count=%s",
    query_type,
    source_count,
    target_count,
    linked_count,
)
```

Compute those four locals immediately before the call. Do the same for `source_count` before the
subgraph log so the AST policy never receives entity-bearing objects.

Do not remove count, latency, retry-number, boolean-state, or predefined strategy metadata.

- [ ] **Step 4: Run the content sentinel and static tests**

Run:

```powershell
python -m pytest tests/test_safe_logging.py -q
```

Expected: the BM25 test passes; remaining failures list exception-object log calls for Task 8 only.

### Task 8: Replace Raw Exception and Traceback Logging

**Files:**
- Modify: `rag_modules/entity_linker.py`
- Modify: `rag_modules/app/services/answer_pipeline.py`
- Modify: `rag_modules/app/services/answer_workflow.py`
- Modify: `rag_modules/build_pipeline/knowledge_base_workflow.py`
- Modify: `rag_modules/build_pipeline/workflow_schema_sync.py`
- Modify: `rag_modules/build_pipeline/document_artifacts/cache.py`
- Modify: `rag_modules/generation/clients/adapter.py`
- Modify: `rag_modules/generation/execution/engine.py`
- Modify: `rag_modules/generation/execution/streaming.py`
- Modify: `rag_modules/generation/execution/two_stage.py`
- Modify: `rag_modules/graph/evidence_orchestrator.py`
- Modify: `rag_modules/graph/query_executor.py`
- Modify: `rag_modules/graph/retrieval_executor.py`
- Modify: `rag_modules/graph/retrieval_postprocess.py`
- Modify: `rag_modules/observability/tracing_sink_interaction.py`
- Modify: `rag_modules/observability/tracing_sinks.py`
- Modify: `rag_modules/retrieval_cache.py`
- Modify: `rag_modules/retrieval/candidate_generator.py`
- Modify: `rag_modules/retrieval/hybrid_index_service.py`
- Modify: `rag_modules/retrieval/post_processor.py`
- Modify: `rag_modules/retrieval/adapters/bm25_retriever.py`
- Modify: `rag_modules/retrieval/adapters/neo4j_fallback_retriever.py`
- Modify: `rag_modules/retrieval/adapters/vector_retriever.py`
- Modify: `rag_modules/routing/search_orchestrator.py`
- Modify: `rag_modules/query_understanding/planning/service.py`
- Modify: `rag_modules/infra/milvus/client.py`
- Modify: `rag_modules/infra/milvus/schema.py`
- Modify: `rag_modules/infra/milvus/search.py`
- Modify: `rag_modules/infra/milvus/writer.py`
- Modify: `rag_modules/telemetry.py`
- Modify: `rag_modules/interfaces/api/request_context.py`
- Modify: `rag_modules/interfaces/api/services/serving.py`
- Test: `tests/test_safe_logging.py`

- [ ] **Step 1: Add a raw-exception sentinel test for representative fallback paths**

Add these imports, fake, and test to `tests/test_safe_logging.py`:

```python
from rag_modules.observability.tracing_sinks import AsyncQueryTraceSink
from rag_modules.runtime import QueryTraceEvent


class _FailingTraceSink:
    def __init__(self, secret: str) -> None:
        self.secret = secret

    def write(self, event: QueryTraceEvent) -> None:
        del event
        raise RuntimeError(self.secret)

    def close(self) -> None:
        raise RuntimeError(self.secret)


def test_trace_sink_logs_exception_type_without_message(self) -> None:
    secret = "trace-sink-api-key"
    sink = AsyncQueryTraceSink(_FailingTraceSink(secret), max_queue_size=1)

    with self.assertLogs("rag_modules.observability.tracing_sinks", level="WARNING") as captured:
        sink.write(QueryTraceEvent(query_id="safe", timestamp=1, query="private query"))
        sink.close()

    output = "\n".join(captured.output)
    self.assertIn("RuntimeError", output)
    self.assertNotIn(secret, output)
```

Keep the AST test as the exhaustive repository gate.

- [ ] **Step 2: Run the failure-log tests and verify RED**

Run:

```powershell
python -m pytest tests/test_safe_logging.py -q
```

Expected: the sentinel is logged and the AST test reports direct `exc`, `error`, `e`, and
`logger.exception` use.

- [ ] **Step 3: Route every caught exception log through `log_failure`**

For each file listed above, import `log_failure` using the correct relative import and replace the
direct logger call with this form:

```python
log_failure(
    logger,
    logging.WARNING,
    "query_planning_failed",
    code="QUERY_PLANNING_FAILED",
    error=exc,
)
```

Use the original log severity and these literal event/code pairs:

| Area | Event | Code |
| --- | --- | --- |
| answer workflow/pipeline | `answer_workflow_failed`, `streaming_output_failed` | `ANSWER_FAILED` |
| build workflow/cache/schema | `build_failed`, `document_cache_load_failed`, `semantic_schema_sync_failed` | `BUILD_FAILED` |
| generation client/execution | `generation_attempt_failed`, `generation_fallback_failed` | `GENERATION_FAILED` |
| graph executor/postprocess/reasoning | `graph_operation_failed` | `GRAPH_OPERATION_FAILED` |
| retrieval/cache/rerank/candidate | `retrieval_operation_failed` | `RETRIEVAL_FAILED` |
| query planning/routing | `query_planning_failed`, `query_routing_failed` | `QUERY_PROCESSING_FAILED` |
| trace sink | `query_trace_sink_failed` | `TRACE_SINK_FAILED` |
| Milvus operations | `milvus_operation_failed` | `MILVUS_OPERATION_FAILED` |
| entity linking | `entity_linking_failed` | `ENTITY_LINKING_FAILED` |

Retry logs may keep the numeric attempt as a separate preceding/succeeding safe log, but the
exception itself must go only through `log_failure`. Replace `logger.exception` with
`log_failure(..., logging.ERROR, ..., error=exc)` inside the existing `except Exception as exc`
block.

In `request_context.py`, add a module logger and safely record the final unknown request failure:

```python
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
```

In the SSE runner's final `except Exception as exc` branch, call `log_failure` with the captured
stream request ID before emitting the safe `ANSWER_FAILED` event.

- [ ] **Step 4: Remove raw exceptions from OpenTelemetry spans**

Replace the exception branch in `RuntimeTelemetry.span`:

```python
except Exception as exc:
    span.set_attribute("error.type", type(exc).__name__)
    span.set_status(Status(StatusCode.ERROR, "INTERNAL_ERROR"))
    raise
```

Do not call `span.record_exception(exc)`, because OpenTelemetry serializes the exception message
and stack trace.

- [ ] **Step 5: Run the privacy gate and verify GREEN**

Run:

```powershell
python -m pytest tests/test_safe_logging.py -q
```

Expected: all safe-logging and AST tests pass with no sentinel output.

- [ ] **Step 6: Run subsystem tests touched by the logging edits**

Run:

```powershell
python -m pytest tests/test_query_semantics.py tests/test_query_tracer.py tests/test_graph_retrieval_executor.py tests/test_hybrid_search_service.py tests/test_retrieval_candidate_generator.py tests/test_generation_executor.py tests/test_build_pipeline_provider.py -q
```

Expected: all selected tests pass; logging-only edits do not alter subsystem results.

- [ ] **Step 7: Commit the complete logging privacy gate**

```powershell
git add -- rag_modules/safe_logging.py rag_modules/entity_linker.py rag_modules/app/services/answer_pipeline.py rag_modules/app/services/answer_workflow.py rag_modules/build_pipeline/knowledge_base_workflow.py rag_modules/build_pipeline/workflow_schema_sync.py rag_modules/build_pipeline/document_artifacts/cache.py rag_modules/build_pipeline/graph_preparation/document_builder.py rag_modules/build_pipeline/graph_preparation/module.py rag_modules/domain/shared/query_constraints.py rag_modules/generation/service.py rag_modules/generation/clients/adapter.py rag_modules/generation/execution/engine.py rag_modules/generation/execution/streaming.py rag_modules/generation/execution/two_stage.py rag_modules/graph/evidence_orchestrator.py rag_modules/graph/query_executor.py rag_modules/graph/retrieval_executor.py rag_modules/graph/retrieval_postprocess.py rag_modules/infra/milvus/client.py rag_modules/infra/milvus/schema.py rag_modules/infra/milvus/search.py rag_modules/infra/milvus/writer.py rag_modules/infra/neo4j/connection.py rag_modules/interfaces/api/request_context.py rag_modules/interfaces/api/services/serving.py rag_modules/observability/tracing_sink_interaction.py rag_modules/observability/tracing_sinks.py rag_modules/query_understanding/planning/service.py rag_modules/retrieval_cache.py rag_modules/retrieval/adapters/bm25_retriever.py rag_modules/retrieval/adapters/neo4j_fallback_retriever.py rag_modules/retrieval/adapters/vector_retriever.py rag_modules/retrieval/candidate_generator.py rag_modules/retrieval/dual_level_retriever.py rag_modules/retrieval/hybrid_index_service.py rag_modules/retrieval/hybrid_search_service.py rag_modules/retrieval/post_processor.py rag_modules/routing/search_orchestrator.py rag_modules/routing/workflow_service.py rag_modules/telemetry.py tests/test_safe_logging.py
git commit -m "fix: prevent sensitive data in production logs"
```

Before committing, inspect `git diff --cached --name-only` and confirm the set contains only files
named in Tasks 6 through 8; do not stage unrelated user changes.

### Task 9: Documentation and Release Verification

**Files:**
- Modify: `README.md`
- Modify: `docs/superpowers/plans/2026-06-28-error-privacy-hardening.md` (checkbox status only during execution)
- Test: `tests/test_api_app.py`
- Test: `tests/test_build_job_persistence.py`
- Test: `tests/test_safe_logging.py`

- [ ] **Step 1: Update public API and operations documentation**

Add an `Error contract and request correlation` section near the API startup documentation in
`README.md` containing:

```markdown
### Error contract and request correlation

All HTTP failures use `{"ok": false, "error": {"code": "...", "message": "..."},
"request_id": "..."}`. Error codes are stable; messages are safe for display and never contain raw
exceptions. Validation errors may include field paths and reason codes, but never the rejected
input.

Clients may send `X-Request-ID` using 1–128 ASCII letters, digits, `.`, `_`, `:`, or `-`. The service
generates a replacement when the header is missing or invalid and returns the resolved value in
every response header and every error body. SSE error events use the same payload.

Application logs do not contain raw questions, query tokens, prompts, credentials, or exception
messages. Use `request_id` and stable error codes for support correlation.
```

Also document that failed build-job resources contain a typed `error` object with code,
catalog-controlled message, and submission request ID.

- [ ] **Step 2: Run Ruff on changed Python files**

Run:

```powershell
python -m ruff check rag_modules tests/test_api_app.py tests/test_answer_workflow.py tests/test_build_job_persistence.py tests/test_safe_logging.py
python -m ruff format --check rag_modules tests/test_api_app.py tests/test_answer_workflow.py tests/test_build_job_persistence.py tests/test_safe_logging.py
```

Expected: both commands exit 0. If formatting is required, run `python -m ruff format` on only the
reported changed files, inspect the diff, and rerun both checks.

- [ ] **Step 3: Run the complete test suite**

Run:

```powershell
python -m pytest -q
```

Expected: exit 0 with no failed tests.

- [ ] **Step 4: Run repository hooks**

Run:

```powershell
pre-commit run --all-files
```

Expected: all hooks pass. Because Ruff may rewrite files, inspect `git diff` and rerun the hook if
any file changed.

- [ ] **Step 5: Run the release gate**

Run:

```powershell
python scripts/release_gate.py
```

Expected: release gate exits 0.

- [ ] **Step 6: Verify privacy requirements directly**

Run:

```powershell
rg -n --glob '*.py' 'logger\.exception|logger\..*query_tokens|logger\..*request\.query|logger\..*str\(exc\)' rag_modules
python -m pytest tests/test_api_app.py tests/test_build_job_persistence.py tests/test_safe_logging.py -q
git diff --check
```

Expected: `rg` prints no unsafe calls, focused tests pass, and `git diff --check` exits 0.

- [ ] **Step 7: Commit documentation and final verification state**

```powershell
git add README.md docs/superpowers/plans/2026-06-28-error-privacy-hardening.md
git commit -m "docs: document API error privacy contract"
```

- [ ] **Step 8: Review final requirement coverage**

Confirm from fresh command output:

- every HTTP error body has `error.code` and `request_id`;
- every response header has `X-Request-ID`;
- SSE error events use the same contract;
- no public response or persisted build job contains a raw exception sentinel;
- no production logger call accepts raw query, tokenized data, or exception objects;
- full tests, hooks, and release gate passed.
