from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from .metrics import PressureMetrics
from .scenario import PressureScenario

PressureStatus = Literal["pass", "warn", "fail"]


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
    max_sse_executor_peak_active: int | None = None
    max_sse_executor_peak_outstanding: int | None = None
    min_sse_executor_rejections: int | None = None
    require_sse_rejection_accounting: bool = False
    require_sse_executor_idle: bool = False
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
            "max_sse_executor_peak_active": self.max_sse_executor_peak_active,
            "max_sse_executor_peak_outstanding": self.max_sse_executor_peak_outstanding,
            "min_sse_executor_rejections": self.min_sse_executor_rejections,
            "require_sse_rejection_accounting": self.require_sse_rejection_accounting,
            "require_sse_executor_idle": self.require_sse_executor_idle,
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
    _max_check(
        checks,
        name="sse_executor_peak_active",
        actual=metrics.sse.executor.peak_active,
        limit=thresholds.max_sse_executor_peak_active,
        message="SSE executor active tasks stayed within the worker limit.",
    )
    _max_check(
        checks,
        name="sse_executor_peak_outstanding",
        actual=metrics.sse.executor.peak_outstanding,
        limit=thresholds.max_sse_executor_peak_outstanding,
        message="SSE executor outstanding tasks stayed within the submission limit.",
    )
    _min_check(
        checks,
        name="sse_executor_rejections",
        actual=metrics.sse.executor.rejected,
        limit=thresholds.min_sse_executor_rejections,
        message="SSE executor rejections prove bounded saturation.",
    )
    if thresholds.require_sse_rejection_accounting:
        rejection_accounting = (
            metrics.sse.executor.rejected == metrics.sse.rate_limited_error_events
        )
        checks.append(
            PressureCheck(
                name="sse_executor_rejection_accounting",
                status="pass" if rejection_accounting else "fail",
                actual=rejection_accounting,
                operator="is",
                limit=True,
                message="Executor rejections match RATE_LIMITED SSE events.",
            )
        )
    if thresholds.require_sse_executor_idle:
        executor_idle = metrics.sse.executor.active == 0 and metrics.sse.executor.queued == 0
        checks.append(
            PressureCheck(
                name="sse_executor_idle",
                status="pass" if executor_idle else "fail",
                actual=executor_idle,
                operator="is",
                limit=True,
                message="SSE executor returned to zero active and queued tasks.",
            )
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
            max_sse_executor_peak_active=scenario.stream_executor_max_workers,
            max_sse_executor_peak_outstanding=scenario.stream_executor_max_outstanding,
            min_sse_executor_rejections=1,
            require_sse_rejection_accounting=True,
            require_sse_executor_idle=True,
            max_trace_failed_events=0,
        )
    if scenario.name == "model_call_budget":
        return PressureThresholds(
            max_model_p95_latency_ms=1000.0,
            max_tokens_per_request=4096,
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
