# Concurrency And Backpressure Convergence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add configurable serving admission control and trace sink metrics so answer load is bounded without letting trace backpressure slow requests.

**Architecture:** Keep the change at the API and observability boundaries. Add a tiny admission controller inside the serving API service, surface a dedicated 429 error through FastAPI routes, and expand async trace sink stats without changing retrieval, generation, or build-job behavior.

**Tech Stack:** Python 3.11, FastAPI, unittest, pytest, threading, queue, existing GraphRAG config and tracing utilities.

---

## File Structure

- Modify: `rag_modules/configuration/models.py` - add API concurrency and stream queue settings.
- Modify: `rag_modules/configuration/section_loaders.py` - read new API env vars and clamp defaults.
- Modify: `rag_modules/interfaces/api/services/errors.py` - add `ApiBackpressureError`.
- Modify: `rag_modules/interfaces/api/services/__init__.py` - export the new API error.
- Modify: `rag_modules/interfaces/api/service.py` - keep compat exports aligned.
- Modify: `rag_modules/interfaces/api/services/serving.py` - add admission control, configurable stream queue/executor sizes, and SSE backpressure handling.
- Modify: `rag_modules/interfaces/api/routes.py` - register a 429 handler for admission failures.
- Modify: `rag_modules/interfaces/api/app.py` - wire the new handler into the serving app.
- Modify: `rag_modules/tracing_sinks.py` - add thread-safe sink metrics.
- Modify: `scripts/pressure_api_service.py` - accept admission controls and print rejection/trace metrics.
- Modify: `tests/test_configuration_section_loaders.py` - add failing config assertions first.
- Modify: `tests/test_api_app.py` - add failing admission/backpressure tests first.
- Modify: `tests/test_query_tracer.py` - add failing trace metrics tests first.
- Create: `tests/test_pressure_api_service.py` - add a focused pressure-script regression test.

### Task 1: API Configuration Surface

**Files:**
- Modify: `tests/test_configuration_section_loaders.py`
- Modify: `rag_modules/configuration/models.py`
- Modify: `rag_modules/configuration/section_loaders.py`

- [ ] **Step 1: Write the failing config test**

Add this test method to `ConfigurationSectionLoaderTests`:

```python
    def test_api_settings_include_concurrency_and_stream_limits(self) -> None:
        config = load_config(
            source=EnvConfigSource(
                environ={
                    "API_AUTH_ENABLED": "false",
                    "API_ACCESS_TOKEN": "test-access-token",
                    "API_MAX_REQUEST_BODY_BYTES": "32768",
                    "API_MAX_CONCURRENT_ANSWERS": "3",
                    "API_ANSWER_ACQUIRE_TIMEOUT_SECONDS": "0.5",
                    "API_STREAM_EXECUTOR_MAX_WORKERS": "8",
                    "API_STREAM_QUEUE_MAX_SIZE": "128",
                }
            )
        )

        self.assertFalse(config.api.auth_enabled)
        self.assertEqual(config.api.access_token, "test-access-token")
        self.assertEqual(config.api.max_request_body_bytes, 32768)
        self.assertEqual(config.api.max_concurrent_answers, 3)
        self.assertEqual(config.api.answer_acquire_timeout_seconds, 0.5)
        self.assertEqual(config.api.stream_executor_max_workers, 8)
        self.assertEqual(config.api.stream_queue_max_size, 128)
```

- [ ] **Step 2: Run the focused test to verify it fails**

Run:

```powershell
python -m pytest tests/test_configuration_section_loaders.py -q
```

Expected: FAIL because the new API fields do not exist yet.

- [ ] **Step 3: Implement the API settings and loader fields**

Add these fields to `ApiSettings`:

```python
    max_concurrent_answers: int = 0
    answer_acquire_timeout_seconds: float = 0.25
    stream_executor_max_workers: int = 4
    stream_queue_max_size: int = 64
```

Update `load_api_settings()` to read:

```python
        max_concurrent_answers=max(
            0,
            source.get_int(
                "API_MAX_CONCURRENT_ANSWERS",
                int(api_defaults.get("max_concurrent_answers", 0)),
            ),
        ),
        answer_acquire_timeout_seconds=max(
            0.0,
            source.get_float(
                "API_ANSWER_ACQUIRE_TIMEOUT_SECONDS",
                float(api_defaults.get("answer_acquire_timeout_seconds", 0.25)),
            ),
        ),
        stream_executor_max_workers=max(
            1,
            source.get_int(
                "API_STREAM_EXECUTOR_MAX_WORKERS",
                int(api_defaults.get("stream_executor_max_workers", 4)),
            ),
        ),
        stream_queue_max_size=max(
            1,
            source.get_int(
                "API_STREAM_QUEUE_MAX_SIZE",
                int(api_defaults.get("stream_queue_max_size", 64)),
            ),
        ),
```

- [ ] **Step 4: Run the focused test to verify it passes**

Run:

```powershell
python -m pytest tests/test_configuration_section_loaders.py -q
```

Expected: PASS.

### Task 2: Admission Control And 429/SSE Backpressure

**Files:**
- Modify: `tests/test_api_app.py`
- Modify: `rag_modules/interfaces/api/services/errors.py`
- Modify: `rag_modules/interfaces/api/services/__init__.py`
- Modify: `rag_modules/interfaces/api/service.py`
- Modify: `rag_modules/interfaces/api/services/serving.py`
- Modify: `rag_modules/interfaces/api/routes.py`
- Modify: `rag_modules/interfaces/api/app.py`

- [ ] **Step 1: Write the failing API tests**

Add these tests to `ApiAppTests`:

```python
    def test_serving_answers_are_rejected_when_admission_limit_is_full(self) -> None:
        system = _BlockingApiSystem()
        config = build_test_config(
            {
                "api": {
                    "access_token": _API_TOKEN,
                    "max_concurrent_answers": 1,
                    "answer_acquire_timeout_seconds": 0.01,
                }
            }
        )
        service = GraphRAGServingApiService(system=system, config=config)
        second_error: dict[str, object] = {}

        def run_first() -> None:
            service.answer_question(question="first tofu")

        def run_second() -> None:
            try:
                service.answer_question(question="second tofu")
            except Exception as exc:
                second_error["error"] = exc

        first_thread = threading.Thread(target=run_first)
        second_thread = threading.Thread(target=run_second)
        first_thread.start()
        self.assertTrue(system.answer_started.wait(timeout=1.0))
        second_thread.start()
        second_thread.join(timeout=1.0)
        system.release_answer.set()
        first_thread.join(timeout=1.0)

        self.assertEqual(second_error["error"].__class__.__name__, "ApiBackpressureError")
```

```python
    def test_serving_streams_emit_error_events_when_admission_is_full(self) -> None:
        system = _BlockingApiSystem()
        config = build_test_config(
            {
                "api": {
                    "access_token": _API_TOKEN,
                    "max_concurrent_answers": 1,
                    "answer_acquire_timeout_seconds": 0.01,
                    "stream_executor_max_workers": 2,
                    "stream_queue_max_size": 4,
                }
            }
        )
        service = GraphRAGServingApiService(system=system, config=config)

        first_thread = threading.Thread(target=lambda: service.answer_question(question="busy tofu"))
        first_thread.start()
        self.assertTrue(system.answer_started.wait(timeout=1.0))

        events = list(
            service.stream_answer_question_events(
                question="blocked tofu",
                explain_routing=True,
            )
        )

        system.release_answer.set()
        first_thread.join(timeout=1.0)

        self.assertEqual(events[0].event, AnswerStreamEventType.error)
        self.assertEqual(events[0].data.error_type, "api_backpressure")
        self.assertEqual(events[-1].event, AnswerStreamEventType.done)
```

- [ ] **Step 2: Run the focused API tests to verify they fail**

Run:

```powershell
python -m pytest tests/test_api_app.py -q
```

Expected: FAIL because `ApiBackpressureError` and the new admission logic do not exist yet.

- [ ] **Step 3: Implement the admission controller and route mapping**

Add `ApiBackpressureError` in `rag_modules/interfaces/api/services/errors.py` and export it from:

- `rag_modules/interfaces/api/services/__init__.py`
- `rag_modules/interfaces/api/service.py`

In `rag_modules/interfaces/api/services/serving.py`, add a tiny private controller:

```python
class _AnswerAdmissionController:
    def __init__(self, *, max_concurrent_answers: int, acquire_timeout_seconds: float) -> None:
        self.max_concurrent_answers = max(0, int(max_concurrent_answers or 0))
        self.acquire_timeout_seconds = max(0.0, float(acquire_timeout_seconds or 0.0))
        self._semaphore = (
            threading.BoundedSemaphore(self.max_concurrent_answers)
            if self.max_concurrent_answers > 0
            else None
        )

    @contextmanager
    def permit(self):
        if self._semaphore is None:
            yield
            return
        if not self._semaphore.acquire(timeout=self.acquire_timeout_seconds):
            raise ApiBackpressureError("Serving answer concurrency limit exceeded.")
        try:
            yield
        finally:
            self._semaphore.release()
```

Use it in both `answer_question()` and `stream_answer_question_events()`.

Add a `register_api_backpressure_handler(app)` helper in `rag_modules/interfaces/api/routes.py`:

```python
def register_api_backpressure_handler(app: FastAPI) -> None:
    @app.exception_handler(ApiBackpressureError)
    async def handle_api_backpressure(_: Request, exc: ApiBackpressureError):
        return build_json_response(
            status_code=429,
            content={
                "ok": False,
                "message": str(exc),
                "error_type": "api_backpressure",
            },
        )
```

Call it from `create_serving_api_app()` in `rag_modules/interfaces/api/app.py`.

- [ ] **Step 4: Run the focused API tests to verify they pass**

Run:

```powershell
python -m pytest tests/test_api_app.py -q
```

Expected: PASS.

### Task 3: Trace Sink Metrics

**Files:**
- Modify: `tests/test_query_tracer.py`
- Modify: `rag_modules/tracing_sinks.py`

- [ ] **Step 1: Write the failing trace metrics test**

Add this test method to `QueryTracerTests`:

```python
    def test_async_sink_exposes_write_and_drop_metrics(self) -> None:
        delegate = _BlockingSink()
        sink = AsyncQueryTraceSink(delegate, max_queue_size=1)

        sink.write(QueryTraceEvent(query_id="a", timestamp=1, query="first"))
        self.assertTrue(delegate.started.wait(timeout=0.5))
        sink.write(QueryTraceEvent(query_id="b", timestamp=2, query="second"))
        sink.write(QueryTraceEvent(query_id="c", timestamp=3, query="third"))

        delegate.release.set()
        sink.close()

        stats = sink.stats()
        self.assertEqual(stats["max_queue_size"], 1)
        self.assertEqual(stats["closed"], True)
        self.assertGreaterEqual(stats["written_events"], 1)
        self.assertGreaterEqual(stats["dropped_events"], 1)
        self.assertEqual(stats["failed_events"], 0)
```

- [ ] **Step 2: Run the focused trace test to verify it fails**

Run:

```powershell
python -m pytest tests/test_query_tracer.py -q
```

Expected: FAIL because the sink does not expose the new metrics yet.

- [ ] **Step 3: Implement thread-safe sink counters**

In `rag_modules/tracing_sinks.py`, add counters and a lock to `AsyncQueryTraceSink`:

```python
        self._stats_lock = threading.Lock()
        self._written_events = 0
        self._failed_events = 0
```

Increment them in the worker and write path:

```python
        with self._stats_lock:
            self._dropped_events += 1
```

```python
                with self._stats_lock:
                    self._written_events += 1
```

```python
                with self._stats_lock:
                    self._failed_events += 1
```

Return them from `stats()` together with `queued_events`, `closed`, and `max_queue_size`.

Also align `NullQueryTraceSink` and `JsonlQueryTraceSink` stats so they return the same key set.

- [ ] **Step 4: Run the focused trace test to verify it passes**

Run:

```powershell
python -m pytest tests/test_query_tracer.py -q
```

Expected: PASS.

### Task 4: Pressure Script Coverage

**Files:**
- Create: `tests/test_pressure_api_service.py`
- Modify: `scripts/pressure_api_service.py`

- [ ] **Step 1: Write the failing pressure-script test**

Create a focused regression test:

```python
from __future__ import annotations

import unittest

from scripts.pressure_api_service import run_pressure_test


class PressureApiServiceTests(unittest.TestCase):
    def test_pressure_run_reports_admission_rejections(self) -> None:
        result = run_pressure_test(
            requests=12,
            workers=4,
            answer_delay_ms=50.0,
            trace_delay_ms=10.0,
            trace_queue_size=1,
            max_concurrent_answers=1,
            answer_acquire_timeout_seconds=0.01,
        )

        payload = result.to_dict()
        self.assertEqual(payload["requests"], 12)
        self.assertGreater(payload["rejected_requests"], 0)
        self.assertIn("trace_stats", payload)
        self.assertIn("dropped_events", payload["trace_stats"])
        self.assertIn("written_events", payload["trace_stats"])
        self.assertIn("failed_events", payload["trace_stats"])
        self.assertIn("closed", payload["trace_stats"])
```

- [ ] **Step 2: Run the focused pressure test to verify it fails**

Run:

```powershell
python -m pytest tests/test_pressure_api_service.py -q
```

Expected: FAIL because the script does not accept admission parameters or return rejection counts yet.

- [ ] **Step 3: Implement admission options and richer pressure metrics**

Update `run_pressure_test()` and `PressureResult` in `scripts/pressure_api_service.py`:

```python
def run_pressure_test(
    *,
    requests: int,
    workers: int,
    answer_delay_ms: float,
    trace_delay_ms: float,
    trace_queue_size: int,
    max_concurrent_answers: int,
    answer_acquire_timeout_seconds: float,
) -> PressureResult:
```

Count successful and rejected requests separately:

```python
    completed_requests = 0
    rejected_requests = 0
```

Catch `ApiBackpressureError` inside `worker_loop()` and increment `rejected_requests`.

Add CLI flags:

```python
    parser.add_argument("--max-concurrent-answers", type=int, default=0)
    parser.add_argument("--answer-acquire-timeout-seconds", type=float, default=0.25)
```

Print the new counters and trace metrics in the summary.

- [ ] **Step 4: Run the focused pressure test to verify it passes**

Run:

```powershell
python -m pytest tests/test_pressure_api_service.py -q
```

Expected: PASS.

### Task 5: Final Verification

**Files:**
- All touched files from Tasks 1-4

- [ ] **Step 1: Run the focused regression set**

Run:

```powershell
python -m pytest tests/test_configuration_section_loaders.py tests/test_api_app.py tests/test_query_tracer.py tests/test_pressure_api_service.py -q
```

Expected: PASS.

- [ ] **Step 2: Run the pressure script once**

Run:

```powershell
python scripts/pressure_api_service.py --json --requests 12 --workers 4 --answer-delay-ms 50 --trace-delay-ms 10 --trace-queue-size 1 --max-concurrent-answers 1 --answer-acquire-timeout-seconds 0.01
```

Expected: JSON output with nonzero `rejected_requests` and trace stats that include `queued_events`, `dropped_events`, `written_events`, `failed_events`, `closed`, and `max_queue_size`.

- [ ] **Step 3: Stage only the touched files**

Run:

```powershell
git -c safe.directory=E:/ai-project/all-in-rag add `
  docs/superpowers/plans/2026-06-16-concurrency-backpressure-convergence.md `
  rag_modules/configuration/models.py `
  rag_modules/configuration/section_loaders.py `
  rag_modules/interfaces/api/services/errors.py `
  rag_modules/interfaces/api/services/__init__.py `
  rag_modules/interfaces/api/service.py `
  rag_modules/interfaces/api/services/serving.py `
  rag_modules/interfaces/api/routes.py `
  rag_modules/interfaces/api/app.py `
  rag_modules/tracing_sinks.py `
  scripts/pressure_api_service.py `
  tests/test_configuration_section_loaders.py `
  tests/test_api_app.py `
  tests/test_query_tracer.py `
  tests/test_pressure_api_service.py
```

Expected: only the feature files are staged; do not commit.
