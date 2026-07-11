# API Capacity And Pressure Thresholds Design

## Context

The serving API already has explicit answer admission control, bounded SSE
runner settings, query trace backpressure metrics, model usage telemetry, and
public retrieval degradation diagnostics. The remaining gap is operational:
capacity assumptions, local pressure scenarios, and pass/fail thresholds are not
captured as a versioned contract. `scripts/pressure_api_service.py` reports raw
admission and trace metrics, but it does not explain whether a run is healthy,
which capacity dimension failed, or how the result relates to API concurrency,
SSE, model calls, and retrieval degradation.

This change turns capacity planning into a first-class local artifact. It
documents the model, replaces the current pressure-test output with a structured
scenario/check contract, and adds deterministic tests for the threshold engine.

## Goals

- Document API concurrency, SSE, model-call, and retrieval-degraded capacity
  models in one operator-facing guide.
- Refactor `scripts/pressure_api_service.py` around explicit pressure scenarios,
  metrics, thresholds, checks, and an overall status.
- Make JSON output directly answer whether the run passed, warned, or failed.
- Keep local pressure runs deterministic and independent of Neo4j, Milvus, and
  live model providers.
- Add focused tests for threshold boundaries and the new JSON contract.
- Treat the refactor as a clean replacement of the old script shape, not a
  compatibility layer around the previous summary.

## Non-goals

- Do not add release-gate or local-gate enforcement for host-dependent capacity
  results.
- Do not call real model providers, Neo4j, Milvus, or external services from the
  pressure script.
- Do not change production answer, retrieval, generation, SSE, or API response
  semantics.
- Do not preserve the old pressure JSON contract at top level. Existing tests
  should move to the new contract.
- Do not introduce a new runtime dependency.

## Capacity Model

### API Answer Concurrency

The serving API bounds combined non-streaming and streaming answer work through
`api.max_concurrent_answers`. Capacity should be planned with Little's Law:

```text
required_answer_permits = ceil(target_rps * target_p95_latency_seconds * headroom)
```

Use a headroom factor of `1.25` for normal load and `1.5` for noisy production
dependencies. If `required_answer_permits` exceeds the configured admission
limit, either lower the target RPS, reduce latency, raise the limit, or add more
API replicas. `api.answer_acquire_timeout_seconds` should be shorter than the
client timeout and long enough to absorb brief bursts; local pressure defaults
continue to use `0.25s`.

Baseline threshold intent:

- no admission rejections under the baseline scenario;
- bounded p95 latency for completed requests;
- trace drops stay within the configured backpressure budget;
- throughput remains above the minimum derived from request count and answer
  delay.

Saturation threshold intent:

- admission rejections are expected and must be reported as controlled
  backpressure;
- completed request p95 remains bounded because rejected requests do not wait
  behind unbounded work;
- completed plus rejected requests equals attempted requests.

### SSE Runner Capacity

SSE work consumes the same answer permits as JSON answers and also consumes
`api.stream_executor_max_workers` background threads. The effective streaming
answer capacity per process is:

```text
effective_stream_capacity = min(max_concurrent_answers, stream_executor_max_workers)
```

`api.stream_queue_max_size` is per stream. Memory grows with active streams, so
operators should reason about:

```text
max_stream_event_buffer = active_streams * stream_queue_max_size
```

The local script should model SSE as a separate deterministic scenario rather
than by opening real HTTP streams. It can exercise the same service-level stream
runner and record:

- active stream workers;
- terminal `done` events;
- rate-limited error events;
- cancellation count for closed consumers.

Queue depth is intentionally not a required script metric because the current
runner treats queue internals as implementation detail. The capacity guide still
documents the buffer formula so operators can size `stream_queue_max_size`.

### Model Calls

Model capacity is governed by provider latency, token volume, and cost. The
application already records provider latency and usage when generation executes.
The local pressure script should not call a provider; instead it should accept
synthetic model latency and token settings so the threshold contract remains
deterministic.

Capacity planning formulas:

```text
model_required_concurrency = ceil(target_rps * model_p95_latency_seconds * headroom)
estimated_cost_usd =
  input_tokens / 1_000_000 * input_cost_per_million +
  output_tokens / 1_000_000 * output_cost_per_million
```

Threshold checks should cover:

- model p95 latency stays below the configured generation budget;
- token usage stays below a per-request budget;
- estimated cost stays below a per-run budget;
- fallback or degraded generation rate stays below the allowed rate.

### Retrieval Degraded

Retrieval degraded is a controlled partial-success signal, not a generic error.
Capacity thresholds should count both rate and source concentration:

```text
retrieval_degraded_rate = degraded_answer_count / completed_answer_count
degraded_source_rate[source] = degraded_source_count[source] / completed_answer_count
```

The default local threshold should allow `0` degraded retrieval cases in the
healthy baseline. A dedicated degraded scenario should inject deterministic
degraded source diagnostics and verify that the script classifies the run as a
warning or failure according to configured limits.

Suggested policy:

- baseline: `retrieval_degraded_rate == 0`;
- warning: degraded rate above baseline but at or below `2%`;
- failure: degraded rate above `5%` or any single dependency dominates degraded
  cases above `3%`;
- source-specific failures should identify `vector`, `bm25`, `graph`, or the
  safe public source name returned by diagnostics.

## Pressure Script Architecture

Refactor the script into focused units:

- `PressureScenario`: immutable scenario settings such as request count,
  workers, answer delay, stream mode, synthetic model latency, and deterministic
  degraded injection.
- `PressureMetrics`: raw measured values such as completed requests, rejected
  requests, p95 latency, throughput, trace stats, model usage, and retrieval
  degradation counts.
- `PressureThresholds`: numeric policy for one scenario.
- `PressureCheck`: one threshold evaluation with `name`, `status`, `actual`,
  `limit`, `operator`, and `message`.
- `PressureReport`: top-level output with schema version, scenario, metrics,
  thresholds, checks, and final status.

`run_pressure_test(...)` should return `PressureReport`. CLI flags should choose
or override a scenario, then print the report. The previous ad hoc top-level
summary fields should be removed from JSON output. Human-readable output should
render the same report sections instead of maintaining a second result model.

## JSON Contract

The new JSON output should be shaped like:

```json
{
  "schema_version": 1,
  "scenario": {
    "name": "api_concurrency_baseline",
    "requests": 200,
    "workers": 16
  },
  "status": "pass",
  "metrics": {
    "completed_requests": 200,
    "rejected_requests": 0,
    "rejection_rate": 0.0,
    "throughput_rps": 50.0,
    "p95_latency_ms": 80.0,
    "trace": {
      "dropped_events": 0,
      "written_events": 200
    },
    "model": {
      "p95_latency_ms": 0.0,
      "estimated_cost_usd": 0.0
    },
    "retrieval": {
      "degraded_rate": 0.0,
      "degraded_source_counts": {}
    }
  },
  "thresholds": {
    "max_rejection_rate": 0.0,
    "max_p95_latency_ms": 250.0,
    "max_trace_dropped_events": 0,
    "max_retrieval_degraded_rate": 0.0
  },
  "checks": [
    {
      "name": "rejection_rate",
      "status": "pass",
      "actual": 0.0,
      "operator": "<=",
      "limit": 0.0,
      "message": "Admission rejections are within the scenario budget."
    }
  ]
}
```

Allowed report statuses are `pass`, `warn`, and `fail`. Any failed check makes
the report `fail`; otherwise any warning check makes it `warn`; otherwise the
report is `pass`.

## Default Scenarios

### `api_concurrency_baseline`

Purpose: prove configured answer admission can serve ordinary local load without
uncontrolled rejection.

Default thresholds:

- `max_rejection_rate = 0.0`;
- `max_p95_latency_ms = 250.0`;
- `min_completed_requests = requests`;
- `max_trace_dropped_events = 0`;
- `max_retrieval_degraded_rate = 0.0`.

### `api_concurrency_saturation`

Purpose: prove overload becomes controlled backpressure.

Default thresholds:

- `min_rejection_rate = 0.05`;
- `max_p95_latency_ms = answer_delay_ms + answer_acquire_timeout_ms + 150`;
- `request_accounting_must_balance = true`;
- `max_trace_failed_events = 0`.

### `sse_runner_capacity`

Purpose: prove stream executor and admission limits produce terminal SSE events
under load.

Default thresholds:

- `max_rate_limited_error_rate = expected_rate_limit_budget`;
- `min_done_event_rate = 1.0`;
- `max_unfinished_streams = 0`;
- `max_cancelled_after_done = 0`.

### `model_call_budget`

Purpose: model capacity and cost with deterministic synthetic latency and token
usage.

Default thresholds:

- `max_model_p95_latency_ms = generation_latency_budget_seconds * 1000`;
- `max_tokens_per_request = configured scenario budget`;
- `max_estimated_cost_usd = configured scenario budget`;
- `max_generation_degraded_rate = 0.0`.

### `retrieval_degraded_budget`

Purpose: verify degraded retrieval is visible and classified.

Default thresholds:

- `warn_retrieval_degraded_rate = 0.02`;
- `max_retrieval_degraded_rate = 0.05`;
- `max_single_source_degraded_rate = 0.03`;
- baseline runs keep `max_retrieval_degraded_rate = 0.0`.

## Documentation

Add `docs/api_capacity_and_pressure_thresholds.md` as the operator-facing guide.
It should include:

- capacity formulas and how to map them to `profiles/*.toml` API settings;
- a scenario table with purpose, command, and expected status;
- metric definitions for API, SSE, model, trace, and retrieval-degraded fields;
- guidance for interpreting pass, warn, and fail;
- a clear note that host-dependent pressure results are not part of the offline
  release gate.

Update README with a short link from the common pressure command section to the
new guide.

## Testing Strategy

Add focused tests in `tests/test_pressure_api_service.py`:

- threshold equality passes for maximum and minimum limits;
- values outside limits fail with the expected check name;
- warning limits produce `warn` when no failures exist;
- report status aggregation prefers `fail` over `warn` over `pass`;
- JSON output contains `schema_version`, `scenario`, `metrics`, `thresholds`,
  `checks`, and `status`;
- the saturation scenario still reports admission rejections and balanced
  request accounting.

Run:

```powershell
python -m pytest tests/test_pressure_api_service.py -q
python scripts/pressure_api_service.py --json
```

If README or docs formatting checks are available through pre-commit, run the
repo's normal formatting gate before final delivery.

## Files And Boundaries

- `docs/api_capacity_and_pressure_thresholds.md`: new operator guide.
- `scripts/pressure_api_service.py`: replace summary-oriented script internals
  with scenario, metrics, thresholds, checks, and report models.
- `tests/test_pressure_api_service.py`: update tests to the new report
  contract and threshold behavior.
- `README.md`: short link to the new guide from the pressure command section.

No production package changes are expected unless implementation reveals that a
service-level metric is impossible to observe through the current pressure
harness. In that case, prefer extending the local harness over changing public
API behavior.

## Acceptance Criteria

- The capacity guide documents API concurrency, SSE, model-call, and retrieval
  degraded formulas and thresholds.
- `run_pressure_test(...)` returns a structured `PressureReport` with
  deterministic threshold checks.
- JSON output has the new schema and does not preserve the old top-level summary
  shape.
- Baseline and saturation pressure tests exercise admission behavior and classify
  results through checks.
- Retrieval degraded and model-call thresholds can be evaluated without live
  dependencies.
- Focused pressure tests pass.
- A default `python scripts/pressure_api_service.py --json` run emits a report
  with an overall `pass`, `warn`, or `fail` status.
