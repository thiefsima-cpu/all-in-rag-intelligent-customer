# Concurrency And Backpressure Convergence Design

## Goal

Converge serving concurrency and trace backpressure into explicit, observable
runtime controls. The serving API should admit a bounded number of answer
workloads when configured, reject excess load predictably, and keep trace
persistence from slowing user-facing requests.

## Scope

This design covers two layers:

- API admission control for `/answers` and `/answers/stream`.
- Async query trace sink metrics and pressure-test visibility.

It does not change retrieval, routing, generation model behavior, build job
execution, or lifecycle locking semantics.

## Architecture

The API layer owns admission control because it is the first shared boundary
for online answer work. `GraphRAGServingApiService` will hold a small admission
controller that guards only answer execution:

- Non-streaming `/answers` acquires a permit before calling
  `system.answer_question_response(...)`.
- Streaming `/answers/stream` acquires a permit in the background runner before
  calling `system.answer_question_response(..., stream=True, ...)`.
- `/health`, `/stats`, and `/diagnostics` do not consume answer permits.
- Build, refresh, and shutdown continue to use the existing
  `_GraphRAGApiServiceLocks.lifecycle_operation()` coordination.

Trace persistence remains behind `AsyncQueryTraceSink`. The sink keeps the
existing non-blocking policy: caller threads enqueue with `put_nowait`, and
events are dropped when the queue is full.

## Configuration

Add API settings with compatibility-preserving defaults:

- `API_MAX_CONCURRENT_ANSWERS=0`
  - `0` disables admission limiting and preserves existing behavior.
  - Positive values bound concurrent non-streaming and streaming answer work
    together.
- `API_ANSWER_ACQUIRE_TIMEOUT_SECONDS=0.25`
  - Maximum time a request waits for an answer permit before rejection.
- `API_STREAM_EXECUTOR_MAX_WORKERS=4`
  - Replaces the current hard-coded stream executor worker count.
- `API_STREAM_QUEUE_MAX_SIZE=64`
  - Replaces the current hard-coded per-stream SSE queue size.

Existing trace settings remain active:

- `QUERY_TRACE_ASYNC_ENABLED`
- `QUERY_TRACE_MAX_QUEUE_SIZE`

## Components

### API Admission Controller

Add a focused helper owned by the serving service. It can be private to
`rag_modules.interfaces.api.services.serving` unless reuse appears later.

Responsibilities:

- Track configured max concurrent answer operations.
- Return a context manager that acquires and releases one permit.
- Treat `max_concurrent_answers <= 0` as unlimited.
- Wait up to `answer_acquire_timeout_seconds` for a permit.
- Raise `ApiBackpressureError` when no permit is available in time.

The controller should not know about FastAPI, response models, generation, or
trace sinks.

### Serving API Service

`GraphRAGServingApiService` will:

- Resolve the four new API settings from `config.api`.
- Use configured stream executor workers and stream queue size.
- Wrap non-streaming answer work in the admission controller.
- Wrap streaming background runner answer work in the same controller.
- Preserve current stats/diagnostics behavior during lifecycle operations.

### API Error Surface

Add `ApiBackpressureError` in `rag_modules.interfaces.api.services.errors`.

Route handlers register an exception handler mapping the error to HTTP 429:

```json
{
  "ok": false,
  "message": "Serving answer concurrency limit exceeded.",
  "error_type": "api_backpressure"
}
```

For SSE streams where HTTP headers may already be committed, the stream emits
an `error` event with `error_type="api_backpressure"` and then emits `done`.

### Async Trace Sink Metrics

`AsyncQueryTraceSink` will keep non-blocking writes and add thread-safe metrics:

- `queued_events`
- `dropped_events`
- `written_events`
- `failed_events`
- `closed`
- `max_queue_size`

Delegate write failures stay isolated to the sink worker. They increment
`failed_events` and log a warning, but do not affect answer request execution.

## Data Flow

Non-streaming answer flow:

1. FastAPI route validates the request.
2. Route delegates to `GraphRAGServingApiService.answer_question`.
3. Serving service ensures runtime initialization and refresh checks.
4. Admission controller acquires an answer permit.
5. Service enters the existing answer operation lock.
6. Service calls `system.answer_question_response(...)`.
7. Permit is released in a `finally` path.
8. Route returns the existing answer response shape.

Streaming answer flow:

1. FastAPI route creates an SSE response.
2. Serving service creates a bounded per-stream event queue.
3. Background runner starts from the configured stream executor.
4. Runner acquires an answer permit.
5. Runner calls `system.answer_question_response(..., stream=True, ...)`.
6. Message, chunk, result, error, and done events flow through the bounded queue.
7. Consumer disconnect sets `stream_closed`, and the runner exits through the
   existing cancellation path.

Trace flow:

1. `QueryTracer.record(...)` creates a sanitized trace event.
2. `AsyncQueryTraceSink.write(...)` clones and attempts non-blocking enqueue.
3. If the queue is full, the sink increments `dropped_events` and returns.
4. The worker drains queued events to the delegate.
5. Delegate failures increment `failed_events` and are logged.

## Error Handling

- `ApiBackpressureError` maps to HTTP 429 for normal JSON request handling.
- SSE backpressure maps to a stream `error` event plus `done`.
- `SystemNotReadyError` remains HTTP 409.
- Trace enqueue overflow drops trace events without blocking request threads.
- Trace delegate failures never propagate to request execution.
- `shutdown()` continues to shut down the stream executor and close the system.

## Testing

Add focused tests:

- Configuration loading covers all new API env and override fields.
- Default `API_MAX_CONCURRENT_ANSWERS=0` still allows concurrent answers.
- With `API_MAX_CONCURRENT_ANSWERS=1` and a short acquire timeout, a second
  concurrent non-streaming answer is rejected with `ApiBackpressureError` at
  service level and HTTP 429 at route level.
- A stream request rejected after SSE setup emits `error` and `done`.
- Serving service uses configured stream executor worker count and stream queue
  size.
- `AsyncQueryTraceSink` exposes `written_events`, `failed_events`, `closed`,
  and `max_queue_size`.
- Concurrent trace writes keep `dropped_events` accounting thread-safe.
- Pressure script output includes admitted/rejected counts and trace
  queued/dropped/written/failed metrics.

## Pressure Script

Extend `scripts/pressure_api_service.py` with API admission options:

- `--max-concurrent-answers`
- `--answer-acquire-timeout-seconds`

The summary should report:

- requests attempted
- requests completed
- requests rejected by admission control
- throughput and latency for completed requests
- trace queued, dropped, written, failed, and closed metrics

This script remains local and deterministic; it does not require external
Neo4j, Milvus, or model provider access.

## Acceptance Criteria

- Default configuration preserves current serving concurrency behavior.
- Positive `API_MAX_CONCURRENT_ANSWERS` bounds combined streaming and
  non-streaming answer work.
- Excess answer load produces predictable 429 or SSE error events.
- Trace backpressure is visible through stats without adding request latency.
- Existing API, generation, query tracer, and pressure tests remain fast and
  deterministic.
