# API Contract Governance, V1, and Debug Response Design

## Goal

Harden the HTTP API contract by separating public answer responses from debug answer
responses, making complete traces opt-in through explicit debug routes, and introducing a
versioned `/v1` API surface shared by the serving and build applications.

## Scope

This design covers:

- Serving answer routes and SSE routes.
- Build API operational routes.
- FastAPI app metadata versioning.
- OpenAPI response schemas for public and debug answer responses.
- Compatibility aliases for the existing unversioned routes.
- README/API documentation updates for the changed public workflow.

This design does not cover:

- Query trace persistence format.
- Application-layer `QuestionAnswerResponse` and runtime trace DTO semantics.
- Authentication policy changes beyond applying the same policy to `/v1` routes.
- Removing existing unversioned routes in this slice.

## Chosen Approach

Add explicit versioned public and debug routes:

- `POST /v1/answers`
- `POST /v1/answers/stream`
- `POST /v1/debug/answers`
- `POST /v1/debug/answers/stream`

The public `/v1/answers` and `/v1/answers/stream` routes return answer payloads without the
top-level `traces` object. The debug routes return the existing complete answer payload including
`traces`.

The existing unversioned routes remain compatibility aliases for this slice. They keep their
current response behavior so current clients are not broken while the new `/v1` contract becomes
the preferred surface. Documentation and OpenAPI should lead clients to `/v1`.

## Alternatives Considered

Using `debug=true` on `/answers` was rejected because the same path would have two substantially
different response schemas. That makes generated clients, OpenAPI consumers, and compatibility
testing harder.

Using a request header was rejected because it hides a major payload-shape decision from URLs and
OpenAPI route listings.

Changing every existing unversioned route immediately was rejected because old clients may depend
on `traces`. Keeping root aliases stable lets the team migrate clients deliberately.

## API Versioning

Introduce shared API constants in the API interface package:

- `API_VERSION = "1.0.0"`
- `API_PREFIX = "/v1"`

Both `create_serving_api_app()` and `create_build_api_app()` use `API_VERSION` for FastAPI
metadata instead of independent hard-coded strings. Route registration helpers use `API_PREFIX`
for canonical routes.

The serving and build apps register versioned aliases for health, readiness, stats, diagnostics,
runtime initialization, and domain operations where appropriate:

- `/v1/health`
- `/v1/health/live`
- `/v1/health/ready`
- `/v1/stats`
- `/v1/diagnostics`
- `/v1/runtime/serving/initialize`
- `/v1/runtime/serving/refresh`
- `/v1/runtime/build/initialize`
- `/v1/jobs`
- `/v1/jobs/{job_id}`
- `/v1/jobs/build`
- `/v1/jobs/rebuild`
- `/v1/artifacts`
- `/v1/knowledge-base/build`
- `/v1/knowledge-base/rebuild`

The root path `/` remains a health compatibility endpoint. Prometheus `/metrics`, docs, redoc, and
`/openapi.json` remain framework and tooling endpoints outside the `/v1` namespace.

## Response Models

The existing full answer payload model remains the debug response contract:

- `AnswerPayloadModel`
- `AnswerResponseModel`
- `AnswerStreamResultDataModel`

Add public response models that reuse the existing strict submodels but omit traces:

- `PublicAnswerPayloadModel`
- `PublicAnswerResponseModel`
- `PublicAnswerStreamResultDataModel`

The public payload includes:

- `summary`
- `grounding`
- `diagnostics`

The debug payload includes:

- `summary`
- `grounding`
- `diagnostics`
- `traces`

Both public and debug models are built from the same typed application response mapper. The public
mapper must drop `traces` at the API DTO boundary only; runtime and application DTOs remain
unchanged so trace capture, persisted traces, diagnostics, and debug routes keep their current
data.

Stable model boundaries continue to use `extra="forbid"`. Intentionally dynamic fields such as
metadata, evidence details, route-stage details, query plans, and graph event details keep their
existing JSON object shapes.

## Route Behavior

`/v1/answers` returns `PublicAnswerResponseModel`.

`/v1/debug/answers` returns `AnswerResponseModel`.

`/v1/answers/stream` emits SSE events where the `result` event contains a public response payload
without `traces`.

`/v1/debug/answers/stream` emits SSE events where the `result` event contains a debug response
payload with complete `traces`.

The compatibility `stream=true` flag on `/v1/answers` keeps returning public SSE. The existing
unversioned `/answers` compatibility route keeps its current behavior, including full traces, until
a separate retirement design changes it.

## Security and OpenAPI

The same authentication and request-size middleware applies to `/v1` and `/v1/debug` routes.
Debug routes are protected routes by default just like `/answers`, `/stats`, and build operations.

OpenAPI should expose separate schemas for public and debug answer responses. This makes the trace
boundary visible to generated clients and prevents accidental public-schema drift.

OpenAPI security metadata must clear public health routes for both unversioned health paths and
versioned health paths. Protected `/v1` and `/v1/debug` routes must keep the configured security
requirements.

## Documentation

Update README API examples and contract notes to identify `/v1` as the preferred client surface.
Document that public answer responses omit complete traces by default and that full traces are
available from `/v1/debug/answers` and `/v1/debug/answers/stream`.

The existing unversioned routes should be described as compatibility aliases rather than the
recommended surface.

## Testing

Use test-first implementation with focused API tests:

- `POST /v1/answers` returns a public payload with no `traces`.
- `POST /v1/debug/answers` returns the complete debug payload with `traces`.
- `POST /v1/answers` with `stream=true` emits public SSE result payloads without `traces`.
- `POST /v1/answers/stream` emits public SSE result payloads without `traces`.
- `POST /v1/debug/answers/stream` emits debug SSE result payloads with `traces`.
- OpenAPI exposes both public and debug answer response schemas.
- Serving `/v1/health`, `/v1/stats`, and management routes behave like their unversioned
  counterparts.
- Build `/v1/jobs`, `/v1/artifacts`, and build job operations behave like their unversioned
  counterparts.
- Both FastAPI apps use the shared `API_VERSION`.
- OpenAPI security metadata clears versioned health paths and keeps debug routes protected.

Run narrow tests first:

```powershell
python -m pytest tests/test_api_app.py tests/test_answer_response_mapping.py -q
```

Because the change affects the public API surface and documentation, also run:

```powershell
python -m pytest tests/test_entrypoints.py tests/test_public_api_manifest.py -q
python scripts/release_gate.py
```

Before completion, run the repository formatting hook or the closest available equivalent:

```powershell
pre-commit run --all-files
```

## Acceptance Criteria

- `/v1` is the canonical API prefix for serving and build operations.
- Serving and build apps share one API version constant.
- Public `/v1` answer responses do not include complete traces by default.
- Full traces are available only through explicit `/v1/debug/answers` and
  `/v1/debug/answers/stream` routes in the versioned surface.
- Existing unversioned routes remain available as compatibility aliases.
- OpenAPI distinguishes public and debug answer response schemas.
- README documents `/v1` and the public/debug trace boundary.
- Focused tests and release-sensitive checks pass, or any environment limitation is reported.

## Self-Review

- No placeholder requirements remain.
- The scope is limited to API contract governance and does not alter runtime trace semantics.
- The public/debug boundary lives at the API DTO layer, matching the existing architecture.
- The compatibility policy is explicit and avoids silently breaking old clients.
- Version constants and routes are concrete enough for an implementation plan.
