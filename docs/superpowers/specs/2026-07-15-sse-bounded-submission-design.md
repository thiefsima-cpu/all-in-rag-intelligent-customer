# SSE Bounded Submission Refactor Design

## Goal

Make SSE background execution structurally bounded so overload cannot accumulate an
unbounded number of pending `ThreadPoolExecutor` work items. Saturated streams must be
rejected immediately with the existing `RATE_LIMITED` SSE contract, and executor capacity
must be visible in production metrics and deterministic pressure tests.

## Scope

This refactor covers the serving SSE session, its background executor boundary, API stream
capacity configuration, Prometheus instrumentation, and the local SSE pressure scenario.

It does not change retrieval, routing, generation, the SSE event schema, non-streaming HTTP
error contracts, or the shared answer admission policy. It also does not replace unrelated
thread pools elsewhere in the repository.

## Root Cause

Each `_SseStreamSession` owns a bounded event queue, but `events()` submits `_run()` directly
to a standard `ThreadPoolExecutor`. Python's standard executor accepts an unbounded number of
pending work items. The shared answer admission permit is acquired later inside the worker, so
it limits answer execution without limiting already-submitted SSE tasks. Under sustained
concurrency, pending sessions, futures, request controls, and captured request data can grow
with request volume.

The existing pressure scenario observes SSE terminal and rate-limit events but does not
observe executor queue depth or prove a submission-capacity invariant.

## Design Decision

Introduce a dedicated bounded stream executor that wraps `ThreadPoolExecutor` and is the only
submission path used by SSE sessions. A non-blocking `BoundedSemaphore` reserves one slot before
every submission. The configured slot count is explicit:

```text
submission_capacity = stream_executor_max_outstanding
```

The semaphore bounds all outstanding tasks, including both tasks currently running in worker
threads and tasks submitted but not yet started. The underlying standard executor queue remains
an implementation detail and cannot grow beyond this admission boundary. The configuration names
the invariant directly instead of implying that the wrapper can observe or replace the standard
executor's private queue.

The shared answer admission controller remains separate. It continues to bound combined JSON
and SSE answer execution after a stream task begins. Executor capacity and answer capacity model
different resources and must not consume each other's permits.

### Rejected Alternatives

Moving the existing answer permit acquisition before `submit()` was rejected because it would
make queued SSE tasks consume business-execution capacity and could starve non-streaming answer
requests.

Replacing or mutating `ThreadPoolExecutor`'s private work queue was rejected because it relies on
CPython implementation details and complicates shutdown behavior.

Building a custom worker pool was rejected because the standard executor already provides
well-tested future, cancellation, exception, and shutdown semantics. A strict public submission
boundary solves the memory-growth problem without recreating those semantics.

## Component Boundaries

### Bounded Stream Executor

Create `rag_modules/interfaces/api/services/serving_stream_executor.py`.

It owns:

- the private `ThreadPoolExecutor`;
- the `BoundedSemaphore` covering running plus queued submissions;
- non-blocking submission and immediate saturation rejection;
- per-submission state transitions for queued, active, cancelled, and completed work;
- shutdown and cancellation accounting;
- a thread-safe executor-capacity snapshot.

It exposes a focused API equivalent to:

```python
class BoundedStreamExecutor:
    def submit(self, fn: Callable[[], None]) -> Future[None]: ...
    def snapshot(self) -> StreamExecutorSnapshot: ...
    def shutdown(self) -> None: ...
```

`submit()` raises `ApiBackpressureError` immediately when no submission slot is available. It
raises `RuntimeError` after shutdown so the existing system-not-ready terminal behavior remains
available for lifecycle races.

Every accepted submission owns exactly one slot. The slot is released exactly once when the
task completes or when a queued future is cancelled before it starts. Failed executor submission
rolls back the queued state and releases the reserved slot.

### SSE Session And Runner

`serving_streams.py` keeps responsibility for session state, event buffering, result conversion,
request cancellation, and SSE terminal ordering.

The runner owns one `BoundedStreamExecutor`; sessions no longer resolve or access a raw
`ThreadPoolExecutor`. On `ApiBackpressureError`, a session emits:

1. `error` with `ErrorCode.RATE_LIMITED` and the request ID;
2. `done`;
3. no background future and no answer invocation.

The existing answer admission permit stays around `answer_question_response(...)` inside the
background task.

### Serving Service

`GraphRAGServingApiService` constructs the bounded executor through `ServingSseRunner`, passes
the explicit worker and total-outstanding capacities, and provides the runtime telemetry observer.
Shutdown continues to close the stream runner before closing the application system.

## Configuration Cutover

Two different queues receive distinct, unambiguous names:

- `api.stream_executor_max_workers`, default `4`, minimum `1`;
- `api.stream_executor_max_outstanding`, default `8`, minimum equal to
  `stream_executor_max_workers`;
- `api.stream_event_queue_max_size`, default `64`, minimum `1`.

Environment variables become:

- `API_STREAM_EXECUTOR_MAX_WORKERS`;
- `API_STREAM_EXECUTOR_MAX_OUTSTANDING`;
- `API_STREAM_EVENT_QUEUE_MAX_SIZE`.

Remove `api.stream_queue_max_size` and `API_STREAM_QUEUE_MAX_SIZE`. Do not add aliases,
deprecation shims, dual reads, or fallback compatibility logic. Update repository profiles,
examples, tests, and documentation to the new names in the same change.

## Capacity Invariants

At every externally observable point:

```text
0 <= active <= stream_executor_max_workers
0 <= queued <= stream_executor_max_outstanding
active + queued <= submission_capacity
```

Worker startup may race with the submitting thread, so state changes must be serialized by one
metrics/state lock. A submission is recorded as queued before it is handed to the standard
executor. Worker start atomically moves it from queued to active. Completion atomically removes
it from active and releases its slot. Cancellation before worker start atomically removes it from
queued and releases its slot.

No counter or gauge may become negative. A future callback and worker `finally` block must not
both release the same submission.

## Metrics And Observability

Extend `RuntimeTelemetry` with these Prometheus instruments:

- `graphrag_sse_executor_active`: gauge of currently running SSE executor tasks;
- `graphrag_sse_executor_queued`: gauge of accepted tasks not yet started;
- `graphrag_sse_executor_rejected_total`: counter of immediate capacity rejections.

Metric updates originate from the bounded executor state transitions, which are the single
source of truth. Metrics remain registered when Prometheus is enabled through the existing
runtime telemetry registry and appear on the existing `/metrics` endpoint.

The executor snapshot contains:

- worker count;
- pending queue limit;
- total submission capacity;
- current active and queued counts;
- peak active, queued, and total outstanding counts;
- cumulative rejected submissions.

Current gauges support live operations. Peak and cumulative values support deterministic tests
and post-run pressure reporting.

## Pressure Scenario

Extend the `sse_runner_capacity` scenario so it can configure executor workers and maximum
outstanding submissions independently from pressure-client worker count. The scenario must create
more simultaneous stream attempts than `max_outstanding` while answer work is blocked long enough
to hold the executor at capacity.

Add an `executor` object under `metrics.sse` containing the snapshot fields. The pressure checks
must prove:

- at least one submission was immediately rejected in the saturation fixture;
- `peak_active` did not exceed configured executor workers;
- `peak_outstanding` did not exceed configured maximum outstanding submissions;
- rejected submissions equal `RATE_LIMITED` SSE error events;
- every attempted stream still emitted one terminal `done` event;
- current active and queued counts return to zero after shutdown.

The test remains local and deterministic and must not require HTTP, model providers, Neo4j, or
Milvus.

## Error And Lifecycle Handling

- Saturation is a normal overload outcome and emits `RATE_LIMITED` plus `done` without logging an
  application failure.
- Executor shutdown races continue to emit `SYSTEM_NOT_READY` plus `done`.
- Exceptions raised by accepted background tasks keep the existing answer-failure mapping.
- Closing a stream consumer still cancels its request control and attempts to cancel its future.
- Cancelling queued futures during shutdown releases their submission slots and decrements queued
  metrics.
- Running futures release active capacity in their `finally` path even when the stream consumer
  disconnects or answer generation fails.

## Testing Strategy

Follow test-driven development with focused red-green cycles:

1. Configuration tests prove the new names and deliberate removal of the old field and env key.
2. Executor unit tests use blocking callables to prove one active plus one queued task causes the
   next submission to fail immediately when `max_outstanding=2`, without relying on private
   executor state.
3. Executor lifecycle tests prove submit failure rollback, queued cancellation, task exception,
   and shutdown leave current metrics and semaphore slots balanced.
4. SSE service tests prove rejected streams emit exactly `RATE_LIMITED`, then `done`, and never
   invoke the application answer workflow.
5. Prometheus tests prove active, queued, and rejected series are exported with correct values.
6. Pressure tests prove bounded peaks, balanced rejection accounting, terminal events, and zero
   residual activity.
7. Run the API SSE slice, pressure suite, configuration tests, Ruff, and the release gate before
   completion because this changes public configuration and serving capacity behavior.

Tests should synchronize with events and barriers rather than arbitrary sleeps wherever possible.

## Documentation

Update `.env.example`, the API capacity guide, observability documentation, and any configuration
reference that names the old event queue setting. Document both formulas:

```text
max_outstanding_sse_tasks = stream_executor_max_outstanding
max_stream_event_buffer = outstanding_streams * stream_event_queue_max_size
```

Clarify that the first formula bounds retained request/session objects, while the second bounds
events retained by accepted streams.

## Acceptance Criteria

- No SSE code path submits directly to a raw `ThreadPoolExecutor`.
- Outstanding SSE background tasks remain within the configured hard capacity under overload.
- Saturation returns `RATE_LIMITED` plus `done` immediately without invoking answer generation.
- Slots and current metrics are balanced across success, failure, cancellation, submit rollback,
  and shutdown.
- Prometheus exposes current active, queued, and cumulative rejected executor metrics.
- The local pressure scenario proves configured active and queued bounds and balanced rejection
  accounting.
- Old ambiguous queue configuration names are absent from production code, tests, profiles,
  examples, and current documentation.
- Relevant focused tests, Ruff, and the release gate pass.
