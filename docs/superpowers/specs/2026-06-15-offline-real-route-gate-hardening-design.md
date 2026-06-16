# Offline Real-Route Gate Hardening Design

## Goal

Strengthen the deterministic release gate so the existing real-route answer
pipeline smoke suite verifies integration contracts, not only happy-path answer
snapshots. The gate must remain offline, repeatable, and suitable for ordinary
PR and release checks.

## Current Context

`scripts/release_gate.py` runs five deterministic suites and enforces 100%
pass rate. The strongest integration-like suite today is
`answer_pipeline_real_route`, which uses the real `IntelligentQueryRouter` and
`AnswerWorkflow`, but still supplies static hybrid and graph retrieval fixtures
plus a dummy LLM client. This is intentional: the release gate should not call
DashScope, Milvus, Neo4j, or other external services.

The current real-route smoke checks strategy, stage names, generation mode,
selected graph trace fields, answer text, and trace-event consistency. It does
not yet expose suite-level quality metrics for plan, request, trace, and
evidence contracts. A regression could preserve the visible strategy while
dropping important integration payloads from `RetrievalRequest`, `QueryPlan`,
route trace, graph trace, or emitted trace events.

## Recommended Approach

Harden the existing offline real-route suite with contract checks and metrics.
Keep all test doubles local to the suite, but assert that the real router and
answer workflow produce complete integration artifacts across the pipeline.

This is narrower than adding a live integration gate. A live gate can be added
later as a manually triggered release check, but this change focuses on the
default deterministic gate.

## Suite Contracts

Each `answer_pipeline_real_route` case should validate these contracts:

- The query planner path is offline-safe: the dummy LLM planner is not called,
  and the resulting plan records the expected graph query type when one is
  expected.
- `RetrievalRequest` carries the original query, effective candidate sizing,
  and a `QueryPlan` for routed requests.
- Route trace strategy, stages, diagnostics, request payload, and plan payload
  stay aligned with the answer response.
- Graph and combined cases include graph trace request, plan, events, document
  count, and graph evidence units.
- Hybrid-only cases do not fabricate graph trace details.
- Emitted trace events agree with the answer response for strategy, document
  count, and plan graph query type.

Failures should be case-local and explicit so regressions are readable from
the release-gate report.

## Metrics And Policy

The suite should return a `metrics` object with deterministic rates:

- `plan_contract_pass_rate`
- `request_contract_pass_rate`
- `trace_contract_pass_rate`
- `graph_contract_pass_rate`
- `evidence_contract_pass_rate`
- `offline_planner_guard_pass_rate`

`eval/release_gate.json` should gate these metrics at `1.0` for
`answer_pipeline_real_route`. The existing case-count and pass-rate checks stay
in place. These metric thresholds make contract regressions visible even when a
case still returns the expected strategy and answer text.

## Test Coverage

Focused tests should cover both success and failure behavior:

- The default real-route corpus passes and reports all contract metrics at
  `1.0`.
- The release gate fails when a required real-route metric falls below policy.
- A malformed or incomplete suite result produces a readable metric-threshold
  failure.

Existing release-gate report writing should not need a new format. JSON already
contains checks and failed checks; markdown summaries can continue listing
failed metric thresholds through the existing failed-check mechanism.

## Non-Goals

This design does not add a live DashScope, Milvus, or Neo4j gate. It does not
change retrieval algorithms, generation behavior, query-planner heuristics, or
the release gate's offline guarantee. It also does not replace the curated eval
script; it only makes the default real-route smoke stricter.

## Completion Criteria

The work is complete when:

- `answer_pipeline_real_route` validates plan, request, trace, graph, evidence,
  and offline-planner contracts per case.
- The suite exposes deterministic contract metrics.
- The default release policy gates those metrics at `1.0`.
- Tests prove the policy catches real-route contract regressions.
- The offline release gate still passes without external services.
