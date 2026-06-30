# Answer Public/Debug Field Contract Design

## Goal

Define a field-level boundary between public answer responses and debug answer
responses so internal RAG runtime structures can evolve without becoming `/v1`
API compatibility obligations.

## Scope

This design covers:

- `POST /v1/answers`
- `POST /v1/answers/stream`
- `POST /v1/debug/answers`
- `POST /v1/debug/answers/stream`
- Answer response OpenAPI schemas and model-level mapping tests.

It does not change runtime answer DTOs, query trace persistence, retrieval,
generation, or build API behavior.

## Chosen Contract

Debug answer routes keep the complete existing `AnswerPayloadModel`:

- `summary`
- `grounding`
- `diagnostics`
- `traces`

The debug payload remains the operational introspection surface. It may expose
route traces, graph traces, generation traces, query plans, semantic profiles,
retrieval requests, evidence units, graph evidence maps, metadata, and policy
snapshots.

Public answer routes use a separate `PublicAnswerPayloadModel`:

- `summary`: final answer, status, strategy, latency, evidence count, fallback,
  failure code, token usage, cost estimate, and sanitized error code.
- `grounding.evidence_documents`: citation fields only: `content`,
  `recipe_name`, `score`, `source`, `evidence_type`, and `matched_terms`.
- `diagnostics`: stable health and degradation fields only:
  `retrieval_bucket`, `generation_bucket`, `overall_bucket`,
  `retrieval_degraded`, `degraded_sources`, `degraded_candidates`,
  `circuit_breaker_triggered`, `answer_impacted`, and `failure_reasons`.

Public responses intentionally exclude:

- `traces`
- `grounding.retrieval_outcome`
- `grounding.answer_context`
- `grounding.route_resolution`
- `diagnostics.analysis`
- query plans and semantic profiles
- retrieval requests
- graph evidence maps and evidence units
- open-ended metadata bags
- route, graph, generation, and query trace snapshots

## Architecture

Keep the boundary in `rag_modules/interfaces/api/answer_models.py`.
Application-layer dataclasses still produce the complete typed
`QuestionAnswerResponse`. The API layer maps that response into either the
debug schema or the public schema.

The public schema must not reuse debug submodels for grounding or diagnostics.
Instead it owns:

- `PublicEvidenceDocumentResponseModel`
- `PublicAnswerGroundingModel`
- `PublicAnswerDiagnosticsModel`
- `PublicAnswerPayloadModel`
- `PublicAnswerResponseModel`

`PublicAnswerPayloadModel.from_dto()` maps directly from application DTOs.
`PublicAnswerPayloadModel.from_debug_payload()` maps from an already-validated
debug payload into the same public shape for SSE and response-builder reuse.

## Error Handling

No runtime error behavior changes. Public summaries continue to expose only the
sanitized answer error code. Degraded candidate details continue to be reduced
to safe source, error code, and error type fields.

## Testing

Focused tests should prove:

- Public model mapping excludes debug-only grounding, diagnostics, and traces.
- Public model validation rejects debug-only fields if they are injected.
- `/v1/answers` and `/v1/answers/stream` return the public field contract.
- `/v1/debug/answers` and `/v1/debug/answers/stream` keep the debug payload.
- OpenAPI exposes dedicated public grounding, diagnostics, and evidence schemas.

Run:

```powershell
python -m pytest tests/test_answer_response_mapping.py tests/test_api_app.py -q
```

Because this changes the public HTTP contract, also run public-surface and
release-sensitive checks before declaring completion.

## Self-Review

- No placeholder requirements remain.
- Public and debug payloads are separate schema contracts, not one schema with
  selectively omitted fields.
- The public contract is narrow enough that future route, plan, graph, and
  evidence internals can change without breaking `/v1` clients.
