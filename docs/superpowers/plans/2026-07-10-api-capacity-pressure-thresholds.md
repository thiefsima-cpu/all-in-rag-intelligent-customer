# API Capacity Pressure Thresholds Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a deterministic capacity and pressure threshold contract for API concurrency, SSE, model-call budget, and retrieval degraded signals.

**Architecture:** Refactor `scripts/pressure_api_service.py` into explicit scenario, metrics, threshold, check, and report dataclasses. Keep the pressure harness local and deterministic, then document how operators map report fields to runtime API settings and online metrics.

**Tech Stack:** Python 3.11, dataclasses, `argparse`, `json`, `threading`, existing `GraphRAGServingApiService`, `QueryTracer`, pytest/unittest-compatible tests, Markdown docs.

## Global Constraints

- Use Python `>=3.11,<3.12`.
- Do not add production or development dependencies.
- Do not call real model providers, Neo4j, Milvus, or external services from the pressure script.
- Do not change production answer, retrieval, generation, SSE, or API response semantics.
- Do not preserve the old pressure JSON contract at top level.
- Keep pressure results out of `scripts/local_gate.py` and `scripts/release_gate.py`.
- Use `apply_patch` for manual file edits.
- Run focused pressure tests before broader checks.
- Keep line width at or below 100 characters where practical.

---

## File Structure

- `scripts/pressure_api_service.py`
  - Owns local deterministic pressure execution.
  - Defines `PressureScenario`, `PressureMetrics`, `TraceMetrics`, `ModelMetrics`,
    `RetrievalMetrics`, `PressureThresholds`, `PressureCheck`, and `PressureReport`.
  - Exposes `run_pressure_test(...) -> PressureReport`.
  - Exposes `build_pressure_report(...) -> PressureReport` for direct threshold tests.
  - Keeps the existing fake serving application and async trace sink harness local to the script.

- `tests/test_pressure_api_service.py`
  - Owns pressure report contract tests and deterministic admission/backpressure tests.
  - Stops asserting the old top-level `PressureResult` summary shape.

- `docs/api_capacity_and_pressure_thresholds.md`
  - Operator guide for capacity formulas, scenarios, thresholds, report interpretation, and commands.

- `README.md`
  - Adds one short pointer from the common pressure command section to the capacity guide.

---

### Task 1: Pressure Report And Threshold Engine

**Files:**
- Modify: `scripts/pressure_api_service.py`
- Modify: `tests/test_pressure_api_service.py`

**Interfaces:**
- Consumes: existing `_percentile(values: list[float], ratio: float) -> float`.
- Produces:
  - `PressureScenario.to_dict() -> dict[str, object]`
  - `PressureMetrics.to_dict() -> dict[str, object]`
  - `SseMetrics.to_dict() -> dict[str, object]`
  - `PressureThresholds.to_dict() -> dict[str, object]`
  - `PressureCheck.to_dict() -> dict[str, object]`
  - `PressureReport.to_dict() -> dict[str, object]`
  - `build_pressure_report(*, scenario: PressureScenario, metrics: PressureMetrics, thresholds: PressureThresholds) -> PressureReport`
  - `_evaluate_pressure_checks(metrics: PressureMetrics, thresholds: PressureThresholds) -> list[PressureCheck]`

- [ ] **Step 1: Replace pressure tests with failing report contract tests**

Replace `tests/test_pressure_api_service.py` with:

```python
from __future__ import annotations

import unittest

from scripts.pressure_api_service import (
    ModelMetrics,
    PressureMetrics,
    PressureScenario,
    PressureThresholds,
    RetrievalMetrics,
    SseMetrics,
    TraceMetrics,
    build_pressure_report,
    run_pressure_test,
)


def _metrics(
    *,
    requests: int = 10,
    completed_requests: int = 10,
    rejected_requests: int = 0,
    p95_latency_ms: float = 100.0,
    throughput_rps: float = 20.0,
    trace_dropped_events: int = 0,
    trace_failed_events: int = 0,
    retrieval_degraded_rate: float = 0.0,
    degraded_source_counts: dict[str, int] | None = None,
) -> PressureMetrics:
    return PressureMetrics(
        requests=requests,
        workers=2,
        completed_requests=completed_requests,
        rejected_requests=rejected_requests,
        total_duration_ms=500.0,
        throughput_rps=throughput_rps,
        avg_latency_ms=80.0,
        p95_latency_ms=p95_latency_ms,
        trace=TraceMetrics(
            dropped_events=trace_dropped_events,
            queued_events=0,
            written_events=completed_requests,
            failed_events=trace_failed_events,
            closed=True,
            max_queue_size=32,
            async_enabled=True,
        ),
        sse=SseMetrics(),
        model=ModelMetrics(
            p95_latency_ms=25.0,
            input_tokens=100,
            output_tokens=50,
            estimated_cost_usd=0.001,
            degraded_rate=0.0,
        ),
        retrieval=RetrievalMetrics(
            degraded_count=round(completed_requests * retrieval_degraded_rate),
            degraded_rate=retrieval_degraded_rate,
            degraded_source_counts=degraded_source_counts or {},
            max_single_source_degraded_rate=retrieval_degraded_rate,
        ),
    )


class PressureApiServiceTests(unittest.TestCase):
    def test_threshold_equality_passes_for_maximum_and_minimum_limits(self) -> None:
        report = build_pressure_report(
            scenario=PressureScenario(
                name="boundary",
                requests=10,
                workers=2,
                answer_delay_ms=20.0,
                trace_delay_ms=0.0,
                trace_queue_size=32,
                max_concurrent_answers=4,
                answer_acquire_timeout_seconds=0.25,
            ),
            metrics=_metrics(
                requests=10,
                completed_requests=10,
                rejected_requests=0,
                p95_latency_ms=250.0,
                throughput_rps=10.0,
            ),
            thresholds=PressureThresholds(
                max_rejection_rate=0.0,
                max_p95_latency_ms=250.0,
                min_completed_requests=10,
                min_throughput_rps=10.0,
                max_trace_dropped_events=0,
                max_trace_failed_events=0,
                max_retrieval_degraded_rate=0.0,
            ),
        )

        payload = report.to_dict()
        self.assertEqual(payload["status"], "pass")
        self.assertTrue(all(check["status"] == "pass" for check in payload["checks"]))

    def test_threshold_failures_identify_the_failed_check_names(self) -> None:
        report = build_pressure_report(
            scenario=PressureScenario(
                name="failure",
                requests=10,
                workers=2,
                answer_delay_ms=20.0,
                trace_delay_ms=0.0,
                trace_queue_size=32,
                max_concurrent_answers=4,
                answer_acquire_timeout_seconds=0.25,
            ),
            metrics=_metrics(
                requests=10,
                completed_requests=8,
                rejected_requests=2,
                p95_latency_ms=400.0,
                trace_dropped_events=1,
            ),
            thresholds=PressureThresholds(
                max_rejection_rate=0.0,
                max_p95_latency_ms=250.0,
                min_completed_requests=10,
                max_trace_dropped_events=0,
            ),
        )

        payload = report.to_dict()
        failed_names = {
            check["name"] for check in payload["checks"] if check["status"] == "fail"
        }
        self.assertEqual(payload["status"], "fail")
        self.assertIn("rejection_rate", failed_names)
        self.assertIn("p95_latency_ms", failed_names)
        self.assertIn("completed_requests", failed_names)
        self.assertIn("trace_dropped_events", failed_names)

    def test_warning_thresholds_produce_warn_without_failures(self) -> None:
        report = build_pressure_report(
            scenario=PressureScenario(
                name="retrieval-warning",
                requests=100,
                workers=4,
                answer_delay_ms=20.0,
                trace_delay_ms=0.0,
                trace_queue_size=32,
                max_concurrent_answers=4,
                answer_acquire_timeout_seconds=0.25,
            ),
            metrics=_metrics(
                requests=100,
                completed_requests=100,
                retrieval_degraded_rate=0.02,
                degraded_source_counts={"vector": 2},
            ),
            thresholds=PressureThresholds(
                warn_retrieval_degraded_rate=0.01,
                max_retrieval_degraded_rate=0.05,
                max_single_source_degraded_rate=0.03,
            ),
        )

        payload = report.to_dict()
        self.assertEqual(payload["status"], "warn")
        self.assertIn(
            {
                "name": "retrieval_degraded_rate",
                "status": "warn",
                "actual": 0.02,
                "operator": "<=",
                "limit": 0.01,
                "message": "Retrieval degraded rate exceeded the warning budget.",
            },
            payload["checks"],
        )

    def test_report_status_prefers_fail_over_warn_over_pass(self) -> None:
        report = build_pressure_report(
            scenario=PressureScenario(
                name="fail-wins",
                requests=100,
                workers=4,
                answer_delay_ms=20.0,
                trace_delay_ms=0.0,
                trace_queue_size=32,
                max_concurrent_answers=4,
                answer_acquire_timeout_seconds=0.25,
            ),
            metrics=_metrics(
                requests=100,
                completed_requests=100,
                p95_latency_ms=500.0,
                retrieval_degraded_rate=0.02,
                degraded_source_counts={"vector": 2},
            ),
            thresholds=PressureThresholds(
                max_p95_latency_ms=250.0,
                warn_retrieval_degraded_rate=0.01,
                max_retrieval_degraded_rate=0.05,
            ),
        )

        self.assertEqual(report.to_dict()["status"], "fail")

    def test_report_json_contract_uses_structured_sections(self) -> None:
        report = build_pressure_report(
            scenario=PressureScenario(
                name="json-contract",
                requests=10,
                workers=2,
                answer_delay_ms=20.0,
                trace_delay_ms=0.0,
                trace_queue_size=32,
                max_concurrent_answers=4,
                answer_acquire_timeout_seconds=0.25,
            ),
            metrics=_metrics(),
            thresholds=PressureThresholds(max_rejection_rate=0.0),
        )

        payload = report.to_dict()
        self.assertEqual(payload["schema_version"], 1)
        self.assertEqual(set(payload), {"schema_version", "scenario", "status", "metrics", "thresholds", "checks"})
        self.assertIn("trace", payload["metrics"])
        self.assertIn("model", payload["metrics"])
        self.assertIn("retrieval", payload["metrics"])
        self.assertNotIn("trace_stats", payload)
        self.assertNotIn("requests", payload)

    def test_saturation_run_reports_admission_rejections_and_balanced_accounting(self) -> None:
        report = run_pressure_test(
            scenario_name="api_concurrency_saturation",
            requests=12,
            workers=4,
            answer_delay_ms=50.0,
            trace_delay_ms=10.0,
            trace_queue_size=1,
            max_concurrent_answers=1,
            answer_acquire_timeout_seconds=0.01,
        )

        payload = report.to_dict()
        metrics = payload["metrics"]
        self.assertEqual(payload["scenario"]["name"], "api_concurrency_saturation")
        self.assertGreater(metrics["completed_requests"], 0)
        self.assertGreater(metrics["rejected_requests"], 0)
        self.assertEqual(
            metrics["completed_requests"] + metrics["rejected_requests"],
            payload["scenario"]["requests"],
        )
        self.assertIn(payload["status"], {"pass", "warn", "fail"})
        self.assertTrue(
            any(check["name"] == "request_accounting" for check in payload["checks"])
        )


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the focused test and verify it fails**

Run:

```powershell
python -m pytest tests/test_pressure_api_service.py -q
```

Expected: FAIL during import with messages that names such as `ModelMetrics`,
`PressureMetrics`, and `build_pressure_report` cannot be imported from
`scripts.pressure_api_service`.

- [ ] **Step 3: Add dataclasses and threshold evaluation**

In `scripts/pressure_api_service.py`, replace `PressureResult` with these models
and helpers. Keep existing imports and add `field` to the dataclass import:

```python
from dataclasses import dataclass, field
from typing import Literal
```

Insert this code where `PressureResult` used to be:

```python
PressureStatus = Literal["pass", "warn", "fail"]


@dataclass(frozen=True)
class PressureScenario:
    name: str
    requests: int
    workers: int
    answer_delay_ms: float
    trace_delay_ms: float
    trace_queue_size: int
    max_concurrent_answers: int
    answer_acquire_timeout_seconds: float
    synthetic_model_latency_ms: float = 0.0
    synthetic_input_tokens_per_request: int = 0
    synthetic_output_tokens_per_request: int = 0
    input_cost_per_million_tokens: float = 0.0
    output_cost_per_million_tokens: float = 0.0
    retrieval_degraded_every: int = 0
    retrieval_degraded_source: str = "vector"

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "requests": self.requests,
            "workers": self.workers,
            "answer_delay_ms": round(self.answer_delay_ms, 2),
            "trace_delay_ms": round(self.trace_delay_ms, 2),
            "trace_queue_size": self.trace_queue_size,
            "max_concurrent_answers": self.max_concurrent_answers,
            "answer_acquire_timeout_seconds": round(
                self.answer_acquire_timeout_seconds,
                4,
            ),
            "synthetic_model_latency_ms": round(self.synthetic_model_latency_ms, 2),
            "synthetic_input_tokens_per_request": self.synthetic_input_tokens_per_request,
            "synthetic_output_tokens_per_request": self.synthetic_output_tokens_per_request,
            "input_cost_per_million_tokens": self.input_cost_per_million_tokens,
            "output_cost_per_million_tokens": self.output_cost_per_million_tokens,
            "retrieval_degraded_every": self.retrieval_degraded_every,
            "retrieval_degraded_source": self.retrieval_degraded_source,
        }


@dataclass(frozen=True)
class TraceMetrics:
    dropped_events: int = 0
    queued_events: int = 0
    written_events: int = 0
    failed_events: int = 0
    closed: bool = False
    max_queue_size: int = 0
    async_enabled: bool = False

    @classmethod
    def from_stats(cls, stats: dict) -> "TraceMetrics":
        return cls(
            dropped_events=int(stats.get("dropped_events", 0) or 0),
            queued_events=int(stats.get("queued_events", 0) or 0),
            written_events=int(stats.get("written_events", 0) or 0),
            failed_events=int(stats.get("failed_events", 0) or 0),
            closed=bool(stats.get("closed", False)),
            max_queue_size=int(stats.get("max_queue_size", 0) or 0),
            async_enabled=bool(stats.get("async_enabled", False)),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "dropped_events": self.dropped_events,
            "queued_events": self.queued_events,
            "written_events": self.written_events,
            "failed_events": self.failed_events,
            "closed": self.closed,
            "max_queue_size": self.max_queue_size,
            "async_enabled": self.async_enabled,
        }


@dataclass(frozen=True)
class SseMetrics:
    attempted_streams: int = 0
    done_events: int = 0
    result_events: int = 0
    error_events: int = 0
    rate_limited_error_events: int = 0
    unfinished_streams: int = 0
    cancelled_after_done: int = 0

    @property
    def done_event_rate(self) -> float:
        if self.attempted_streams <= 0:
            return 0.0
        return self.done_events / self.attempted_streams

    @property
    def rate_limited_error_rate(self) -> float:
        if self.attempted_streams <= 0:
            return 0.0
        return self.rate_limited_error_events / self.attempted_streams

    def to_dict(self) -> dict[str, object]:
        return {
            "attempted_streams": self.attempted_streams,
            "done_events": self.done_events,
            "done_event_rate": round(self.done_event_rate, 4),
            "result_events": self.result_events,
            "error_events": self.error_events,
            "rate_limited_error_events": self.rate_limited_error_events,
            "rate_limited_error_rate": round(self.rate_limited_error_rate, 4),
            "unfinished_streams": self.unfinished_streams,
            "cancelled_after_done": self.cancelled_after_done,
        }


@dataclass(frozen=True)
class ModelMetrics:
    p95_latency_ms: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    estimated_cost_usd: float = 0.0
    degraded_rate: float = 0.0

    def to_dict(self) -> dict[str, object]:
        return {
            "p95_latency_ms": round(self.p95_latency_ms, 2),
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "estimated_cost_usd": round(self.estimated_cost_usd, 6),
            "degraded_rate": round(self.degraded_rate, 4),
        }


@dataclass(frozen=True)
class RetrievalMetrics:
    degraded_count: int = 0
    degraded_rate: float = 0.0
    degraded_source_counts: dict[str, int] = field(default_factory=dict)
    max_single_source_degraded_rate: float = 0.0

    def to_dict(self) -> dict[str, object]:
        return {
            "degraded_count": self.degraded_count,
            "degraded_rate": round(self.degraded_rate, 4),
            "degraded_source_counts": dict(self.degraded_source_counts),
            "max_single_source_degraded_rate": round(
                self.max_single_source_degraded_rate,
                4,
            ),
        }


@dataclass(frozen=True)
class PressureMetrics:
    requests: int
    workers: int
    completed_requests: int
    rejected_requests: int
    total_duration_ms: float
    throughput_rps: float
    avg_latency_ms: float
    p95_latency_ms: float
    trace: TraceMetrics = field(default_factory=TraceMetrics)
    sse: SseMetrics = field(default_factory=SseMetrics)
    model: ModelMetrics = field(default_factory=ModelMetrics)
    retrieval: RetrievalMetrics = field(default_factory=RetrievalMetrics)

    @property
    def rejection_rate(self) -> float:
        if self.requests <= 0:
            return 0.0
        return self.rejected_requests / self.requests

    @property
    def request_accounting_balanced(self) -> bool:
        return self.completed_requests + self.rejected_requests == self.requests

    def to_dict(self) -> dict[str, object]:
        return {
            "requests": self.requests,
            "workers": self.workers,
            "completed_requests": self.completed_requests,
            "rejected_requests": self.rejected_requests,
            "rejection_rate": round(self.rejection_rate, 4),
            "total_duration_ms": round(self.total_duration_ms, 2),
            "throughput_rps": round(self.throughput_rps, 2),
            "avg_latency_ms": round(self.avg_latency_ms, 2),
            "p95_latency_ms": round(self.p95_latency_ms, 2),
            "trace": self.trace.to_dict(),
            "sse": self.sse.to_dict(),
            "model": self.model.to_dict(),
            "retrieval": self.retrieval.to_dict(),
        }


@dataclass(frozen=True)
class PressureThresholds:
    max_rejection_rate: float | None = None
    min_rejection_rate: float | None = None
    max_p95_latency_ms: float | None = None
    min_completed_requests: int | None = None
    min_throughput_rps: float | None = None
    max_trace_dropped_events: int | None = None
    max_trace_failed_events: int | None = None
    max_rate_limited_error_rate: float | None = None
    min_done_event_rate: float | None = None
    max_unfinished_streams: int | None = None
    max_cancelled_after_done: int | None = None
    warn_retrieval_degraded_rate: float | None = None
    max_retrieval_degraded_rate: float | None = None
    max_single_source_degraded_rate: float | None = None
    max_model_p95_latency_ms: float | None = None
    max_tokens_per_request: int | None = None
    max_estimated_cost_usd: float | None = None
    max_generation_degraded_rate: float | None = None
    require_request_accounting_balance: bool = False

    def to_dict(self) -> dict[str, object]:
        payload = {
            "max_rejection_rate": self.max_rejection_rate,
            "min_rejection_rate": self.min_rejection_rate,
            "max_p95_latency_ms": self.max_p95_latency_ms,
            "min_completed_requests": self.min_completed_requests,
            "min_throughput_rps": self.min_throughput_rps,
            "max_trace_dropped_events": self.max_trace_dropped_events,
            "max_trace_failed_events": self.max_trace_failed_events,
            "max_rate_limited_error_rate": self.max_rate_limited_error_rate,
            "min_done_event_rate": self.min_done_event_rate,
            "max_unfinished_streams": self.max_unfinished_streams,
            "max_cancelled_after_done": self.max_cancelled_after_done,
            "warn_retrieval_degraded_rate": self.warn_retrieval_degraded_rate,
            "max_retrieval_degraded_rate": self.max_retrieval_degraded_rate,
            "max_single_source_degraded_rate": self.max_single_source_degraded_rate,
            "max_model_p95_latency_ms": self.max_model_p95_latency_ms,
            "max_tokens_per_request": self.max_tokens_per_request,
            "max_estimated_cost_usd": self.max_estimated_cost_usd,
            "max_generation_degraded_rate": self.max_generation_degraded_rate,
            "require_request_accounting_balance": self.require_request_accounting_balance,
        }
        return {key: value for key, value in payload.items() if value is not None}


@dataclass(frozen=True)
class PressureCheck:
    name: str
    status: PressureStatus
    actual: float | int | bool
    operator: str
    limit: float | int | bool
    message: str

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "status": self.status,
            "actual": self.actual,
            "operator": self.operator,
            "limit": self.limit,
            "message": self.message,
        }


@dataclass(frozen=True)
class PressureReport:
    scenario: PressureScenario
    metrics: PressureMetrics
    thresholds: PressureThresholds
    checks: list[PressureCheck]
    schema_version: int = 1

    @property
    def status(self) -> PressureStatus:
        statuses = [check.status for check in self.checks]
        if "fail" in statuses:
            return "fail"
        if "warn" in statuses:
            return "warn"
        return "pass"

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "scenario": self.scenario.to_dict(),
            "status": self.status,
            "metrics": self.metrics.to_dict(),
            "thresholds": self.thresholds.to_dict(),
            "checks": [check.to_dict() for check in self.checks],
        }
```

Add these helpers below the dataclasses:

```python
def _max_check(
    checks: list[PressureCheck],
    *,
    name: str,
    actual: float | int,
    limit: float | int | None,
    message: str,
) -> None:
    if limit is None:
        return
    checks.append(
        PressureCheck(
            name=name,
            status="pass" if actual <= limit else "fail",
            actual=round(actual, 4) if isinstance(actual, float) else actual,
            operator="<=",
            limit=limit,
            message=message,
        )
    )


def _min_check(
    checks: list[PressureCheck],
    *,
    name: str,
    actual: float | int,
    limit: float | int | None,
    message: str,
) -> None:
    if limit is None:
        return
    checks.append(
        PressureCheck(
            name=name,
            status="pass" if actual >= limit else "fail",
            actual=round(actual, 4) if isinstance(actual, float) else actual,
            operator=">=",
            limit=limit,
            message=message,
        )
    )


def _warn_max_check(
    checks: list[PressureCheck],
    *,
    name: str,
    actual: float,
    limit: float | None,
    message: str,
) -> None:
    if limit is None:
        return
    checks.append(
        PressureCheck(
            name=name,
            status="pass" if actual <= limit else "warn",
            actual=round(actual, 4),
            operator="<=",
            limit=limit,
            message=message,
        )
    )


def _evaluate_pressure_checks(
    metrics: PressureMetrics,
    thresholds: PressureThresholds,
) -> list[PressureCheck]:
    checks: list[PressureCheck] = []
    _max_check(
        checks,
        name="rejection_rate",
        actual=metrics.rejection_rate,
        limit=thresholds.max_rejection_rate,
        message="Admission rejections are within the scenario budget.",
    )
    _min_check(
        checks,
        name="rejection_rate",
        actual=metrics.rejection_rate,
        limit=thresholds.min_rejection_rate,
        message="Admission rejections prove controlled saturation.",
    )
    _max_check(
        checks,
        name="p95_latency_ms",
        actual=metrics.p95_latency_ms,
        limit=thresholds.max_p95_latency_ms,
        message="Completed request p95 latency is within budget.",
    )
    _min_check(
        checks,
        name="completed_requests",
        actual=metrics.completed_requests,
        limit=thresholds.min_completed_requests,
        message="Completed request count met the scenario requirement.",
    )
    _min_check(
        checks,
        name="throughput_rps",
        actual=metrics.throughput_rps,
        limit=thresholds.min_throughput_rps,
        message="Throughput met the scenario minimum.",
    )
    _max_check(
        checks,
        name="trace_dropped_events",
        actual=metrics.trace.dropped_events,
        limit=thresholds.max_trace_dropped_events,
        message="Trace drops are within the backpressure budget.",
    )
    _max_check(
        checks,
        name="trace_failed_events",
        actual=metrics.trace.failed_events,
        limit=thresholds.max_trace_failed_events,
        message="Trace sink failures are within budget.",
    )
    _max_check(
        checks,
        name="rate_limited_error_rate",
        actual=metrics.sse.rate_limited_error_rate,
        limit=thresholds.max_rate_limited_error_rate,
        message="SSE rate-limited error events are within budget.",
    )
    _min_check(
        checks,
        name="done_event_rate",
        actual=metrics.sse.done_event_rate,
        limit=thresholds.min_done_event_rate,
        message="SSE streams emitted terminal done events.",
    )
    _max_check(
        checks,
        name="unfinished_streams",
        actual=metrics.sse.unfinished_streams,
        limit=thresholds.max_unfinished_streams,
        message="SSE streams all reached terminal events.",
    )
    _max_check(
        checks,
        name="cancelled_after_done",
        actual=metrics.sse.cancelled_after_done,
        limit=thresholds.max_cancelled_after_done,
        message="SSE streams were not cancelled after terminal done events.",
    )
    _warn_max_check(
        checks,
        name="retrieval_degraded_rate",
        actual=metrics.retrieval.degraded_rate,
        limit=thresholds.warn_retrieval_degraded_rate,
        message="Retrieval degraded rate exceeded the warning budget.",
    )
    _max_check(
        checks,
        name="retrieval_degraded_rate",
        actual=metrics.retrieval.degraded_rate,
        limit=thresholds.max_retrieval_degraded_rate,
        message="Retrieval degraded rate is within the failure budget.",
    )
    _max_check(
        checks,
        name="single_source_retrieval_degraded_rate",
        actual=metrics.retrieval.max_single_source_degraded_rate,
        limit=thresholds.max_single_source_degraded_rate,
        message="Single-source retrieval degradation is within budget.",
    )
    _max_check(
        checks,
        name="model_p95_latency_ms",
        actual=metrics.model.p95_latency_ms,
        limit=thresholds.max_model_p95_latency_ms,
        message="Synthetic model p95 latency is within budget.",
    )
    tokens_per_request = (
        (metrics.model.input_tokens + metrics.model.output_tokens) / metrics.completed_requests
        if metrics.completed_requests
        else 0.0
    )
    _max_check(
        checks,
        name="tokens_per_request",
        actual=tokens_per_request,
        limit=thresholds.max_tokens_per_request,
        message="Synthetic token use per completed request is within budget.",
    )
    _max_check(
        checks,
        name="estimated_cost_usd",
        actual=metrics.model.estimated_cost_usd,
        limit=thresholds.max_estimated_cost_usd,
        message="Synthetic model cost is within budget.",
    )
    _max_check(
        checks,
        name="generation_degraded_rate",
        actual=metrics.model.degraded_rate,
        limit=thresholds.max_generation_degraded_rate,
        message="Synthetic generation degraded rate is within budget.",
    )
    if thresholds.require_request_accounting_balance:
        checks.append(
            PressureCheck(
                name="request_accounting",
                status="pass" if metrics.request_accounting_balanced else "fail",
                actual=metrics.request_accounting_balanced,
                operator="is",
                limit=True,
                message="Completed plus rejected requests equals attempted requests.",
            )
        )
    return checks


def build_pressure_report(
    *,
    scenario: PressureScenario,
    metrics: PressureMetrics,
    thresholds: PressureThresholds,
) -> PressureReport:
    return PressureReport(
        scenario=scenario,
        metrics=metrics,
        thresholds=thresholds,
        checks=_evaluate_pressure_checks(metrics, thresholds),
    )
```

- [ ] **Step 4: Run the focused tests and verify Task 1 passes except runtime signature**

Run:

```powershell
python -m pytest tests/test_pressure_api_service.py::PressureApiServiceTests::test_threshold_equality_passes_for_maximum_and_minimum_limits tests/test_pressure_api_service.py::PressureApiServiceTests::test_threshold_failures_identify_the_failed_check_names tests/test_pressure_api_service.py::PressureApiServiceTests::test_warning_thresholds_produce_warn_without_failures tests/test_pressure_api_service.py::PressureApiServiceTests::test_report_status_prefers_fail_over_warn_over_pass tests/test_pressure_api_service.py::PressureApiServiceTests::test_report_json_contract_uses_structured_sections -q
```

Expected: PASS. The saturation runtime test can still fail until Task 2 changes
`run_pressure_test(...)`.

- [ ] **Step 5: Commit Task 1**

Run:

```powershell
git add scripts/pressure_api_service.py tests/test_pressure_api_service.py
git commit -m "feat: add pressure threshold report model"
```

---

### Task 2: Scenario Execution And CLI Contract

**Files:**
- Modify: `scripts/pressure_api_service.py`
- Modify: `tests/test_pressure_api_service.py`

**Interfaces:**
- Consumes:
  - `PressureScenario`
  - `PressureMetrics`
  - `PressureThresholds`
  - `build_pressure_report(...)`
- Produces:
  - `default_pressure_scenario(...) -> PressureScenario`
  - `default_pressure_thresholds(scenario: PressureScenario) -> PressureThresholds`
  - `_run_sse_pressure_scenario(scenario: PressureScenario) -> PressureReport`
  - `run_pressure_test(...) -> PressureReport`
  - CLI `--scenario-name`
  - CLI JSON with `schema_version`, `scenario`, `status`, `metrics`, `thresholds`, and `checks`

- [ ] **Step 1: Add failing CLI and runtime scenario tests**

Append these methods inside `PressureApiServiceTests` in
`tests/test_pressure_api_service.py`:

```python
    def test_default_run_returns_new_report_contract(self) -> None:
        report = run_pressure_test(
            requests=8,
            workers=2,
            answer_delay_ms=5.0,
            trace_delay_ms=0.0,
            trace_queue_size=8,
            max_concurrent_answers=2,
            answer_acquire_timeout_seconds=0.25,
        )

        payload = report.to_dict()
        self.assertEqual(payload["schema_version"], 1)
        self.assertEqual(payload["scenario"]["name"], "api_concurrency_baseline")
        self.assertEqual(payload["metrics"]["requests"], 8)
        self.assertEqual(payload["metrics"]["rejected_requests"], 0)
        self.assertIn(payload["status"], {"pass", "warn", "fail"})
        self.assertIn("max_rejection_rate", payload["thresholds"])

    def test_retrieval_degraded_budget_can_warn_without_live_dependencies(self) -> None:
        report = run_pressure_test(
            scenario_name="retrieval_degraded_budget",
            requests=20,
            workers=2,
            answer_delay_ms=1.0,
            trace_delay_ms=0.0,
            trace_queue_size=8,
            max_concurrent_answers=2,
            answer_acquire_timeout_seconds=0.25,
            retrieval_degraded_every=10,
            retrieval_degraded_source="vector",
        )

        payload = report.to_dict()
        self.assertEqual(payload["scenario"]["name"], "retrieval_degraded_budget")
        self.assertEqual(payload["metrics"]["retrieval"]["degraded_count"], 2)
        self.assertEqual(
            payload["metrics"]["retrieval"]["degraded_source_counts"],
            {"vector": 2},
        )
        self.assertEqual(payload["status"], "warn")

    def test_model_call_budget_uses_synthetic_latency_tokens_and_cost(self) -> None:
        report = run_pressure_test(
            scenario_name="model_call_budget",
            requests=4,
            workers=2,
            answer_delay_ms=1.0,
            trace_delay_ms=0.0,
            trace_queue_size=8,
            max_concurrent_answers=2,
            answer_acquire_timeout_seconds=0.25,
            synthetic_model_latency_ms=35.0,
            synthetic_input_tokens_per_request=100,
            synthetic_output_tokens_per_request=50,
            input_cost_per_million_tokens=2.0,
            output_cost_per_million_tokens=4.0,
        )

        payload = report.to_dict()
        self.assertEqual(payload["scenario"]["name"], "model_call_budget")
        self.assertEqual(payload["metrics"]["model"]["p95_latency_ms"], 35.0)
        self.assertEqual(payload["metrics"]["model"]["input_tokens"], 400)
        self.assertEqual(payload["metrics"]["model"]["output_tokens"], 200)
        self.assertEqual(payload["metrics"]["model"]["estimated_cost_usd"], 0.0016)

    def test_sse_runner_capacity_records_terminal_events_without_http(self) -> None:
        report = run_pressure_test(
            scenario_name="sse_runner_capacity",
            requests=6,
            workers=3,
            answer_delay_ms=50.0,
            trace_delay_ms=0.0,
            trace_queue_size=8,
            max_concurrent_answers=1,
            answer_acquire_timeout_seconds=0.01,
        )

        payload = report.to_dict()
        sse = payload["metrics"]["sse"]
        self.assertEqual(payload["scenario"]["name"], "sse_runner_capacity")
        self.assertEqual(sse["attempted_streams"], 6)
        self.assertEqual(sse["done_events"], 6)
        self.assertEqual(sse["done_event_rate"], 1.0)
        self.assertGreaterEqual(sse["rate_limited_error_events"], 1)
        self.assertEqual(sse["unfinished_streams"], 0)
        self.assertTrue(any(check["name"] == "done_event_rate" for check in payload["checks"]))
```

- [ ] **Step 2: Run runtime tests and verify they fail**

Run:

```powershell
python -m pytest tests/test_pressure_api_service.py::PressureApiServiceTests::test_default_run_returns_new_report_contract tests/test_pressure_api_service.py::PressureApiServiceTests::test_retrieval_degraded_budget_can_warn_without_live_dependencies tests/test_pressure_api_service.py::PressureApiServiceTests::test_model_call_budget_uses_synthetic_latency_tokens_and_cost tests/test_pressure_api_service.py::PressureApiServiceTests::test_sse_runner_capacity_records_terminal_events_without_http tests/test_pressure_api_service.py::PressureApiServiceTests::test_saturation_run_reports_admission_rejections_and_balanced_accounting -q
```

Expected: FAIL because `run_pressure_test(...)` does not accept
`scenario_name`, synthetic model arguments, retrieval degraded arguments, or the
SSE report fields, and still returns the old result shape.

- [ ] **Step 3: Add scenario defaults and metric builders**

Add these helpers above `run_pressure_test(...)` in
`scripts/pressure_api_service.py`:

```python
DEFAULT_SCENARIO_NAME = "api_concurrency_baseline"


def default_pressure_scenario(
    *,
    scenario_name: str = DEFAULT_SCENARIO_NAME,
    requests: int = 200,
    workers: int = 16,
    answer_delay_ms: float = 20.0,
    trace_delay_ms: float = 5.0,
    trace_queue_size: int = 32,
    max_concurrent_answers: int = DEFAULT_MAX_CONCURRENT_ANSWERS,
    answer_acquire_timeout_seconds: float = 0.25,
    synthetic_model_latency_ms: float = 0.0,
    synthetic_input_tokens_per_request: int = 0,
    synthetic_output_tokens_per_request: int = 0,
    input_cost_per_million_tokens: float = 0.0,
    output_cost_per_million_tokens: float = 0.0,
    retrieval_degraded_every: int = 0,
    retrieval_degraded_source: str = "vector",
) -> PressureScenario:
    return PressureScenario(
        name=scenario_name or DEFAULT_SCENARIO_NAME,
        requests=max(1, int(requests)),
        workers=max(1, int(workers)),
        answer_delay_ms=max(0.0, float(answer_delay_ms)),
        trace_delay_ms=max(0.0, float(trace_delay_ms)),
        trace_queue_size=max(0, int(trace_queue_size)),
        max_concurrent_answers=max(1, int(max_concurrent_answers)),
        answer_acquire_timeout_seconds=max(0.0, float(answer_acquire_timeout_seconds)),
        synthetic_model_latency_ms=max(0.0, float(synthetic_model_latency_ms)),
        synthetic_input_tokens_per_request=max(0, int(synthetic_input_tokens_per_request)),
        synthetic_output_tokens_per_request=max(0, int(synthetic_output_tokens_per_request)),
        input_cost_per_million_tokens=max(0.0, float(input_cost_per_million_tokens)),
        output_cost_per_million_tokens=max(0.0, float(output_cost_per_million_tokens)),
        retrieval_degraded_every=max(0, int(retrieval_degraded_every)),
        retrieval_degraded_source=str(retrieval_degraded_source or "vector"),
    )


def default_pressure_thresholds(scenario: PressureScenario) -> PressureThresholds:
    if scenario.name == "api_concurrency_saturation":
        acquire_timeout_ms = scenario.answer_acquire_timeout_seconds * 1000.0
        return PressureThresholds(
            min_rejection_rate=0.05,
            max_p95_latency_ms=scenario.answer_delay_ms + acquire_timeout_ms + 150.0,
            max_trace_failed_events=0,
            require_request_accounting_balance=True,
        )
    if scenario.name == "retrieval_degraded_budget":
        return PressureThresholds(
            warn_retrieval_degraded_rate=0.02,
            max_retrieval_degraded_rate=0.05,
            max_single_source_degraded_rate=0.03,
            max_trace_failed_events=0,
            require_request_accounting_balance=True,
        )
    if scenario.name == "sse_runner_capacity":
        return PressureThresholds(
            max_rate_limited_error_rate=1.0,
            min_done_event_rate=1.0,
            max_unfinished_streams=0,
            max_cancelled_after_done=0,
            max_trace_failed_events=0,
        )
    if scenario.name == "model_call_budget":
        max_tokens = (
            scenario.synthetic_input_tokens_per_request
            + scenario.synthetic_output_tokens_per_request
        )
        return PressureThresholds(
            max_model_p95_latency_ms=max(1.0, scenario.synthetic_model_latency_ms),
            max_tokens_per_request=max_tokens,
            max_estimated_cost_usd=1.0,
            max_generation_degraded_rate=0.0,
            max_trace_failed_events=0,
            require_request_accounting_balance=True,
        )
    return PressureThresholds(
        max_rejection_rate=0.0,
        max_p95_latency_ms=250.0,
        min_completed_requests=scenario.requests,
        max_trace_dropped_events=0,
        max_retrieval_degraded_rate=0.0,
        max_trace_failed_events=0,
        require_request_accounting_balance=True,
    )


def _retrieval_metrics_from_scenario(
    *,
    scenario: PressureScenario,
    completed_requests: int,
) -> RetrievalMetrics:
    if completed_requests <= 0 or scenario.retrieval_degraded_every <= 0:
        return RetrievalMetrics()
    degraded_count = completed_requests // scenario.retrieval_degraded_every
    degraded_rate = degraded_count / completed_requests
    source_counts = (
        {scenario.retrieval_degraded_source: degraded_count} if degraded_count else {}
    )
    max_source_rate = degraded_rate if degraded_count else 0.0
    return RetrievalMetrics(
        degraded_count=degraded_count,
        degraded_rate=degraded_rate,
        degraded_source_counts=source_counts,
        max_single_source_degraded_rate=max_source_rate,
    )


def _model_metrics_from_scenario(
    *,
    scenario: PressureScenario,
    completed_requests: int,
) -> ModelMetrics:
    input_tokens = completed_requests * scenario.synthetic_input_tokens_per_request
    output_tokens = completed_requests * scenario.synthetic_output_tokens_per_request
    estimated_cost = (
        input_tokens / 1_000_000 * scenario.input_cost_per_million_tokens
        + output_tokens / 1_000_000 * scenario.output_cost_per_million_tokens
    )
    return ModelMetrics(
        p95_latency_ms=scenario.synthetic_model_latency_ms,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        estimated_cost_usd=estimated_cost,
        degraded_rate=0.0,
    )


def _empty_pressure_metrics(
    *,
    scenario: PressureScenario,
    trace: TraceMetrics,
    sse: SseMetrics | None = None,
) -> PressureMetrics:
    return PressureMetrics(
        requests=scenario.requests,
        workers=scenario.workers,
        completed_requests=0,
        rejected_requests=0,
        total_duration_ms=0.0,
        throughput_rps=0.0,
        avg_latency_ms=0.0,
        p95_latency_ms=0.0,
        trace=trace,
        sse=sse or SseMetrics(),
        model=_model_metrics_from_scenario(scenario=scenario, completed_requests=0),
        retrieval=_retrieval_metrics_from_scenario(scenario=scenario, completed_requests=0),
    )
```

- [ ] **Step 4: Add service-level SSE pressure execution**

Add this helper above `run_pressure_test(...)`:

```python
def _run_sse_pressure_scenario(scenario: PressureScenario) -> PressureReport:
    tracer = _build_tracer(
        queue_size=scenario.trace_queue_size,
        trace_delay_ms=scenario.trace_delay_ms,
    )
    system = _PressureTestSystem(
        answer_delay_ms=scenario.answer_delay_ms,
        query_tracer=tracer,
    )
    service = GraphRAGServingApiService(
        system=system,
        config=build_test_config(
            {
                "api": {
                    "max_concurrent_answers": scenario.max_concurrent_answers,
                    "answer_acquire_timeout_seconds": (
                        scenario.answer_acquire_timeout_seconds
                    ),
                    "stream_executor_max_workers": max(1, scenario.workers),
                    "stream_queue_max_size": max(1, scenario.trace_queue_size),
                }
            }
        ),
    )
    next_request = 0
    request_lock = threading.Lock()
    counts_lock = threading.Lock()
    done_events = 0
    result_events = 0
    error_events = 0
    rate_limited_error_events = 0
    unfinished_streams = 0

    def worker_loop(worker_id: int) -> None:
        nonlocal next_request
        nonlocal done_events, result_events, error_events, rate_limited_error_events
        nonlocal unfinished_streams
        while True:
            with request_lock:
                if next_request >= scenario.requests:
                    return
                request_id = next_request
                next_request += 1
            events = list(
                service.stream_answer_question_events(
                    question=f"sse-pressure-{worker_id}-{request_id}",
                    request_id=f"sse-pressure-{request_id}",
                    include_traces=False,
                )
            )
            event_names = [str(event.event.value) for event in events]
            stream_done = "done" in event_names
            stream_result_events = event_names.count("result")
            stream_error_events = event_names.count("error")
            stream_rate_limited = any(
                getattr(getattr(event.data, "error", None), "code", None) == "RATE_LIMITED"
                or str(getattr(getattr(event.data, "error", None), "code", "")) == "RATE_LIMITED"
                for event in events
            )
            with counts_lock:
                done_events += 1 if stream_done else 0
                result_events += stream_result_events
                error_events += stream_error_events
                rate_limited_error_events += 1 if stream_rate_limited else 0
                unfinished_streams += 0 if stream_done else 1

    threads = [
        threading.Thread(
            target=worker_loop,
            args=(worker_id,),
            name=f"pressure-sse-worker-{worker_id}",
        )
        for worker_id in range(scenario.workers)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    service.shutdown()
    trace = TraceMetrics.from_stats(tracer.stats())
    sse = SseMetrics(
        attempted_streams=scenario.requests,
        done_events=done_events,
        result_events=result_events,
        error_events=error_events,
        rate_limited_error_events=rate_limited_error_events,
        unfinished_streams=unfinished_streams,
        cancelled_after_done=0,
    )
    return build_pressure_report(
        scenario=scenario,
        metrics=_empty_pressure_metrics(scenario=scenario, trace=trace, sse=sse),
        thresholds=default_pressure_thresholds(scenario),
    )
```

- [ ] **Step 5: Replace `run_pressure_test(...)` with report-producing execution**

Replace the existing `run_pressure_test(...)` function with:

```python
def run_pressure_test(
    *,
    scenario_name: str = DEFAULT_SCENARIO_NAME,
    requests: int = 200,
    workers: int = 16,
    answer_delay_ms: float = 20.0,
    trace_delay_ms: float = 5.0,
    trace_queue_size: int = 32,
    max_concurrent_answers: int = DEFAULT_MAX_CONCURRENT_ANSWERS,
    answer_acquire_timeout_seconds: float = 0.25,
    synthetic_model_latency_ms: float = 0.0,
    synthetic_input_tokens_per_request: int = 0,
    synthetic_output_tokens_per_request: int = 0,
    input_cost_per_million_tokens: float = 0.0,
    output_cost_per_million_tokens: float = 0.0,
    retrieval_degraded_every: int = 0,
    retrieval_degraded_source: str = "vector",
) -> PressureReport:
    scenario = default_pressure_scenario(
        scenario_name=scenario_name,
        requests=requests,
        workers=workers,
        answer_delay_ms=answer_delay_ms,
        trace_delay_ms=trace_delay_ms,
        trace_queue_size=trace_queue_size,
        max_concurrent_answers=max_concurrent_answers,
        answer_acquire_timeout_seconds=answer_acquire_timeout_seconds,
        synthetic_model_latency_ms=synthetic_model_latency_ms,
        synthetic_input_tokens_per_request=synthetic_input_tokens_per_request,
        synthetic_output_tokens_per_request=synthetic_output_tokens_per_request,
        input_cost_per_million_tokens=input_cost_per_million_tokens,
        output_cost_per_million_tokens=output_cost_per_million_tokens,
        retrieval_degraded_every=retrieval_degraded_every,
        retrieval_degraded_source=retrieval_degraded_source,
    )
    if scenario.name == "sse_runner_capacity":
        return _run_sse_pressure_scenario(scenario)
    tracer = _build_tracer(
        queue_size=scenario.trace_queue_size,
        trace_delay_ms=scenario.trace_delay_ms,
    )
    system = _PressureTestSystem(
        answer_delay_ms=scenario.answer_delay_ms,
        query_tracer=tracer,
    )
    service = GraphRAGServingApiService(
        system=system,
        config=build_test_config(
            {
                "api": {
                    "max_concurrent_answers": scenario.max_concurrent_answers,
                    "answer_acquire_timeout_seconds": (
                        scenario.answer_acquire_timeout_seconds
                    ),
                }
            }
        ),
    )
    latencies: list[float] = []
    latencies_lock = threading.Lock()
    counts_lock = threading.Lock()
    next_request = 0
    request_lock = threading.Lock()
    completed_requests = 0
    rejected_requests = 0

    def worker_loop(worker_id: int) -> None:
        nonlocal next_request, completed_requests, rejected_requests
        while True:
            with request_lock:
                if next_request >= scenario.requests:
                    return
                request_id = next_request
                next_request += 1
            question = f"pressure-{worker_id}-{request_id}"
            start = time.perf_counter()
            try:
                service.answer_question(question=question)
            except ApiBackpressureError:
                with counts_lock:
                    rejected_requests += 1
            else:
                latency_ms = (time.perf_counter() - start) * 1000
                with counts_lock:
                    completed_requests += 1
                with latencies_lock:
                    latencies.append(latency_ms)

    started = time.perf_counter()
    threads = [
        threading.Thread(
            target=worker_loop,
            args=(worker_id,),
            name=f"pressure-worker-{worker_id}",
        )
        for worker_id in range(scenario.workers)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    total_duration_ms = (time.perf_counter() - started) * 1000
    service.shutdown()
    trace = TraceMetrics.from_stats(tracer.stats())
    metrics = PressureMetrics(
        requests=scenario.requests,
        workers=scenario.workers,
        completed_requests=completed_requests,
        rejected_requests=rejected_requests,
        total_duration_ms=total_duration_ms,
        throughput_rps=(completed_requests / (total_duration_ms / 1000.0))
        if total_duration_ms
        else 0.0,
        avg_latency_ms=(sum(latencies) / len(latencies)) if latencies else 0.0,
        p95_latency_ms=_percentile(latencies, 0.95),
        trace=trace,
        sse=SseMetrics(),
        model=_model_metrics_from_scenario(
            scenario=scenario,
            completed_requests=completed_requests,
        ),
        retrieval=_retrieval_metrics_from_scenario(
            scenario=scenario,
            completed_requests=completed_requests,
        ),
    )
    return build_pressure_report(
        scenario=scenario,
        metrics=metrics,
        thresholds=default_pressure_thresholds(scenario),
    )
```

- [ ] **Step 6: Replace CLI parsing and rendering**

In `_parse_args()`, add scenario and synthetic budget flags:

```python
    parser.add_argument("--scenario-name", default=DEFAULT_SCENARIO_NAME)
    parser.add_argument("--synthetic-model-latency-ms", type=float, default=0.0)
    parser.add_argument("--synthetic-input-tokens-per-request", type=int, default=0)
    parser.add_argument("--synthetic-output-tokens-per-request", type=int, default=0)
    parser.add_argument("--input-cost-per-million-tokens", type=float, default=0.0)
    parser.add_argument("--output-cost-per-million-tokens", type=float, default=0.0)
    parser.add_argument("--retrieval-degraded-every", type=int, default=0)
    parser.add_argument("--retrieval-degraded-source", default="vector")
```

Change the existing JSON help text to:

```python
    parser.add_argument("--json", action="store_true", help="Emit report as JSON.")
```

Replace `main()` with:

```python
def _print_human_report(payload: dict[str, object]) -> None:
    scenario = payload["scenario"]
    metrics = payload["metrics"]
    thresholds = payload["thresholds"]
    checks = payload["checks"]
    print("Pressure report")
    print("---------------")
    print(f"Scenario: {scenario['name']}")
    print(f"Status: {payload['status']}")
    print(f"Requests: {scenario['requests']}")
    print(f"Workers: {scenario['workers']}")
    print(f"Completed requests: {metrics['completed_requests']}")
    print(f"Rejected requests: {metrics['rejected_requests']}")
    print(f"Rejection rate: {metrics['rejection_rate']}")
    print(f"Throughput (req/s): {metrics['throughput_rps']}")
    print(f"Average latency (ms): {metrics['avg_latency_ms']}")
    print(f"P95 latency (ms): {metrics['p95_latency_ms']}")
    print(f"Thresholds: {json.dumps(thresholds, ensure_ascii=False, sort_keys=True)}")
    print("Checks:")
    for check in checks:
        print(
            f"- {check['status']} {check['name']}: "
            f"{check['actual']} {check['operator']} {check['limit']} "
            f"({check['message']})"
        )


def main() -> None:
    args = _parse_args()
    report = run_pressure_test(
        scenario_name=args.scenario_name,
        requests=args.requests,
        workers=args.workers,
        answer_delay_ms=args.answer_delay_ms,
        trace_delay_ms=args.trace_delay_ms,
        trace_queue_size=args.trace_queue_size,
        max_concurrent_answers=args.max_concurrent_answers,
        answer_acquire_timeout_seconds=args.answer_acquire_timeout_seconds,
        synthetic_model_latency_ms=args.synthetic_model_latency_ms,
        synthetic_input_tokens_per_request=args.synthetic_input_tokens_per_request,
        synthetic_output_tokens_per_request=args.synthetic_output_tokens_per_request,
        input_cost_per_million_tokens=args.input_cost_per_million_tokens,
        output_cost_per_million_tokens=args.output_cost_per_million_tokens,
        retrieval_degraded_every=args.retrieval_degraded_every,
        retrieval_degraded_source=args.retrieval_degraded_source,
    )
    payload = report.to_dict()
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    _print_human_report(payload)
```

- [ ] **Step 7: Run all pressure tests**

Run:

```powershell
python -m pytest tests/test_pressure_api_service.py -q
```

Expected: PASS.

- [ ] **Step 8: Run the default CLI report**

Run:

```powershell
python scripts/pressure_api_service.py --json --requests 8 --workers 2 --answer-delay-ms 5 --trace-delay-ms 0 --trace-queue-size 8 --max-concurrent-answers 2
```

Expected: JSON with top-level keys `schema_version`, `scenario`, `status`,
`metrics`, `thresholds`, and `checks`. The top-level output must not include
old keys such as `requests`, `workers`, or `trace_stats`.

- [ ] **Step 9: Run the SSE scenario CLI**

Run:

```powershell
python scripts/pressure_api_service.py --json --scenario-name sse_runner_capacity --requests 6 --workers 3 --answer-delay-ms 50 --trace-delay-ms 0 --trace-queue-size 8 --max-concurrent-answers 1 --answer-acquire-timeout-seconds 0.01
```

Expected: JSON with `scenario.name: sse_runner_capacity`,
`metrics.sse.done_event_rate: 1.0`, and at least one
`metrics.sse.rate_limited_error_events`.

- [ ] **Step 10: Commit Task 2**

Run:

```powershell
git add scripts/pressure_api_service.py tests/test_pressure_api_service.py
git commit -m "feat: classify pressure scenarios with thresholds"
```

---

### Task 3: Capacity Guide And README Link

**Files:**
- Create: `docs/api_capacity_and_pressure_thresholds.md`
- Modify: `README.md`

**Interfaces:**
- Consumes: `graph-rag-pressure` entry point and `python scripts/pressure_api_service.py --json`.
- Produces: operator documentation for formulas, scenarios, thresholds, and report interpretation.

- [ ] **Step 1: Create the capacity guide**

Create `docs/api_capacity_and_pressure_thresholds.md` with:

```markdown
# API Capacity And Pressure Thresholds

This guide explains how to size and verify the serving API for answer
concurrency, SSE streams, synthetic model-call budgets, and retrieval degraded
signals. The pressure tool is local and deterministic. It does not call model
providers, Neo4j, Milvus, or other external services.

Host-dependent pressure results are not part of the offline release gate. Use
them as local evidence when changing API admission, stream execution, generation
budgets, retrieval diagnostics, or deployment profiles.

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
max_stream_event_buffer = active_streams * stream_queue_max_size
```

The event queue is per stream. Size `api.stream_queue_max_size` for slow
consumers, and size `api.stream_executor_max_workers` with the same headroom
used for answer permits.

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
| `model_call_budget` | Evaluate synthetic provider latency, token, and cost budgets. | `python scripts/pressure_api_service.py --json --scenario-name model_call_budget --synthetic-model-latency-ms 35 --synthetic-input-tokens-per-request 100 --synthetic-output-tokens-per-request 50` | `pass` when synthetic budget checks stay within limits |
| `retrieval_degraded_budget` | Verify degraded retrieval is counted and classified. | `python scripts/pressure_api_service.py --json --scenario-name retrieval_degraded_budget --retrieval-degraded-every 10` | `warn` at the default 10% injected degraded rate |

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

## Metric Definitions

- `metrics.completed_requests`: requests admitted and completed by the serving service.
- `metrics.rejected_requests`: requests rejected by answer admission.
- `metrics.rejection_rate`: rejected requests divided by attempted requests.
- `metrics.p95_latency_ms`: p95 latency for completed requests only.
- `metrics.trace.dropped_events`: trace events dropped by async trace backpressure.
- `metrics.trace.failed_events`: trace sink write failures.
- `metrics.model.p95_latency_ms`: synthetic model latency configured for the scenario.
- `metrics.model.estimated_cost_usd`: synthetic token cost for completed requests.
- `metrics.retrieval.degraded_rate`: deterministic degraded retrieval count divided by completed requests.
- `metrics.retrieval.degraded_source_counts`: degraded count by safe public source name.

## Threshold Interpretation

Use `api_concurrency_baseline` before and after changing admission, trace, or
answer workflow settings. Use `api_concurrency_saturation` when validating that
overload rejects quickly instead of creating unbounded latency.

Use `model_call_budget` to review model latency and cost policy changes without
provider calls. Use live observability for production provider SLOs.

Use `retrieval_degraded_budget` to verify degraded retrieval reporting and
classification. A warning means the signal is visible but above the healthy
baseline. A failure means the degraded rate or source concentration exceeds the
configured budget.
```

- [ ] **Step 2: Add README link near the pressure command**

Find the common command block in `README.md` that contains:

```powershell
python scripts/pressure_api_service.py --json
```

Add this sentence immediately after the paragraph that explains the local gate
and quality gates:

```markdown
API capacity formulas and pressure threshold interpretation are documented in
[docs/api_capacity_and_pressure_thresholds.md](docs/api_capacity_and_pressure_thresholds.md).
```

- [ ] **Step 3: Run docs diff check**

Run:

```powershell
git diff --check
```

Expected: no output and exit code `0`.

- [ ] **Step 4: Commit Task 3**

Run:

```powershell
git add docs/api_capacity_and_pressure_thresholds.md README.md
git commit -m "docs: document API pressure thresholds"
```

---

### Task 4: Final Verification

**Files:**
- Verify: `scripts/pressure_api_service.py`
- Verify: `tests/test_pressure_api_service.py`
- Verify: `docs/api_capacity_and_pressure_thresholds.md`
- Verify: `README.md`

**Interfaces:**
- Consumes: all previous task deliverables.
- Produces: final confidence that the focused pressure workflow and docs are coherent.

- [ ] **Step 1: Run focused pressure tests**

Run:

```powershell
python -m pytest tests/test_pressure_api_service.py -q
```

Expected: PASS.

- [ ] **Step 2: Run the default pressure CLI**

Run:

```powershell
python scripts/pressure_api_service.py --json --requests 8 --workers 2 --answer-delay-ms 5 --trace-delay-ms 0 --trace-queue-size 8 --max-concurrent-answers 2
```

Expected: JSON with `schema_version: 1`, `scenario.name:
api_concurrency_baseline`, and no old top-level `trace_stats`.

- [ ] **Step 3: Run the saturation pressure CLI**

Run:

```powershell
python scripts/pressure_api_service.py --json --scenario-name api_concurrency_saturation --requests 12 --workers 4 --answer-delay-ms 50 --trace-delay-ms 10 --trace-queue-size 1 --max-concurrent-answers 1 --answer-acquire-timeout-seconds 0.01
```

Expected: JSON with `scenario.name: api_concurrency_saturation`, at least one
rejected request, and a `request_accounting` check.

- [ ] **Step 4: Run import boundary check for script importability**

Run:

```powershell
python -m pytest tests/test_module_boundary_facades.py::ModuleBoundaryFacadeTests::test_operational_scripts_import_canonical_contracts -q
```

Expected: PASS.

- [ ] **Step 5: Run diff whitespace check**

Run:

```powershell
git diff --check
```

Expected: no output and exit code `0`.

- [ ] **Step 6: Review final diff**

Run:

```powershell
git diff --stat
git diff -- scripts/pressure_api_service.py tests/test_pressure_api_service.py docs/api_capacity_and_pressure_thresholds.md README.md
```

Expected: diff only contains the planned pressure script, pressure tests,
capacity guide, and README link.

- [ ] **Step 7: Commit final verification adjustments if needed**

If verification required small fixes, run:

```powershell
git add scripts/pressure_api_service.py tests/test_pressure_api_service.py docs/api_capacity_and_pressure_thresholds.md README.md
git commit -m "test: verify pressure threshold workflow"
```

Skip this commit when Task 4 does not change files.
