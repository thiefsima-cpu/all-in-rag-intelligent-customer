# Live Quality Interaction SLO and 0.4 Evidence Design

## Context

The last successful real-model record predates the current `0.4.0.dev0`
customer-service implementation. It covers 34 cases and reports a
21,413.888 ms full-response p95. The committed
`quality-evidence/live_quality_gate/20260708-203513/` report is a historical
failed attempt with `case_count=0`; it neither proves that the current code
fails nor provides current success evidence.

The repository has already advanced beyond the initially reported 47-case
baseline. The canonical `eval/live_quality_gate.json` policy contains 52
cases:

- 28 grounded answers;
- 17 no-evidence answers;
- 4 clarification answers;
- 3 constraint-conflict answers;
- 18 customer-service cases, including 5 grounded order, refund, warranty,
  invoice, and policy-version answers.

This work therefore keeps the 52-case corpus and focuses on making interactive
latency release-blocking, recording an independently observable rerank stage,
and producing current evidence without misrepresenting development evidence as
protected-tag release evidence.

## Goals

1. Run each live-quality case exactly once through the real streaming serving
   path while retaining the complete debug answer and trace contract.
2. Measure client-observed time to first token and full response, plus
   retrieval, rerank, and generation latency.
3. Enforce the following p95 budgets:
   - client-observed TTFT: at most 5,000 ms;
   - retrieval: at most 3,000 ms;
   - rerank: at most 2,000 ms;
   - generation: at most 20,000 ms;
   - client-observed full response: at most 25,000 ms.
4. Prevent missing events, missing trace fields, or disabled reranking from
   passing through zero-valued metrics.
5. Extend release-evidence validation so a future 0.4 release candidate must
   prove the same interaction SLOs.
6. Run the real-dependency integration gate and 52-case live-quality gate
   against the final clean implementation commit, retaining honest diagnostic
   evidence for `0.4.0.dev0`.

## Non-goals

- Adding more live-quality cases beyond the current 52-case corpus.
- Treating model-internal first-token latency as the customer-visible TTFT.
- Doubling model and judge calls by issuing separate streaming and non-streaming
  requests for the same case.
- Treating a development diagnostic snapshot as protected-tag release
  evidence.
- Broad retrieval, generation, or API refactoring unrelated to timing
  observability and gate enforcement.

## Chosen Approach

Each case uses the existing `POST /v1/debug/answers/stream` endpoint. This
endpoint returns model chunks and a final result containing the complete debug
answer payload. The gate therefore measures the interactive path and evaluates
quality from one model invocation.

The rejected alternatives are:

1. A non-streaming quality request plus a second streaming TTFT request. This
   doubles provider cost and permits the two observations to disagree.
2. Prometheus or OpenTelemetry scraping. Aggregate process metrics cannot
   reliably bind the measured latency to the current 52 cases or their final
   answers.

## Runtime Data Flow

For each case, the live-quality client:

1. Starts a monotonic timer immediately before posting the request.
2. Sends the case query to `/v1/debug/answers/stream` with route explanation
   enabled.
3. Parses SSE frames incrementally rather than assuming one HTTP chunk equals
   one event.
4. Records end-to-end TTFT at the first non-empty `chunk` event. Progress
   `message` events and empty chunks do not satisfy TTFT.
5. Accumulates model chunks for protocol consistency checks.
6. Requires exactly one `result` event and records client-observed full-response
   latency when that event arrives.
7. Requires a terminal `done` event and rejects any stream error.
8. Normalizes the debug answer in the result event into the existing quality
   observation, augmented with timing fields.
9. Runs deterministic scoring and the configured judge exactly once.

The final result trace provides:

- `route_trace.total_latency_ms` as retrieval-pipeline latency, including
  planning, retrieval strategies, and post-processing;
- explicit post-process rerank attempted, succeeded, and elapsed fields;
- `generation_trace.total_latency_ms` as generation latency;
- `generation_trace.first_token_latency_ms` as a diagnostic-only,
  model-executor measurement.

Client-observed TTFT is authoritative for the 5,000 ms interaction SLO because
it includes admission, SSE scheduling, routing, retrieval, reranking,
generation startup, and delivery to the HTTP client. The model-executor
first-token value remains visible to distinguish provider startup from
pre-generation and delivery overhead but does not decide release.

## Rerank Trace Contract

`RetrievalPostProcessor` gains a focused traced outcome containing:

- the final evidence documents;
- `rerank_attempted`;
- `rerank_succeeded`;
- `rerank_latency_ms`.

The existing document-only post-process entry point remains as a compatibility
wrapper. The routing orchestrator uses the traced entry point and records its
fields in the `post_process` route stage. The debug route-stage response model
exposes these fields explicitly rather than relying on permissive extra fields.

Rerank semantics are:

- no documents or no configured rerank client: not attempted;
- successful provider call: attempted and succeeded, with monotonic elapsed
  time;
- provider error: attempted but not succeeded, with elapsed time retained.

A failed rerank preserves the existing serving fallback to the original
documents, but marks the stage as retrieval-degraded with the safe source label
`rerank`. The existing zero-tolerance retrieval-degradation threshold then
blocks the live-quality gate.

## Observation and Report Contract

Each successful `LiveQualityObservation` contains:

- `ttft_ms`;
- `latency_ms`, redefined for the live gate as client-observed time through the
  unique result event;
- `retrieval_latency_ms`;
- `rerank_attempted`;
- `rerank_succeeded`;
- `rerank_latency_ms`, absent when rerank was not attempted;
- `generation_latency_ms`;
- `generation_first_token_latency_ms`, diagnostic only;
- the existing answer, evidence, route, fallback, degradation, token, and cost
  fields.

Each case report exposes these values in a dedicated `timings` object. Ranking
metrics remain separate so release-evidence validation can recompute both
quality and performance without conflating their applicability.

Aggregate metrics add:

- `p95_ttft_ms`;
- `p95_retrieval_latency_ms`;
- `rerank_observation_count`;
- `p95_rerank_latency_ms`, computed only from attempted and successful reranks;
- `p95_generation_latency_ms`;
- `p95_generation_first_token_latency_ms`, diagnostic only;
- the existing `p95_latency_ms`, now based on client-observed result latency.

The existing percentile helper remains the canonical calculation. Slice
summaries expose the same timing metrics for diagnosis, while only the global
interaction SLOs are initially release-blocking.

## Policy and Blocking Semantics

The live-quality policy adds these required thresholds:

- `maximum_p95_ttft_ms = 5000`;
- `maximum_p95_retrieval_latency_ms = 3000`;
- `maximum_p95_rerank_latency_ms = 2000`;
- `maximum_p95_generation_latency_ms = 20000`;
- `maximum_p95_latency_ms = 25000`.

It also requires at least one real successful rerank observation. This coverage
check prevents a disabled reranker or a missing trace field from satisfying the
2,000 ms threshold with a fabricated zero.

The new latency checks use `BUDGET_REGRESSION`. Missing, non-finite, negative,
or contract-default timing values are gate execution failures rather than valid
quality misses. Per-case deterministic or judge quality misses continue to be
governed by aggregate and slice quality thresholds; transport, event-protocol,
trace-contract, degradation, coverage, and budget failures remain immediately
release-blocking.

## Schema Evolution

The live-quality policy and report move to schema version 2 because the required
stream event and timing contract is incompatible with version 1 producers.
Tests and documentation explicitly retain the historical version 1 failed
report as diagnostic history.

Release-evidence capture and manifest schemas also move to version 2. The
quality projection includes every blocking p95 metric and rerank observation
count. Strict report validation:

- requires the exact version 2 aggregate and per-case timing keys;
- recomputes p95 metrics from case timings;
- verifies every policy check and threshold payload;
- rejects removed, extra, null-inapplicable, negative, non-finite, or
  inconsistent values;
- rejects a successful report with no real rerank observation;
- preserves dataset, profile, model suite, active knowledge-base, report,
  artifact, and evaluated-commit binding.

This is an intentional strict-schema change for the unreleased 0.4 line rather
than a silent expansion of the existing v1 contract.

## Failure Handling

The case runner emits a structured, release-blocking check when it encounters:

- an HTTP, connection, or request timeout failure;
- invalid content type or malformed SSE;
- an error event;
- no non-empty model chunk;
- duplicate or missing result events;
- a result after a terminal event;
- no terminal done event;
- a malformed debug answer;
- absent or invalid retrieval, rerank, generation, or internal first-token
  trace fields.

The service continues to the remaining cases so the report retains the full
diagnostic surface. Failed case requests have no observation, which also makes
the 52-case minimum fail. Unexpected collaborator return types remain gate
execution errors as today.

Judge transport and schema failures retain their current fail-closed behavior.
Judge latency does not contribute to answer TTFT or full-response latency
because judging happens after the serving response.

## Test Strategy

Implementation follows red-green-refactor cycles.

Focused tests cover:

- SSE frames split across arbitrary HTTP chunks;
- multiple events in one HTTP chunk;
- CRLF and LF framing;
- progress messages before the first non-empty model chunk;
- empty chunks;
- stream error, duplicate result, missing result, result-after-done, and
  missing done cases;
- client-observed TTFT and result latency from an injected monotonic clock;
- explicit route, rerank, generation, and diagnostic first-token fields;
- rerank not attempted, succeeded, and provider-failed outcomes;
- provider-failed rerank causing retrieval degradation;
- aggregate and slice p95 calculations;
- exact threshold boundary passes and over-budget failures;
- zero rerank observations failing coverage;
- report schema and Markdown output;
- release-evidence exact-key, recomputation, and tamper rejection;
- compatibility behavior for the document-only post-process wrapper.

Verification expands in this order:

1. focused retrieval post-process and live-quality tests;
2. API answer and SSE tests;
3. release-evidence tests;
4. the repository's API-related test slice;
5. the full test suite;
6. Ruff check and format verification;
7. `python scripts/release_gate.py`.

## Real-Model Execution and Evidence

Real execution occurs only after implementation, policy, tests, and
documentation form a clean final commit. The running API is built from that
exact HEAD with the customer-service domain, the current prepared knowledge
base, and the configured real embedding, rerank, generation, and judge models.

The execution order is:

1. verify dependency and serving readiness;
2. run the real-dependency integration gate;
3. run the 52-case live-quality gate;
4. inspect every failed check if either gate fails;
5. optimize only the responsible stage and repeat from a new clean commit when
   code or policy changes;
6. retain reports only after their final run;
7. record report and policy hashes, exact HEAD, model suite, profile, active
   knowledge-base identity, case counts, and all SLO values;
8. scan retained artifacts for credentials, authorization material, absolute
   private paths, tracebacks, and customer data.

The current `0.4.0.dev0` result is stored and documented as development
diagnostic evidence. It may prove the exact development commit exercised, but
it is not placed under the protected
`quality-evidence/releases/<version>/evidence-manifest.json` discovery path and
does not replace release-candidate capture. A future 0.4 RC or final release
must run the v2 release-evidence workflow again on its own immutable candidate
commit.

No success document is written unless both real gates pass, all 52 live cases
produce valid observations, every blocking quality and interaction SLO passes,
and the retained evidence identity matches the clean evaluated commit.

