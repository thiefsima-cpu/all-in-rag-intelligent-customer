# Type Contract Ratchet Design

## Goal

Make mypy useful as a CI gate by creating the first strict type island around
runtime assembly and the retrieval/generation boundaries. The first slice
reduces `Any` where it hides real cross-module contracts, while keeping the
blast radius small enough to review and extend.

## Scope

This design covers:

- `rag_modules/app/runtime_state.py` and runtime view dataclasses.
- Provider contracts in `rag_modules/app/provider_components/contracts.py`.
- Retrieval/generation assembly ports that currently accept untyped runtime
  collaborators.
- Existing runtime, retrieval, and generation dataclasses that can replace
  loose payloads at these boundaries.
- A focused mypy ratchet for only the typed island.

This design does not make the whole repository strict, rewrite public API
models, change runtime behavior, or remove compatibility facades. Dynamic
payloads that are genuinely serialized trace or metadata data remain dictionary
based until a later ratchet step.

## Architecture

Add a narrow set of structural protocols for runtime collaborators. These
protocols describe what the application layer actually uses, rather than tying
assembly code to concrete infrastructure classes.

The initial protocols cover:

- Neo4j manager behavior: `driver`, `session(...)`, and `close()`.
- Graph data module behavior: graph loading, document/chunk materialization,
  statistics, close, and document/chunk state.
- Vector index behavior: collection name, collection readiness/load/delete,
  vector index build, collection stats, and close.
- Query tracer behavior: `record(...)`, `stats()`, and `close()`.
- Routing workflow behavior through the existing `RoutingWorkflowProtocol`.
- Generation behavior through `GenerationWorkflowService` or a matching
  protocol when a narrower port is cleaner.

`BuildRuntime`, `ServingRuntime`, and grouped runtime views use these protocols
instead of `Any`. Provider protocols use the same ports for parameters and
return values. Retrieval and generation factories keep concrete return types
where they already exist and replace loose collaborators with the smallest
useful protocol.

## Data Contracts

Use existing domain models before adding new ones:

- `RetrievalRequest` and `EvidenceDocument` remain the retrieval request and
  evidence contracts.
- `QueryAnalysis`, `QueryUnderstandingSnapshot`, `RouteResolution`, and
  `AnswerContext` remain the cross-stage runtime contracts.
- `GenerationSettings`, `RenderedPrompt`, `AnswerPlan`, and
  `GenerationTrace` remain generation contracts.

Analysis inputs that currently flow as raw `Any` should normalize at the
boundary. Public compatibility methods may accept `QueryAnalysis`,
`Mapping[str, object]`, or `None`, then call the existing normalization helpers.
Internal generation decisions and execution should prefer `QueryAnalysis | None`
once normalization is complete.

Metadata and trace dictionaries remain typed as `dict[str, object]` only when
they are intentionally open-ended. The first slice should avoid broad
`dict[str, Any]` in new or touched contracts unless the value is a true adapter
escape hatch.

## Mypy Ratchet

Keep the repository baseline unchanged for now, then add targeted mypy override
sections for the first typed island. The initial strict flags should include:

- `check_untyped_defs = true`
- `disallow_untyped_defs = true`
- `warn_return_any = true`
- `warn_unused_ignores = true`
- `no_implicit_optional = true`

The first checked module set should include runtime state/views, provider
contracts, and the focused retrieval/generation port files touched by the
implementation. Later ratchets can expand this module list without weakening
the first island.

The CI command should continue to be `python -m mypy` so the gate uses the
project config. The local development environment must install the `dev` extra
or run the repository bootstrap before the gate can execute.

## Error Handling

The type-contract work does not change runtime error behavior. Adapter methods
that can fail continue to return their current booleans, dictionaries, or raise
the same exceptions as before.

Where compatibility inputs are accepted as mappings, invalid shapes are
normalized through existing helper methods such as `ensure_query_analysis`,
`RetrievalRequest.from_dict`, and `EvidenceDocument.from_dict`.

## Testing

Add focused contract tests that fail before implementation where practical:

- Runtime dataclasses expose protocol-typed fields without losing current
  initialization behavior.
- Provider contracts accept concrete default providers under mypy.
- Generation analysis inputs normalize to `QueryAnalysis` before internal
  decision logic.
- Retrieval candidate/runtime ports type-check against the concrete hybrid
  runtime implementation.

Run the narrow behavior tests for changed modules, then run the focused mypy
gate. If the local environment lacks mypy, record that explicitly and run the
available narrow pytest set.

## Acceptance Criteria

- The first typed island has no `Any` for runtime state fields or provider
  boundary collaborators that have stable behavior.
- Existing dataclass and protocol contracts are reused instead of introducing
  duplicate shapes.
- `python -m mypy` checks the first typed island with meaningful strict flags.
- Existing behavior tests for runtime assembly, retrieval, and generation still
  pass.
- The design leaves a clear ratchet path for expanding mypy coverage without
  weakening the current baseline.
