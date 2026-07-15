# API Capacity And Pressure Thresholds

This guide explains how to size and verify the serving API for answer
concurrency, SSE streams, synthetic model-call budgets, and retrieval degraded
signals. The pressure tool is local and deterministic. It does not call model
providers, Neo4j, Milvus, or other external services.

Host-dependent pressure results are not part of the offline release gate. Use
them as local evidence when changing API admission, stream execution, generation
budgets, retrieval diagnostics, or deployment profiles.

The default baseline is intentionally scheduler-neutral: its four workers match
the four answer permits and its in-memory trace sink adds no synthetic delay.
Use the saturation scenario or explicit trace-delay flags when testing overload
and trace backpressure.

## Capacity Formulas

### API Answer Concurrency

The serving API uses `api.max_concurrent_answers` to bound combined JSON answer
requests and SSE answer work.

```text
required_answer_permits = ceil(target_rps * target_p95_latency_seconds * headroom)
```

Use `headroom = 1.25` for normal load and `headroom = 1.5` when upstream
dependencies are noisy. If required permits exceed the configured limit, reduce
target RPS, reduce p95 latency, raise the limit, add replicas, or split traffic.

`api.answer_acquire_timeout_seconds` controls how long a request waits for an
answer permit. It should be shorter than the client timeout and long enough to
absorb brief bursts.

### SSE Runner Capacity

SSE streams consume answer permits and stream executor workers.

```text
effective_stream_capacity = min(max_concurrent_answers, stream_executor_max_workers)
max_outstanding_sse_tasks = stream_executor_max_outstanding
max_stream_event_buffer = outstanding_streams * stream_event_queue_max_size
```

`api.stream_executor_max_outstanding` must be greater than or equal to
`api.stream_executor_max_workers`. It bounds running plus submitted SSE tasks;
when the bound is full, new streams receive `RATE_LIMITED` immediately instead
of waiting in the standard executor's unbounded internal queue.

The event queue is per accepted stream. Size `api.stream_event_queue_max_size`
for slow consumers, and size `api.stream_executor_max_workers` with the same
headroom used for answer permits.

### Model Calls

The pressure tool uses synthetic latency and token settings for model budget
checks.

```text
model_required_concurrency = ceil(target_rps * model_p95_latency_seconds * headroom)
estimated_cost_usd =
  input_tokens / 1_000_000 * input_cost_per_million +
  output_tokens / 1_000_000 * output_cost_per_million
```

Use live observability metrics for real provider latency and cost. Use the local
pressure scenario to keep threshold logic reviewable without external calls.

### Retrieval Degraded

Retrieval degraded is a controlled partial-success signal.

```text
retrieval_degraded_rate = degraded_answer_count / completed_answer_count
degraded_source_rate[source] = degraded_source_count[source] / completed_answer_count
```

The healthy baseline expects `0` degraded retrieval cases. Dedicated degraded
budget scenarios classify small controlled degradation as `warn` and larger or
single-source concentrated degradation as `fail`.

## Pressure Scenarios

| Scenario | Purpose | Example command | Expected status |
| --- | --- | --- | --- |
| `api_concurrency_baseline` | Prove ordinary local load completes without admission rejection. | `python scripts/pressure_api_service.py --json` | `pass` on a healthy local machine |
| `api_concurrency_saturation` | Prove overload becomes controlled backpressure. | `python scripts/pressure_api_service.py --json --scenario-name api_concurrency_saturation --requests 12 --workers 4 --answer-delay-ms 50 --max-concurrent-answers 1 --answer-acquire-timeout-seconds 0.01` | `pass`, `warn`, or `fail` with explicit checks |
| `sse_runner_capacity` | Prove running plus submitted SSE work is bounded and rejected streams terminate cleanly. | `python scripts/pressure_api_service.py --json --scenario-name sse_runner_capacity --requests 8 --workers 6 --answer-delay-ms 50 --max-concurrent-answers 1 --answer-acquire-timeout-seconds 0.01 --stream-executor-max-workers 1 --stream-executor-max-outstanding 2 --stream-event-queue-max-size 4` | `pass` with bounded peaks, balanced rejection accounting, and zero final executor activity |
| `model_call_budget` | Evaluate synthetic provider latency, token, and cost budgets. | `python scripts/pressure_api_service.py --json --scenario-name model_call_budget --synthetic-model-latency-ms 35 --synthetic-input-tokens-per-request 100 --synthetic-output-tokens-per-request 50` | `pass` when synthetic budget checks stay within limits |
| `retrieval_degraded_budget` | Verify degraded retrieval is counted and classified. | `python scripts/pressure_api_service.py --json --scenario-name retrieval_degraded_budget --requests 120 --workers 2 --answer-delay-ms 1 --trace-delay-ms 0 --trace-queue-size 8 --max-concurrent-answers 2 --answer-acquire-timeout-seconds 0.25 --retrieval-degraded-every 40` | `warn` at a 2.5% injected degraded rate, below the 5% fail budget and above the 2% warning budget |

The direct script and `graph-rag-pressure` console command both delegate to the canonical
`scripts.pressure.cli` entrypoint; scenario, runner, metrics, thresholds, and reporting contracts
are owned by their matching `scripts.pressure` modules.

## Report Contract

JSON reports use this top-level shape:

```json
{
  "schema_version": 1,
  "scenario": {},
  "status": "pass",
  "metrics": {},
  "thresholds": {},
  "checks": []
}
```

`status` is derived from checks:

- `fail` if any check fails;
- `warn` if no checks fail and at least one check warns;
- `pass` when all checks pass.

CLI exit codes follow the same report classification:

- `0` for `pass` and `warn`, because both are completed observations;
- `1` for `fail`, after the full JSON or human-readable report is emitted.

This applies to `python scripts/pressure_api_service.py`, the
`graph-rag-pressure` console entry point, and both output formats.

## Metric Definitions

- `metrics.completed_requests`: requests admitted and completed by the serving service.
- `metrics.rejected_requests`: requests rejected by answer admission.
- `metrics.rejection_rate`: rejected requests divided by attempted requests.
- `metrics.p95_latency_ms`: p95 latency for completed requests only.
- `metrics.trace.dropped_events`: trace events dropped by async trace backpressure.
- `metrics.trace.failed_events`: trace sink write failures.
- `metrics.sse.executor.active` and `queued`: executor activity remaining when the run ends.
- `metrics.sse.executor.peak_active`: highest observed running SSE task count.
- `metrics.sse.executor.peak_outstanding`: highest observed running-plus-submitted count.
- `metrics.sse.executor.rejected`: submissions rejected immediately at the hard capacity.
- `metrics.model.p95_latency_ms`: synthetic model latency configured for the scenario.
- `metrics.model.estimated_cost_usd`: synthetic token cost for completed requests.
- `metrics.retrieval.degraded_rate`: deterministic degraded retrieval count divided by completed requests.
- `metrics.retrieval.degraded_source_counts`: degraded count by safe public source name.

## Threshold Interpretation

Use `api_concurrency_baseline` before and after changing admission, trace, or
answer workflow settings. Use `api_concurrency_saturation` when validating that
overload rejects quickly instead of creating unbounded latency.

Use `sse_runner_capacity` after changing stream execution or event buffering.
Its checks fail if worker or outstanding peaks exceed configuration, rejected
submissions do not match `RATE_LIMITED` events, any stream lacks `done`, or the
executor fails to return to zero activity.

Use `model_call_budget` to review model latency and cost policy changes without
provider calls. Use live observability for production provider SLOs.

Use `retrieval_degraded_budget` to verify degraded retrieval reporting and
classification. A warning means the signal is visible but above the healthy
baseline. A failure means the degraded rate or source concentration exceeds the
configured budget.
