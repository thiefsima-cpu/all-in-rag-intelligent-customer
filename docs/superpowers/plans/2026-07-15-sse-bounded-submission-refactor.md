# SSE Bounded Submission Refactor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace unbounded SSE task submission with an explicitly bounded executor boundary that rejects overload immediately and exposes active, queued, and rejected capacity metrics.

**Architecture:** Add a focused `BoundedStreamExecutor` around the standard executor. It reserves one non-blocking slot per outstanding task, owns queued/active/cancelled transitions, and supplies one thread-safe snapshot; the SSE runner consumes this abstraction while answer admission remains a separate execution concern. Rename the per-stream event queue setting, add an explicit maximum-outstanding setting, wire Prometheus deltas from the same state transitions, and make the local pressure scenario prove the invariant.

**Tech Stack:** Python 3.11, `concurrent.futures`, `threading`, FastAPI, Pydantic v2, Prometheus client, pytest/unittest, Ruff.

## Global Constraints

- Use Python `>=3.11,<3.12`; add no production dependency.
- Preserve the existing SSE event schema and `RATE_LIMITED` then `done` terminal contract.
- Keep shared answer admission separate from executor submission capacity.
- Enforce `active + queued <= stream_executor_max_outstanding` for every accepted task lifecycle.
- Remove `api.stream_queue_max_size` and `API_STREAM_QUEUE_MAX_SIZE`; add no compatibility alias, dual read, or deprecation shim.
- Keep unrelated thread pools, retrieval, routing, generation, and build-job behavior out of scope.
- Add or update tests before each production behavior change and observe each focused test fail for the expected reason.
- Keep Ruff's Python 3.11, 100-character, import-order, and double-quote conventions.

---

## File Structure

- Modify `rag_modules/configuration/model_sections/api.py`: define unambiguous executor and event-queue settings plus their cross-field invariant.
- Modify `rag_modules/configuration/env_specs/api.py`: hard-cut environment names to the new settings.
- Create `rag_modules/interfaces/api/services/serving_stream_executor.py`: own bounded submission, lifecycle accounting, snapshot, and observer contract.
- Modify `rag_modules/interfaces/api/services/serving_streams.py`: keep SSE session behavior while delegating all task submission to the bounded executor.
- Modify `rag_modules/interfaces/api/services/serving.py`: compose the runner with the new settings and runtime telemetry.
- Modify `rag_modules/telemetry.py`: register and update SSE active, queued, and rejected Prometheus instruments.
- Modify `scripts/pressure/scenario.py`: model executor workers, maximum outstanding tasks, and per-stream event capacity.
- Modify `scripts/pressure/cli.py`: expose the new pressure scenario inputs.
- Modify `scripts/pressure/metrics.py`: serialize executor capacity metrics under `metrics.sse.executor`.
- Modify `scripts/pressure/runner.py`: configure the real bounded executor and collect its final snapshot.
- Modify `scripts/pressure/thresholds.py`: prove rejection accounting, capacity bounds, and idle final state.
- Create `tests/test_serving_stream_executor.py`: directly verify bounded concurrency and lifecycle races without private queue inspection.
- Modify `tests/test_configuration_section_loaders.py`: verify new configuration and removal of the old names.
- Modify `tests/test_api_sse.py`: verify service wiring, immediate SSE rejection, and Prometheus values.
- Modify `tests/test_serving_api_collaborators.py`: verify collaborator composition uses the new capacities.
- Modify `tests/test_api_security.py`: verify all new metric families are registered on `/metrics`.
- Modify `tests/test_pressure_runner.py`, `tests/test_pressure_thresholds.py`, and `tests/test_pressure_cli.py`: verify saturation evidence and CLI propagation.
- Modify `.env.example`, `docs/api_capacity_and_pressure_thresholds.md`, and `docs/observability.md`: document the hard cutover, formulas, and metrics.

### Task 1: Explicit Stream Capacity Configuration

**Files:**
- Modify: `tests/test_configuration_section_loaders.py`
- Modify: `rag_modules/configuration/model_sections/api.py`
- Modify: `rag_modules/configuration/env_specs/api.py`
- Modify: `.env.example`

**Interfaces:**
- Consumes: existing `ApiSettings` Pydantic validation and `API_ENV_FIELD_SPECS` loading.
- Produces: `ApiSettings.stream_executor_max_workers: int`, `stream_executor_max_outstanding: int`, and `stream_event_queue_max_size: int` for Tasks 3 and 4.

- [ ] **Step 1: Write failing configuration tests**

Update `test_api_settings_respect_environment_overrides` to use and assert the new fields:

```python
"API_STREAM_EXECUTOR_MAX_WORKERS": "8",
"API_STREAM_EXECUTOR_MAX_OUTSTANDING": "12",
"API_STREAM_EVENT_QUEUE_MAX_SIZE": "128",
```

```python
self.assertEqual(config.api.stream_executor_max_workers, 8)
self.assertEqual(config.api.stream_executor_max_outstanding, 12)
self.assertEqual(config.api.stream_event_queue_max_size, 128)
self.assertFalse(hasattr(config.api, "stream_queue_max_size"))
```

Add this cross-field test:

```python
def test_api_settings_reject_stream_outstanding_below_worker_count(self) -> None:
    with self.assertRaises(ConfigurationError) as context:
        load_config(
            source=EnvConfigSource(
                environ={
                    "API_STREAM_EXECUTOR_MAX_WORKERS": "4",
                    "API_STREAM_EXECUTOR_MAX_OUTSTANDING": "3",
                }
            )
        )

    self.assertIn(
        "api.stream_executor_max_outstanding must be greater than or equal to "
        "api.stream_executor_max_workers",
        str(context.exception),
    )
```

- [ ] **Step 2: Run the configuration tests and verify RED**

Run:

```powershell
python -m pytest tests/test_configuration_section_loaders.py -q
```

Expected: FAIL because the new environment fields and model attributes do not exist and the old attribute still exists.

- [ ] **Step 3: Implement the hard-cut configuration model**

Replace the old stream fields in `ApiSettings` with:

```python
stream_executor_max_workers: int = Field(default=4, ge=1)
stream_executor_max_outstanding: int = Field(default=8, ge=1)
stream_event_queue_max_size: int = Field(default=64, ge=1)
```

Extend the existing model validator before `return self`:

```python
if self.stream_executor_max_outstanding < self.stream_executor_max_workers:
    raise ValueError(
        "api.stream_executor_max_outstanding must be greater than or equal to "
        "api.stream_executor_max_workers."
    )
```

Replace the old environment spec with:

```python
_spec("API_STREAM_EXECUTOR_MAX_WORKERS", ("api", "stream_executor_max_workers"), "int"),
_spec(
    "API_STREAM_EXECUTOR_MAX_OUTSTANDING",
    ("api", "stream_executor_max_outstanding"),
    "int",
),
_spec("API_STREAM_EVENT_QUEUE_MAX_SIZE", ("api", "stream_event_queue_max_size"), "int"),
```

Replace the corresponding `.env.example` block with:

```dotenv
API_STREAM_EXECUTOR_MAX_WORKERS=4
API_STREAM_EXECUTOR_MAX_OUTSTANDING=8
API_STREAM_EVENT_QUEUE_MAX_SIZE=64
```

- [ ] **Step 4: Run the configuration tests and verify GREEN**

Run:

```powershell
python -m pytest tests/test_configuration_section_loaders.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit the configuration cutover**

```powershell
git add -- .env.example rag_modules/configuration/model_sections/api.py rag_modules/configuration/env_specs/api.py tests/test_configuration_section_loaders.py
git commit -m "refactor: define explicit SSE submission capacity"
```

### Task 2: Bounded Stream Executor And Lifecycle Accounting

**Files:**
- Create: `rag_modules/interfaces/api/services/serving_stream_executor.py`
- Create: `tests/test_serving_stream_executor.py`

**Interfaces:**
- Consumes: `ApiBackpressureError` from `rag_modules.interfaces.api.services.errors`.
- Produces: `BoundedStreamExecutor.submit`, `shutdown`, `snapshot`; `StreamExecutorSnapshot`; and `StreamExecutorObserver.record_sse_executor_state` for Task 3.

- [ ] **Step 1: Write failing executor behavior tests**

Create `tests/test_serving_stream_executor.py` with synchronization-based tests equivalent to:

```python
from __future__ import annotations

import threading
import unittest

from rag_modules.interfaces.api.services.errors import ApiBackpressureError
from rag_modules.interfaces.api.services.serving_stream_executor import BoundedStreamExecutor


class BoundedStreamExecutorTests(unittest.TestCase):
    def test_running_plus_queued_are_bounded_and_saturation_rejects_immediately(self) -> None:
        started = threading.Event()
        release = threading.Event()
        executor = BoundedStreamExecutor(max_workers=1, max_outstanding=2)

        def block() -> None:
            started.set()
            release.wait(timeout=2.0)

        first = executor.submit(block)
        self.assertTrue(started.wait(timeout=1.0))
        second = executor.submit(lambda: None)

        with self.assertRaises(ApiBackpressureError):
            executor.submit(lambda: None)

        saturated = executor.snapshot()
        self.assertEqual((saturated.active, saturated.queued), (1, 1))
        self.assertEqual(saturated.peak_outstanding, 2)
        self.assertEqual(saturated.rejected, 1)

        release.set()
        first.result(timeout=1.0)
        second.result(timeout=1.0)
        self.assertEqual((executor.snapshot().active, executor.snapshot().queued), (0, 0))
        executor.shutdown()

    def test_cancelling_queued_future_releases_exactly_one_slot(self) -> None:
        started = threading.Event()
        release = threading.Event()
        executor = BoundedStreamExecutor(max_workers=1, max_outstanding=2)
        first = executor.submit(lambda: (started.set(), release.wait(timeout=2.0)))
        self.assertTrue(started.wait(timeout=1.0))
        queued = executor.submit(lambda: None)

        self.assertTrue(queued.cancel())
        replacement = executor.submit(lambda: None)
        self.assertEqual(executor.snapshot().queued, 1)

        release.set()
        first.result(timeout=1.0)
        replacement.result(timeout=1.0)
        self.assertEqual((executor.snapshot().active, executor.snapshot().queued), (0, 0))
        executor.shutdown()

    def test_task_failure_and_shutdown_leave_capacity_balanced(self) -> None:
        executor = BoundedStreamExecutor(max_workers=1, max_outstanding=1)

        def fail() -> None:
            raise ValueError("expected failure")

        with self.assertRaisesRegex(ValueError, "expected failure"):
            executor.submit(fail).result(timeout=1.0)
        executor.submit(lambda: None).result(timeout=1.0)
        executor.shutdown()

        self.assertEqual((executor.snapshot().active, executor.snapshot().queued), (0, 0))
        with self.assertRaises(RuntimeError):
            executor.submit(lambda: None)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the executor tests and verify RED**

Run:

```powershell
python -m pytest tests/test_serving_stream_executor.py -q
```

Expected: collection ERROR because `serving_stream_executor` does not exist.

- [ ] **Step 3: Implement the bounded executor**

Create `serving_stream_executor.py` with these exact public contracts and state transitions:

```python
from __future__ import annotations

import threading
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from typing import Protocol, TypeVar

from .errors import ApiBackpressureError

_T = TypeVar("_T")


class StreamExecutorObserver(Protocol):
    def record_sse_executor_state(
        self,
        *,
        active_delta: int = 0,
        queued_delta: int = 0,
        rejected_delta: int = 0,
    ) -> None: ...


@dataclass(frozen=True, slots=True)
class StreamExecutorSnapshot:
    max_workers: int
    max_outstanding: int
    active: int
    queued: int
    peak_active: int
    peak_queued: int
    peak_outstanding: int
    rejected: int

    def to_dict(self) -> dict[str, int]:
        return {
            "max_workers": self.max_workers,
            "max_outstanding": self.max_outstanding,
            "active": self.active,
            "queued": self.queued,
            "peak_active": self.peak_active,
            "peak_queued": self.peak_queued,
            "peak_outstanding": self.peak_outstanding,
            "rejected": self.rejected,
        }


class _Submission:
    def __init__(self) -> None:
        self.state = "queued"


class BoundedStreamExecutor:
    def __init__(
        self,
        *,
        max_workers: int,
        max_outstanding: int,
        observer: StreamExecutorObserver | None = None,
    ) -> None:
        if max_workers < 1:
            raise ValueError("max_workers must be at least 1")
        if max_outstanding < max_workers:
            raise ValueError("max_outstanding must be at least max_workers")
        self.max_workers = int(max_workers)
        self.max_outstanding = int(max_outstanding)
        self._observer = observer
        self._slots = threading.BoundedSemaphore(self.max_outstanding)
        self._state_lock = threading.Lock()
        self._lifecycle_lock = threading.Lock()
        self._closed = False
        self._active = 0
        self._queued = 0
        self._peak_active = 0
        self._peak_queued = 0
        self._peak_outstanding = 0
        self._rejected = 0
        self._executor = ThreadPoolExecutor(
            max_workers=self.max_workers,
            thread_name_prefix="graph-rag-answer",
        )

    def submit(self, fn: Callable[[], _T]) -> Future[_T]:
        with self._lifecycle_lock:
            if self._closed:
                raise RuntimeError("cannot schedule new futures after shutdown")
            if not self._slots.acquire(blocking=False):
                self._record_rejection()
                raise ApiBackpressureError()
            submission = _Submission()
            self._record_queued()
            try:
                future = self._executor.submit(self._run, submission, fn)
            except BaseException:
                self._release_queued(submission)
                raise
            future.add_done_callback(lambda completed: self._on_done(submission, completed))
            return future

    def _run(self, submission: _Submission, fn: Callable[[], _T]) -> _T:
        self._start(submission)
        try:
            return fn()
        finally:
            self._finish(submission)

    def _record_queued(self) -> None:
        with self._state_lock:
            self._queued += 1
            self._peak_queued = max(self._peak_queued, self._queued)
            self._peak_outstanding = max(
                self._peak_outstanding,
                self._active + self._queued,
            )
            self._observe(queued_delta=1)

    def _start(self, submission: _Submission) -> None:
        with self._state_lock:
            if submission.state != "queued":
                raise RuntimeError("stream submission did not start from queued state")
            submission.state = "active"
            self._queued -= 1
            self._active += 1
            self._peak_active = max(self._peak_active, self._active)
            self._observe(active_delta=1, queued_delta=-1)

    def _finish(self, submission: _Submission) -> None:
        with self._state_lock:
            if submission.state != "active":
                return
            submission.state = "released"
            self._active -= 1
            self._observe(active_delta=-1)
        self._slots.release()

    def _release_queued(self, submission: _Submission) -> None:
        with self._state_lock:
            if submission.state != "queued":
                return
            submission.state = "released"
            self._queued -= 1
            self._observe(queued_delta=-1)
        self._slots.release()

    def _on_done(self, submission: _Submission, future: Future[object]) -> None:
        if future.cancelled():
            self._release_queued(submission)

    def _record_rejection(self) -> None:
        with self._state_lock:
            self._rejected += 1
            self._observe(rejected_delta=1)

    def _observe(
        self,
        *,
        active_delta: int = 0,
        queued_delta: int = 0,
        rejected_delta: int = 0,
    ) -> None:
        if self._observer is not None:
            self._observer.record_sse_executor_state(
                active_delta=active_delta,
                queued_delta=queued_delta,
                rejected_delta=rejected_delta,
            )

    def snapshot(self) -> StreamExecutorSnapshot:
        with self._state_lock:
            return StreamExecutorSnapshot(
                max_workers=self.max_workers,
                max_outstanding=self.max_outstanding,
                active=self._active,
                queued=self._queued,
                peak_active=self._peak_active,
                peak_queued=self._peak_queued,
                peak_outstanding=self._peak_outstanding,
                rejected=self._rejected,
            )

    def shutdown(self) -> None:
        with self._lifecycle_lock:
            if self._closed:
                return
            self._closed = True
        self._executor.shutdown(wait=False, cancel_futures=True)


__all__ = ["BoundedStreamExecutor", "StreamExecutorSnapshot"]
```

- [ ] **Step 4: Run executor tests and verify GREEN**

Run:

```powershell
python -m pytest tests/test_serving_stream_executor.py -q
```

Expected: PASS with no leaked worker or warning.

- [ ] **Step 5: Commit the bounded executor**

```powershell
git add -- rag_modules/interfaces/api/services/serving_stream_executor.py tests/test_serving_stream_executor.py
git commit -m "feat: bound SSE executor submissions"
```

### Task 3: SSE Integration And Prometheus Metrics

**Files:**
- Modify: `tests/test_api_sse.py`
- Modify: `tests/test_serving_api_collaborators.py`
- Modify: `tests/test_api_security.py`
- Modify: `rag_modules/interfaces/api/services/serving_streams.py`
- Modify: `rag_modules/interfaces/api/services/serving.py`
- Modify: `rag_modules/telemetry.py`

**Interfaces:**
- Consumes: Task 1 settings and Task 2 `BoundedStreamExecutor`/observer contracts.
- Produces: immediate `RATE_LIMITED` SSE events, `ServingSseRunner.executor_snapshot()`, and the three Prometheus series consumed by Task 4 and operations.

- [ ] **Step 1: Write failing SSE saturation, wiring, and metric tests**

Update the configured-limit assertions to the hard-cut names:

```python
"stream_executor_max_workers": 2,
"stream_executor_max_outstanding": 3,
"stream_event_queue_max_size": 7,
```

```python
self.assertEqual(service._stream_executor_max_workers, 2)
self.assertEqual(service._stream_executor_max_outstanding, 3)
self.assertEqual(service._stream_event_queue_max_size, 7)
```

Add an SSE capacity test using `_BlockingStreamApiSystem`, one executor worker, and one outstanding
slot. Consume the first generator on a background thread until its first message, then consume a
second generator synchronously and assert:

```python
self.assertEqual(
    [event.event for event in rejected_events],
    [AnswerStreamEventType.error, AnswerStreamEventType.done],
)
self.assertEqual(rejected_events[0].data.error.code, "RATE_LIMITED")
self.assertFalse(system.second_stream_started.is_set())
self.assertEqual(service.stream_executor_snapshot().rejected, 1)
```

Use a unique `observability.otel_service_name` in the same fixture, read
`get_runtime_telemetry(config).prometheus_payload().decode()`, and assert:

```python
self.assertIn("graphrag_sse_executor_active 1.0", metrics)
self.assertIn("graphrag_sse_executor_queued 0.0", metrics)
self.assertIn("graphrag_sse_executor_rejected_total 1.0", metrics)
```

Extend the `/metrics` registration test with:

```python
self.assertIn("graphrag_sse_executor_active", authorized.text)
self.assertIn("graphrag_sse_executor_queued", authorized.text)
self.assertIn("graphrag_sse_executor_rejected_total", authorized.text)
```

- [ ] **Step 2: Run the SSE slice and verify RED**

Run:

```powershell
python -m pytest tests/test_api_sse.py tests/test_serving_api_collaborators.py tests/test_api_security.py -q
```

Expected: FAIL because service wiring still reads the retired queue name, submissions remain
unbounded, and telemetry does not register executor metrics.

- [ ] **Step 3: Add telemetry instruments and observer method**

Import `Gauge` beside the existing Prometheus classes and register:

```python
self.sse_executor_active = Gauge(
    "graphrag_sse_executor_active",
    "SSE executor tasks currently running.",
    registry=self.registry,
)
self.sse_executor_queued = Gauge(
    "graphrag_sse_executor_queued",
    "Accepted SSE executor tasks waiting to start.",
    registry=self.registry,
)
self.sse_executor_rejected = Counter(
    "graphrag_sse_executor_rejected_total",
    "SSE executor submissions rejected at capacity.",
    registry=self.registry,
)
```

Add the observer implementation:

```python
def record_sse_executor_state(
    self,
    *,
    active_delta: int = 0,
    queued_delta: int = 0,
    rejected_delta: int = 0,
) -> None:
    if not self.identity.prometheus_enabled:
        return
    if active_delta:
        self.sse_executor_active.inc(active_delta)
    if queued_delta:
        self.sse_executor_queued.inc(queued_delta)
    if rejected_delta:
        self.sse_executor_rejected.inc(rejected_delta)
```

- [ ] **Step 4: Replace raw executor access in the SSE runner**

In `serving_streams.py`, remove `ThreadPoolExecutor` and the executor lock, import
`BoundedStreamExecutor`, `StreamExecutorObserver`, and `StreamExecutorSnapshot`, rename
`queue_max_size` to `event_queue_max_size`, and construct:

```python
self._executor = BoundedStreamExecutor(
    max_workers=self.max_workers,
    max_outstanding=self.max_outstanding,
    observer=executor_observer,
)
```

Session submission becomes:

```python
try:
    self.future = self.runner.submit(self._run)
except ApiBackpressureError:
    yield AnswerStreamEventModel.error(
        code=ErrorCode.RATE_LIMITED,
        request_id=self.request_id,
    )
    yield AnswerStreamEventModel.done()
    return
except RuntimeError:
    yield AnswerStreamEventModel.error(
        code=ErrorCode.SYSTEM_NOT_READY,
        request_id=self.request_id,
    )
    yield AnswerStreamEventModel.done()
    return
```

Expose only focused delegation:

```python
def submit(self, fn: Callable[[], None]) -> Future[None]:
    return self._executor.submit(fn)

def executor_snapshot(self) -> StreamExecutorSnapshot:
    return self._executor.snapshot()

def shutdown(self) -> None:
    self._executor.shutdown()
```

- [ ] **Step 5: Compose new settings and telemetry in the serving service**

Resolve settings without retired fallbacks:

```python
stream_executor_max_workers = getattr(api_settings, "stream_executor_max_workers", 4)
stream_executor_max_outstanding = getattr(api_settings, "stream_executor_max_outstanding", 8)
stream_event_queue_max_size = getattr(api_settings, "stream_event_queue_max_size", 64)
telemetry = get_runtime_telemetry(resolved_config) if resolved_config is not None else None
```

Pass `max_outstanding`, `event_queue_max_size`, and `executor_observer=telemetry` into the runner,
store the three explicit service attributes, and add:

```python
def stream_executor_snapshot(self) -> StreamExecutorSnapshot:
    return self._stream_runner.executor_snapshot()
```

- [ ] **Step 6: Run SSE and telemetry tests and verify GREEN**

Run:

```powershell
python -m pytest tests/test_serving_stream_executor.py tests/test_api_sse.py tests/test_serving_api_collaborators.py tests/test_api_security.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit SSE integration and metrics**

```powershell
git add -- rag_modules/interfaces/api/services/serving_streams.py rag_modules/interfaces/api/services/serving.py rag_modules/telemetry.py tests/test_api_sse.py tests/test_serving_api_collaborators.py tests/test_api_security.py
git commit -m "feat: reject saturated SSE submissions"
```

### Task 4: Deterministic Pressure Proof And Operations Documentation

**Files:**
- Modify: `tests/test_pressure_runner.py`
- Modify: `tests/test_pressure_thresholds.py`
- Modify: `tests/test_pressure_cli.py`
- Modify: `scripts/pressure/scenario.py`
- Modify: `scripts/pressure/cli.py`
- Modify: `scripts/pressure/metrics.py`
- Modify: `scripts/pressure/runner.py`
- Modify: `scripts/pressure/thresholds.py`
- Modify: `docs/api_capacity_and_pressure_thresholds.md`
- Modify: `docs/observability.md`

**Interfaces:**
- Consumes: `GraphRAGServingApiService.stream_executor_snapshot()` from Task 3.
- Produces: scenario fields `stream_executor_max_workers`, `stream_executor_max_outstanding`, and
  `stream_event_queue_max_size`; `metrics.sse.executor`; explicit capacity checks and operator docs.

- [ ] **Step 1: Write failing pressure and CLI tests**

Update `test_sse_runner_capacity_records_terminal_events_without_http` to pass:

```python
requests=8,
workers=6,
stream_executor_max_workers=1,
stream_executor_max_outstanding=2,
stream_event_queue_max_size=4,
```

Assert the structured proof:

```python
executor = sse["executor"]
self.assertEqual(executor["max_workers"], 1)
self.assertEqual(executor["max_outstanding"], 2)
self.assertLessEqual(executor["peak_active"], 1)
self.assertLessEqual(executor["peak_outstanding"], 2)
self.assertGreaterEqual(executor["rejected"], 1)
self.assertEqual(executor["rejected"], sse["rate_limited_error_events"])
self.assertEqual((executor["active"], executor["queued"]), (0, 0))
```

Assert check names include:

```python
{
    "sse_executor_peak_active",
    "sse_executor_peak_outstanding",
    "sse_executor_rejections",
    "sse_executor_rejection_accounting",
    "sse_executor_idle",
}
```

Extend CLI parser tests to verify:

```python
--stream-executor-max-workers 1
--stream-executor-max-outstanding 2
--stream-event-queue-max-size 4
```

- [ ] **Step 2: Run pressure tests and verify RED**

Run:

```powershell
python -m pytest tests/test_pressure_runner.py tests/test_pressure_thresholds.py tests/test_pressure_cli.py -q
```

Expected: FAIL because pressure scenarios, metrics, checks, and CLI do not carry executor capacity.

- [ ] **Step 3: Extend pressure scenario and CLI contracts**

Add defaulted `PressureScenario` fields:

```python
stream_executor_max_workers: int = 4
stream_executor_max_outstanding: int = 8
stream_event_queue_max_size: int = 64
```

Serialize them in `to_dict`, accept optional overrides in `default_pressure_scenario` and
`run_pressure_test`, clamp workers/event size to at least `1`, and clamp maximum outstanding to at
least the resolved executor worker count. Add these parser arguments and forward them from `main`:

```python
parser.add_argument(
    "--stream-executor-max-workers",
    type=int,
    default=defaults.stream_executor_max_workers,
)
parser.add_argument(
    "--stream-executor-max-outstanding",
    type=int,
    default=defaults.stream_executor_max_outstanding,
)
parser.add_argument(
    "--stream-event-queue-max-size",
    type=int,
    default=defaults.stream_event_queue_max_size,
)
```

- [ ] **Step 4: Add structured executor pressure metrics**

Add a frozen `SseExecutorMetrics` dataclass with the same eight integer fields as
`StreamExecutorSnapshot`, a `from_snapshot` constructor, and `to_dict`. Add
`executor: SseExecutorMetrics = field(default_factory=SseExecutorMetrics)` to `SseMetrics` and
serialize it under `"executor"`.

Build the pressure service with:

```python
"stream_executor_max_workers": scenario.stream_executor_max_workers,
"stream_executor_max_outstanding": scenario.stream_executor_max_outstanding,
"stream_event_queue_max_size": scenario.stream_event_queue_max_size,
```

After caller threads finish, collect `service.stream_executor_snapshot()` before shutdown and
construct:

```python
executor=SseExecutorMetrics.from_snapshot(executor_snapshot)
```

- [ ] **Step 5: Add capacity and accounting checks**

Extend `PressureThresholds` with:

```python
max_sse_executor_peak_active: int | None = None
max_sse_executor_peak_outstanding: int | None = None
min_sse_executor_rejections: int | None = None
require_sse_rejection_accounting: bool = False
require_sse_executor_idle: bool = False
```

For `sse_runner_capacity`, set limits from the scenario and require at least one rejection. Add
checks named exactly:

```text
sse_executor_peak_active
sse_executor_peak_outstanding
sse_executor_rejections
sse_executor_rejection_accounting
sse_executor_idle
```

The accounting check passes only when executor rejections equal `RATE_LIMITED` error events. The
idle check passes only when both current active and queued are zero.

- [ ] **Step 6: Update capacity and observability documentation**

In `docs/api_capacity_and_pressure_thresholds.md`, replace the old SSE formula with:

```text
max_outstanding_sse_tasks = stream_executor_max_outstanding
max_stream_event_buffer = outstanding_streams * stream_event_queue_max_size
```

Document that `stream_executor_max_outstanding >= stream_executor_max_workers`, saturation is
non-blocking, and the pressure command can set all three stream capacity arguments.

In `docs/observability.md`, document:

```text
graphrag_sse_executor_active
graphrag_sse_executor_queued
graphrag_sse_executor_rejected_total
```

- [ ] **Step 7: Run pressure tests and verify GREEN**

Run:

```powershell
python -m pytest tests/test_pressure_runner.py tests/test_pressure_thresholds.py tests/test_pressure_cli.py -q
python scripts/pressure_api_service.py --json --scenario-name sse_runner_capacity --requests 8 --workers 6 --answer-delay-ms 50 --max-concurrent-answers 1 --answer-acquire-timeout-seconds 0.01 --stream-executor-max-workers 1 --stream-executor-max-outstanding 2 --stream-event-queue-max-size 4
```

Expected: tests PASS; JSON reports all eight attempts with terminal events, at least one executor
rejection, peak active at most `1`, peak outstanding at most `2`, balanced rejection accounting,
and zero final active/queued counts.

- [ ] **Step 8: Commit pressure proof and docs**

```powershell
git add -- scripts/pressure tests/test_pressure_runner.py tests/test_pressure_thresholds.py tests/test_pressure_cli.py docs/api_capacity_and_pressure_thresholds.md docs/observability.md
git commit -m "test: prove bounded SSE submission under pressure"
```

### Task 5: Hard-Cut Audit And Release Verification

**Files:**
- Modify only files found to violate the hard-cut search or formatting checks.

**Interfaces:**
- Consumes: all behavior and documentation from Tasks 1-4.
- Produces: evidence that old names are retired, relevant suites pass, and release-sensitive checks remain green.

- [ ] **Step 1: Audit retired names and raw submission paths**

Run:

```powershell
rg -n "stream_queue_max_size|API_STREAM_QUEUE_MAX_SIZE" .env.example profiles README.md docs/api_capacity_and_pressure_thresholds.md docs/observability.md rag_modules tests
rg -n "ThreadPoolExecutor|\.submit\(" rag_modules/interfaces/api/services/serving_streams.py rag_modules/interfaces/api/services/serving_stream_executor.py
```

Expected: the retired-name search returns no matches in current code/config/tests/docs; raw
`ThreadPoolExecutor` and its `.submit` exist only inside `serving_stream_executor.py`.

- [ ] **Step 2: Run the full relevant test slice**

Run:

```powershell
python -m pytest tests/test_configuration_section_loaders.py tests/test_serving_stream_executor.py tests/test_api_answer.py tests/test_api_sse.py tests/test_api_public_surface.py tests/test_api_security.py tests/test_serving_api_collaborators.py tests/test_pressure_runner.py tests/test_pressure_thresholds.py tests/test_pressure_cli.py tests/test_entrypoints.py -q
```

Expected: PASS.

- [ ] **Step 3: Run Ruff on every changed Python file**

Run:

```powershell
python -m ruff check rag_modules/configuration/model_sections/api.py rag_modules/configuration/env_specs/api.py rag_modules/interfaces/api/services/serving_stream_executor.py rag_modules/interfaces/api/services/serving_streams.py rag_modules/interfaces/api/services/serving.py rag_modules/telemetry.py scripts/pressure tests/test_configuration_section_loaders.py tests/test_serving_stream_executor.py tests/test_api_sse.py tests/test_serving_api_collaborators.py tests/test_api_security.py tests/test_pressure_runner.py tests/test_pressure_thresholds.py tests/test_pressure_cli.py
python -m ruff format --check rag_modules/configuration/model_sections/api.py rag_modules/configuration/env_specs/api.py rag_modules/interfaces/api/services/serving_stream_executor.py rag_modules/interfaces/api/services/serving_streams.py rag_modules/interfaces/api/services/serving.py rag_modules/telemetry.py scripts/pressure tests/test_configuration_section_loaders.py tests/test_serving_stream_executor.py tests/test_api_sse.py tests/test_serving_api_collaborators.py tests/test_api_security.py tests/test_pressure_runner.py tests/test_pressure_thresholds.py tests/test_pressure_cli.py
```

Expected: both commands exit `0` without modifying files.

- [ ] **Step 4: Run release-sensitive verification**

Run:

```powershell
python scripts/release_gate.py
```

Expected: exit `0` with every release-gate check passing.

- [ ] **Step 5: Inspect final diff and repository state**

Run:

```powershell
git diff --check
git status --short
git log -5 --oneline --decorate
```

Expected: no whitespace errors; only intentional uncommitted verification edits, if any; focused
commits for configuration, executor, integration, and pressure proof are visible.
