# Runtime, Trace, and Answer API DTO Convergence Design

## Goal

Remove dictionary-shaped handoffs from the question-answer response path so stable runtime and
trace contracts remain typed until the FastAPI boundary.

The target flow is:

```text
runtime DTO -> application response DTO -> API Pydantic model -> JSON
```

Existing `to_dict()` methods remain available for compatibility and final serialization, but the
application and API response path must not use them to move data between DTOs.

## Scope

This design covers the vertical answer path through:

- Runtime workflow contracts such as `RetrievalOutcome`, `AnswerContext`, and `RouteResolution`.
- Route, graph, generation, and query trace snapshots.
- Application response contracts in `rag_modules/app/services/answer_models.py`.
- `POST /answers` and answer SSE `result` events.
- Focused type-contract ratchets for the modules changed by this slice.

This design does not cover:

- Artifact manifest or build metadata contracts.
- General configuration parsing or infrastructure adapter payloads.
- Every open-ended evidence, query-plan, or graph detail object.
- Removal of public `to_dict()` or `from_dict()` compatibility methods.
- Public JSON field renames, response layout changes, or new API behavior.

## Chosen Approach

Application response DTOs hold the existing runtime and trace DTOs directly. The API layer owns
explicit mappers from those application DTOs to the existing Pydantic response models.

This keeps three concerns separate:

- Runtime models describe workflow state and trace snapshots.
- Application models describe the answer service result and response grouping.
- API models describe the validated HTTP and SSE schema.

The alternatives were rejected for this slice:

- Returning `QuestionAnswerResult` directly to the API would make the HTTP layer understand
  workflow assembly and summary derivation.
- Reusing API Pydantic models throughout runtime would make runtime and application code depend on
  the FastAPI boundary and its serialization framework.

## Application DTO Contracts

`QuestionAnswerResult` remains the terminal workflow result. `QuestionAnswerResponse` remains the
application-facing response, with its grouped DTOs changed from dictionaries to explicit types.

`QuestionAnswerGrounding` contains:

- `RetrievalOutcome`
- `AnswerContext`
- `RouteResolution`
- `list[EvidenceDocument]`

`QuestionAnswerDiagnostics` contains:

- `QueryAnalysis | None`
- `QueryDiagnostics`

`QuestionAnswerTraces` contains:

- `RouteSnapshot`
- `GraphRetrievalSnapshot`
- `GenerationSnapshot`
- `QueryTraceEvent`

`QuestionAnswerResponse.from_result()` derives its summary from `QuestionAnswerResult`, then moves
the existing typed contracts into the grouped response. In particular, it reads diagnostics from
`result.trace_event.diagnostics`; it does not serialize the event and parse the resulting mapping.

Response construction happens at the terminal workflow boundary. The response owns the completed
DTO graph by convention, and the workflow must not mutate those objects after it returns. This
preserves the current observable response behavior without adding broad deep-copy machinery or a
new family of duplicate snapshot types.

## API Mapping

The answer API Pydantic models gain explicit typed construction methods. The root mapping entry is
`AnswerPayloadModel.from_dto(response: QuestionAnswerResponse)`; nested models use their own
`from_dto()` methods where that keeps the mapping small and independently testable.

The mapper copies stable scalar and collection fields explicitly and recursively maps nested DTOs.
It does not use:

- `to_dict()` as an intermediate representation.
- Reflection over dataclass fields.
- A broad `Any` input.
- `model_validate()` over an application-layer dictionary.

The ordinary answer flow returns an `AnswerPayloadModel` from the API service and wraps it in
`AnswerResponseModel` at the route response builder. The SSE `result` event uses the same
`AnswerPayloadModel.from_dto()` mapping path. Both surfaces therefore validate and serialize the
same response contract.

`QuestionAnswerResponse.to_dict()` remains a supported compatibility serializer. It may call the
typed child serializers because that method is itself a final serialization boundary; application
workflow and API mapping code must not call it.

## Dynamic JSON Boundaries

Stable response objects use explicit DTO fields. Open-ended values remain JSON-shaped only where
the payload is intentionally extensible:

- Runtime metadata.
- Query-plan and semantic-profile extension data.
- Evidence package and evidence-unit details.
- Graph event and route stage details.
- Degradation candidate provider details.

Touched runtime fields use the shared `JsonObject` and `JsonValue` aliases instead of
`dict[str, Any]`. Deserialization boundaries accept `Mapping[str, object]` and normalize dynamic
values with the existing JSON coercion helpers. This distinguishes an intentionally dynamic JSON
object from an untyped escape hatch.

The slice does not introduce a DTO for every dynamic detail body. A detail object becomes a new DTO
only when its field set is stable and consumed as a contract by more than one component.

## Compatibility and Error Handling

The public answer payload keeps its current field names, nesting, defaults, and values. Existing
Pydantic `extra="forbid"` rules remain in effect for stable objects. Intentionally open detail and
metadata objects retain their current permissive JSON shapes.

Invalid stable response data continues to fail during Pydantic response construction. Runtime
mapping and normalization retain current defaulting behavior; this refactor does not add a new
silent fallback path or change application exceptions.

The compatibility `to_dict()` methods and persisted query trace JSON format remain available and
keep their existing output shapes.

## Type Contract Ratchet

Extend `tests/test_type_contract_ratchets.py` to cover the application response module and the
runtime/trace modules changed by this slice. Those targets must not contain explicit `Any` names.

Dynamic values in those files must be represented as `JsonObject`, `JsonValue`, `object`, or a
specific DTO. This ratchet is deliberately limited to the vertical answer path and does not claim
that unrelated adapters or configuration loaders are already strict.

## Testing

Use focused tests to prove both structure and behavior:

- Application response groups store the expected runtime and trace DTO instances.
- `QuestionAnswerResponse.from_result()` reads `QueryDiagnostics` directly from the trace event.
- Compatibility `to_dict()` output remains equal to the pre-change payload shape.
- `AnswerPayloadModel.from_dto()` produces the expected Pydantic object for a complete answer.
- Ordinary answer and SSE `result` responses serialize to the same payload contract.
- API mapping succeeds when runtime DTO `to_dict()` methods are patched to raise, proving that the
  internal response path no longer depends on dictionary handoffs.
- Unknown fields on stable API response models remain rejected.
- The type-contract ratchet rejects a reintroduced explicit `Any` in the changed boundary modules.

Run the narrow model and workflow tests first, followed by the full API tests. Because the change
crosses runtime, trace, application, and API boundaries, also run the repository mypy and Ruff or
pre-commit checks. Run `python scripts/release_gate.py` before declaring the implementation ready.

## Acceptance Criteria

- `QuestionAnswerGrounding`, `QuestionAnswerDiagnostics`, and `QuestionAnswerTraces` no longer
  store stable runtime contracts as dictionaries.
- `QuestionAnswerResponse.from_result()` performs no DTO-to-dictionary-to-DTO conversion.
- Ordinary answer responses and SSE `result` events share one typed API mapper.
- The API response path does not call runtime or application `to_dict()` methods.
- Existing public answer JSON and persisted trace JSON shapes remain compatible.
- Intentionally dynamic values use explicit JSON aliases rather than broad `Any`.
- Focused tests, API tests, type checks, formatting checks, and the release gate pass or any
  environment-specific limitation is reported explicitly.

## Self-Review

- The scope is limited to the runtime-to-trace-to-answer-API vertical path.
- Artifact metadata remains explicitly deferred to a later slice.
- Compatibility and ownership rules are explicit.
- Stable DTOs and intentionally dynamic JSON values are distinguished.
- No placeholder requirements or unresolved design choices remain.
