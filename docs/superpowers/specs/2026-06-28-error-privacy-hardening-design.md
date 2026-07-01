# Error and Privacy Hardening Design

**Date:** 2026-06-28

**Status:** Approved for implementation planning

## Goal

Make every public failure deterministic and correlatable without exposing raw exceptions, and
prevent application logs from recording raw queries, tokenized query content, credentials, or
other sensitive values.

This is an intentional breaking API change. Existing top-level `message` and `error_type` error
fields will not be retained as compatibility aliases.

## Scope

The change covers both serving and build FastAPI applications, authentication and request-size
failures, FastAPI validation and routing failures, synchronous answers, SSE answers, asynchronous
build jobs, public diagnostics, structured query traces, and production logging under
`rag_modules/`.

The change does not introduce a new observability backend, change successful answer content, or
refactor subsystem exceptions into a new domain-wide exception hierarchy.

## Current Risks

- FastAPI and the API security middleware return several incompatible error shapes.
- Unhandled exceptions and validation errors can expose implementation details or request input.
- SSE errors use raw exception text and Python exception class names as public fields.
- Failed build jobs persist and return raw exception strings in `error` and `logs`.
- Failed answer results can return raw exception text in a successful HTTP response.
- Public diagnostics and trace-shaped responses can include raw `error` or `last_error` values.
- Routing, graph retrieval, dual-level retrieval, BM25, query planning, and constraint parsing log
  raw query-derived content.
- Many failure logs interpolate raw exception messages, which may contain provider responses,
  database endpoints, credentials, prompts, or user content.

## Chosen Approach

Use a centralized error and privacy policy with adapters at each public boundary.

A boundary-only FastAPI middleware was rejected because it cannot normalize failures emitted after
an SSE response starts, failures persisted by background build jobs, or failure content embedded in
otherwise successful response models. A repository-wide typed domain exception conversion was also
rejected because it would expand this focused hardening task into a broad subsystem refactor.

## Public Error Contract

Every HTTP failure uses this shape:

```json
{
  "ok": false,
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "The request is invalid.",
    "details": [
      {
        "field": "body.question",
        "reason": "string_too_long"
      }
    ]
  },
  "request_id": "client-request-42"
}
```

`error.details` is optional. It may contain only explicitly constructed, non-sensitive values. It
must never contain Pydantic's `input`, raw exception text, a query, tokenized content, a prompt,
credentials, or arbitrary provider/database payloads.

The initial error catalog is:

| HTTP status | Error code | Use |
| --- | --- | --- |
| 400 | `INVALID_REQUEST` | Malformed headers or request framing |
| 401 | `UNAUTHORIZED` | Missing or invalid API credentials |
| 404 | `NOT_FOUND` | Unknown HTTP resource or build job |
| 405 | `METHOD_NOT_ALLOWED` | Unsupported method on a known route |
| 409 | `SYSTEM_NOT_READY` | Serving artifacts are unavailable |
| 409 | `BUILD_JOB_CONFLICT` | Another build job is active |
| 413 | `REQUEST_TOO_LARGE` | Request body exceeds the configured limit |
| 422 | `VALIDATION_ERROR` | Request model validation failed |
| 429 | `RATE_LIMITED` | Answer admission control rejected the request |
| 500 | `ANSWER_FAILED` | The answer workflow failed after admission |
| 500 | `INTERNAL_ERROR` | An unexpected request failure occurred |
| 503 | `SERVICE_MISCONFIGURED` | Required server configuration is missing or invalid |
| 503 | `SERVICE_UNAVAILABLE` | A required service is temporarily unavailable |

Messages come from the catalog, not from `str(exception)`. Python exception class names are not
part of the public response.

Asynchronous resource state also uses the catalog code `BUILD_FAILED`. It is stored inside a failed
build-job representation rather than returned as the code of the surrounding status-200 job lookup.

## Request ID Policy

The request boundary reads `X-Request-ID`. A client value is accepted only when it is 1 to 128
characters long and every character is an ASCII letter, digit, `.`, `_`, `:`, or `-`. Missing or
invalid values are replaced with a server-generated UUID hex string. Invalid client input is never
echoed.

The resolved ID is stored in a `ContextVar` for synchronous and asynchronous request work. Every
HTTP response, including successful, error, authentication, and SSE responses, includes the
`X-Request-ID` header. Every HTTP error body includes the same value in `request_id`.

Work submitted to a raw `ThreadPoolExecutor` does not inherit context reliably. SSE and build-job
entry points therefore capture the resolved ID explicitly. SSE error events and persisted build-job
failure records use that captured ID.

## Components

### API error models

`rag_modules/interfaces/api/error_models.py` owns:

- the string error-code enum;
- the typed error detail and response models;
- catalog-controlled public messages;
- construction of safe HTTP and SSE error payloads.

### Request context boundary

`rag_modules/interfaces/api/request_context.py` owns:

- request ID validation and generation;
- the request ID `ContextVar` accessor;
- response-header injection;
- a final ASGI exception guard for exceptions raised outside FastAPI's route exception handlers.

The boundary tracks whether an HTTP response has started. It emits a JSON failure only when it is
still legal to start a response. Errors after an SSE stream starts are handled by the SSE adapter.

### FastAPI error handlers

`rag_modules/interfaces/api/error_handlers.py` maps:

- known API service exceptions;
- `RequestValidationError` without its input values;
- Starlette `HTTPException` values for 404 and 405;
- remaining request exceptions to `INTERNAL_ERROR`.

The security middleware uses the same response builder for authentication, malformed
`Content-Length`, configuration, and body-size failures. It does not maintain a second error
schema.

### Safe failure logging

`rag_modules/safe_logging.py` provides a narrow helper for failure events. Its accepted dynamic
failure data is limited to a stable error code, the validated request ID, and the exception class
name. It never formats the exception object or traceback. Call sites log additional metadata only
when the value is a predefined state, count, duration, or non-sensitive identifier.

Production logging call sites are audited and changed so that they do not interpolate:

- `query`, `question`, query plans, query constraints, extracted entities, or prompts;
- tokenized queries or keyword lists;
- authorization headers, cookies, API keys, passwords, tokens, or connection credentials;
- raw exception objects, exception strings, provider payloads, or database responses.

Raw content is removed rather than redacted at individual call sites. Request IDs and stable event
names provide correlation. Existing query tracing remains independently useful because
`TraceSanitizer` stores salted fingerprints instead of plaintext.

## Boundary-Specific Behavior

### Synchronous HTTP

Known failures are mapped by registered handlers. An unknown failure is logged with safe metadata
and returned as `INTERNAL_ERROR`. Validation details include only normalized field paths and
Pydantic reason codes.

### Answer workflow

The internal answer result factory no longer creates an answer string containing the exception.
Raw exception text is not copied into answer summaries, route traces, graph traces, or public
diagnostics. If the complete answer workflow ends in a failed state, the HTTP adapter returns
`ANSWER_FAILED` with status 500 instead of a failure-shaped status-200 answer.

Successful or intentionally degraded answers remain successful responses. Existing stable
generation failure codes may be preserved when they describe a non-fatal fallback, but associated
exception messages are removed from the public payload.

### SSE

Failures detected before the stream response starts use the normal HTTP contract. Failures after
streaming starts emit an `error` event whose data is:

```json
{
  "ok": false,
  "error": {
    "code": "ANSWER_FAILED",
    "message": "The answer could not be generated."
  },
  "request_id": "client-request-42"
}
```

The stream then emits its terminal `done` event. No SSE error data includes raw exception text,
exception class names, or unsanitized diagnostics.

### Build jobs

Submission captures the request ID in the job record. A failed job persists a typed failure object
containing `BUILD_FAILED`, a catalog-controlled message, and the submission request ID. The current
raw string `error` field is replaced; this is part of the accepted breaking change.

Build progress logs may contain only predefined lifecycle messages and numeric progress metadata.
When a build operation raises, the job records a fixed failure log line and the stable failure
object. It does not persist the exception string. Existing interrupted-job recovery uses the same
typed failure representation.

### Diagnostics and artifact responses

Public `error` and `last_error` fields are converted to typed safe failure information or stable
codes before model validation. Arbitrary internal strings remain available only inside runtime
state where needed for local control flow; they do not cross the API boundary.

## Data Flow

1. The outer request-context middleware resolves a safe request ID and sets the context.
2. Security and request parsing either continue or construct a catalog error using that ID.
3. Route/service work executes without logging query-derived content.
4. Known exceptions are mapped by type; unknown exceptions are safely logged and mapped to a fixed
   public error.
5. The outer boundary adds `X-Request-ID` to the response and clears its context token.
6. SSE/background adapters use their explicitly captured request ID after leaving the originating
   execution context.

## Tests

Implementation follows test-driven development. Each behavior is first introduced by a focused
failing test and its expected failure is observed before production code changes.

API tests cover:

- accepted, missing, and invalid incoming request IDs;
- request ID equality between header, HTTP body, and SSE error event;
- authentication, request-size, validation, 404, 405, known business, and unknown failures;
- absence of request input and raw exceptions from validation and internal-error responses;
- an answer workflow failure becoming a 500 typed error;
- SSE failure events using the common contract;
- failed and recovered build jobs persisting only typed safe failures;
- diagnostics and artifact responses not exposing raw `last_error` values;
- OpenAPI schemas and examples documenting the new contract.

Logging tests inject unique sentinel values for a query, tokenized terms, API key, provider error,
and database error, capture production logs, and assert that no sentinel appears. Focused behavior
tests cover the known query/content logging call sites. A small AST-based policy test prevents
obvious regressions such as passing variables named `query`, `question`, `tokens`, `exc`, or
`error` directly to a production logger call; explicit safe metadata names are allowed.

Verification expands from the focused API and privacy tests to the full test suite, Ruff or
pre-commit, and `python scripts/release_gate.py` because the change affects release-sensitive API
behavior.

## Documentation and Rollout

README API examples and operational error guidance are updated with the breaking response shape,
request ID rules, error catalog, and logging guarantees. No compatibility feature flag is added.
Clients must read `error.code`, use `request_id` for support correlation, and stop depending on the
removed `message` and `error_type` fields.
