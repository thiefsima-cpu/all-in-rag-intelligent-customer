# Answer Response Contract Design

## Goal

Tighten the public `/answers` response contract by replacing loose
`JsonObject` fields in answer grounding, diagnostics, and traces with Pydantic
models that mirror the runtime dataclass contracts already used by the
question-answer workflow.

The change should make the FastAPI schema useful to frontend clients and
operational tools without changing runtime behavior or broadening the current
API surface.

## Scope

This design covers:

- `POST /answers` JSON responses.
- `/answers/stream` and compatibility `stream=true` SSE `result` events.
- `AnswerPayloadModel` sub-models under `summary`, `grounding`,
  `diagnostics`, and `traces`.
- Focused tests for schema validation and existing API behavior.

This design does not cover:

- `/stats`, `/diagnostics`, health, build jobs, or artifact registry payloads.
- Internal question-answer workflow dataclasses.
- Query trace persistence format.
- Broad replacement of application-layer dataclasses with Pydantic models.

## Architecture

Keep the API layer as the contract boundary. The application service continues
to return `QuestionAnswerResponse.to_dict()`, and
`build_answer_response(...)` continues to validate that mapping through
`AnswerResponseModel`.

Add API response sub-models in `rag_modules/interfaces/api/models.py` that
mirror existing runtime contracts:

- Retrieval and grounding:
  - `EvidenceDocumentResponseModel`
  - `RetrievalOutcomeResponseModel`
  - `QueryUnderstandingSnapshotResponseModel`
  - `RouteResolutionResponseModel`
  - `AnswerContextResponseModel`
- Diagnostics:
  - `QueryAnalysisResponseModel`
  - `QueryDiagnosticsResponseModel`
- Traces:
  - `RouteStageSnapshotResponseModel`
  - `RouteDiagnosticsResponseModel`
  - `RouteSnapshotResponseModel`
  - `GraphTraceEventSnapshotResponseModel`
  - `GraphRetrievalSnapshotResponseModel`
  - `GenerationSnapshotResponseModel`
  - `ModelSuiteSnapshotResponseModel`
  - `RetrievalTraceSnapshotResponseModel`
  - `AnswerTraceSnapshotResponseModel`
  - `QueryTraceEventResponseModel`

These models should use `extra="forbid"` at stable object boundaries. Fields
that are intentionally open-ended remain `JsonObject`, including metadata,
evidence unit details, graph evidence maps, retrieval requests, query plans,
semantic profiles, evidence packages, and stage/event details.

`AnswerSummaryModel` should also include the token and cost fields that
`QuestionAnswerSummary.to_dict()` already emits:

- `prompt_tokens`
- `completion_tokens`
- `total_tokens`
- `estimated_cost_usd`
- `token_usage_source`

## Data Flow

The runtime flow stays unchanged:

1. `GraphRAGServingApiService.answer_question(...)` receives a
   `QuestionAnswerResponse` from the application.
2. The service calls `to_dict()`.
3. `build_answer_response(...)` validates the mapping with
   `AnswerResponseModel`.
4. FastAPI serializes the validated Pydantic model.

The SSE flow uses the same contract through
`AnswerStreamEventModel.result(...)`, which wraps the response mapping in
`AnswerPayloadModel.from_payload(...)`.

## Compatibility

The contract tightens object shapes but preserves field names and the existing
payload layout. Empty snapshots continue to serialize as objects with default
field values rather than disappearing.

Open-ended nested payloads remain allowed only where the runtime contracts are
already intentionally extensible:

- `metadata`
- `build_metadata`
- query plan and semantic profile structures
- evidence graph/details payloads
- retrieval request payloads
- route stage details and graph event details

Unknown fields at the main answer response object boundaries should fail
Pydantic validation. That failure is intentional because it catches accidental
public API drift before it reaches clients.

## Error Handling

No runtime error behavior changes. If an application result contains an invalid
answer response shape, the existing response-builder validation path raises the
Pydantic validation error during response construction.

SSE error events keep their current permissive `AnswerStreamErrorDataModel`
because exception payloads may carry contextual diagnostics from different
failure paths.

## Testing

Add or update focused tests in `tests/test_api_app.py` and, if cleaner, a small
model-level test module:

- Existing `/answers` and SSE result responses still validate and serialize.
- `AnswerResponseModel` rejects unknown fields under stable nested objects such
  as `summary`, `traces.generation_trace`, or `diagnostics.diagnostics`.
- `AnswerResponseModel` accepts the current fake answer payload after it is
  expanded to the runtime `to_dict()` shapes.
- Token and cost fields are present in the answer summary schema and response.

Run the narrow API tests first. If implementation only touches API models and
tests, run:

```powershell
python -m pytest tests/test_api_app.py -q
```

Before completion, also run the repository formatting/type gate appropriate to
the touched files, preferably:

```powershell
pre-commit run --all-files
```

If the local environment cannot run the full hook set, record the failure and
run the closest available Ruff or pytest checks.

## Acceptance Criteria

- Answer grounding, diagnostics, and trace payloads no longer use broad
  top-level `JsonObject` models where stable runtime contracts already exist.
- `POST /answers` and SSE `result` events share the same strict
  `AnswerPayloadModel`.
- Existing response field names and layout stay compatible.
- Stable nested response objects use `extra="forbid"`.
- Intentionally extensible metadata/detail fields remain JSON-shaped.
- Focused API tests prove both accepted current payloads and rejected unknown
  stable fields.

## Self-Review

- No placeholder requirements remain.
- Scope is limited to answer responses and SSE result events.
- The design reuses existing runtime dataclass contracts instead of inventing
  new semantics.
- Open-ended fields are explicitly listed so strictness does not accidentally
  block legitimate metadata.
