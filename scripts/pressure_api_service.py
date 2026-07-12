from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Literal

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from rag_modules.app.diagnostics import ArtifactManifestDiagnostics, StartupDiagnostics
from rag_modules.application.answering.answer_models import (
    QuestionAnswerResponse,
    QuestionAnswerSummary,
)
from rag_modules.configuration.testing import build_test_config
from rag_modules.contracts import EvidenceDocument
from rag_modules.interfaces.api.services import GraphRAGServingApiService
from rag_modules.interfaces.api.services.errors import ApiBackpressureError
from rag_modules.kernel.artifacts import ARTIFACT_HEALTH_READY
from rag_modules.observability.tracing import QueryTracer
from rag_modules.observability.tracing_sinks import AsyncQueryTraceSink


class _SlowCaptureTraceSink:
    def __init__(self, *, write_delay_ms: float) -> None:
        self.write_delay_seconds = max(0.0, float(write_delay_ms) / 1000.0)
        self.events = []
        self.closed = False
        self._lock = threading.Lock()

    def write(self, event) -> None:
        if self.write_delay_seconds > 0:
            time.sleep(self.write_delay_seconds)
        with self._lock:
            self.events.append(event)

    def close(self) -> None:
        self.closed = True

    def stats(self) -> dict[str, int | bool | str]:
        with self._lock:
            persisted = len(self.events)
        return {
            "sink_type": "slow_capture",
            "async_enabled": False,
            "persisted_events": persisted,
            "dropped_events": 0,
            "queued_events": 0,
            "closed": self.closed,
        }


def _diagnostics() -> StartupDiagnostics:
    return StartupDiagnostics(
        mode="serve",
        llm_model="qwen3.7-plus",
        embedding_model="qwen3-vl-embedding",
        rerank_model="qwen3-vl-rerank",
        trace_enabled=True,
        trace_path="pressure-trace.jsonl",
        trace_stats={"dropped_events": 0, "queued_events": 0, "async_enabled": True},
        build_initialized=False,
        serving_initialized=True,
        artifacts_ready=True,
        system_ready=True,
        retrieval_engines_initialized=True,
        manifest=ArtifactManifestDiagnostics(
            stage="ready",
            health=ARTIFACT_HEALTH_READY,
            updated_at="",
            collection_name="pressure",
            manifest_path="storage/indexes/artifact_manifest.json",
            documents_path="",
            chunks_path="",
            total_documents=1,
            total_chunks=1,
            vector_rows=1,
            cache_hit=False,
            last_error="",
        ),
    )


class _PressureTestSystem:
    def __init__(
        self,
        *,
        answer_delay_ms: float,
        query_tracer: QueryTracer,
    ) -> None:
        self.answer_delay_seconds = max(0.0, float(answer_delay_ms) / 1000.0)
        self.query_tracer = query_tracer
        self.system_ready = True
        self.serving_initialized = True
        self.answer_calls = 0
        self._lock = threading.Lock()

    def is_build_initialized(self) -> bool:
        return False

    def is_serving_initialized(self) -> bool:
        return self.serving_initialized

    def initialize_serving_runtime(self, progress=None, *, query_tracer=None, neo4j_manager=None):
        del progress, query_tracer, neo4j_manager
        self.serving_initialized = True
        return None

    def collect_system_stats(self) -> dict:
        return {
            "ready": True,
            "trace_stats": self.query_tracer.stats(),
            "artifact_manifest": {"health": ARTIFACT_HEALTH_READY},
        }

    def collect_startup_diagnostics(self, mode: str) -> StartupDiagnostics:
        del mode
        return _diagnostics()

    def answer_question_response(
        self,
        question: str,
        *,
        stream: bool = False,
        explain_routing: bool = False,
        message_callback=None,
        chunk_callback=None,
        control=None,
    ):
        del stream, explain_routing, message_callback, chunk_callback
        if control is not None:
            control.raise_if_cancelled()
        with self._lock:
            self.answer_calls += 1
        start = time.perf_counter()
        if self.answer_delay_seconds > 0:
            time.sleep(self.answer_delay_seconds)
        if control is not None:
            control.raise_if_cancelled()
        latency_ms = (time.perf_counter() - start) * 1000
        self.query_tracer.record(
            query=question,
            analysis=None,
            documents=[EvidenceDocument(content="pressure-doc", recipe_name="pressure")],
            latency_ms=latency_ms,
            answer="ok",
        )
        return QuestionAnswerResponse(
            summary=QuestionAnswerSummary(
                answer=f"answer:{question}",
                strategy="hybrid_traditional",
                latency_ms=latency_ms,
                doc_count=1,
                has_evidence=True,
            )
        )

    def close(self) -> None:
        self.query_tracer.close()


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


DEFAULT_PRESSURE_SCENARIO = PressureScenario(
    name="api_concurrency_baseline",
    requests=200,
    workers=4,
    answer_delay_ms=20.0,
    trace_delay_ms=0.0,
    trace_queue_size=32,
    max_concurrent_answers=4,
    answer_acquire_timeout_seconds=0.25,
)


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

    @property
    def exit_code(self) -> int:
        return 1 if self.status == "fail" else 0

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "scenario": self.scenario.to_dict(),
            "status": self.status,
            "metrics": self.metrics.to_dict(),
            "thresholds": self.thresholds.to_dict(),
            "checks": [check.to_dict() for check in self.checks],
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


def _build_tracer(*, queue_size: int, trace_delay_ms: float) -> QueryTracer:
    delegate = _SlowCaptureTraceSink(write_delay_ms=trace_delay_ms)
    sink = AsyncQueryTraceSink(delegate, max_queue_size=queue_size)
    config = build_test_config(
        {
            "observability": {
                "enable_query_tracing": True,
                "query_trace_path": "pressure-trace.jsonl",
                "query_trace_async_enabled": True,
                "query_trace_max_queue_size": queue_size,
            }
        }
    )
    return QueryTracer(config, sink=sink)


def _percentile(values: list[float], ratio: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int((len(ordered) - 1) * ratio)))
    return ordered[index]


def default_pressure_scenario(
    *,
    scenario_name: str | None = None,
    requests: int | None = None,
    workers: int | None = None,
    answer_delay_ms: float | None = None,
    trace_delay_ms: float | None = None,
    trace_queue_size: int | None = None,
    max_concurrent_answers: int | None = None,
    answer_acquire_timeout_seconds: float | None = None,
    synthetic_model_latency_ms: float | None = None,
    synthetic_input_tokens_per_request: int | None = None,
    synthetic_output_tokens_per_request: int | None = None,
    input_cost_per_million_tokens: float | None = None,
    output_cost_per_million_tokens: float | None = None,
    retrieval_degraded_every: int | None = None,
    retrieval_degraded_source: str | None = None,
) -> PressureScenario:
    defaults = DEFAULT_PRESSURE_SCENARIO
    return PressureScenario(
        name=str(scenario_name or defaults.name),
        requests=max(1, int(defaults.requests if requests is None else requests)),
        workers=max(1, int(defaults.workers if workers is None else workers)),
        answer_delay_ms=max(
            0.0,
            float(defaults.answer_delay_ms if answer_delay_ms is None else answer_delay_ms),
        ),
        trace_delay_ms=max(
            0.0,
            float(defaults.trace_delay_ms if trace_delay_ms is None else trace_delay_ms),
        ),
        trace_queue_size=max(
            0,
            int(defaults.trace_queue_size if trace_queue_size is None else trace_queue_size),
        ),
        max_concurrent_answers=max(
            1,
            int(
                defaults.max_concurrent_answers
                if max_concurrent_answers is None
                else max_concurrent_answers
            ),
        ),
        answer_acquire_timeout_seconds=max(
            0.0,
            float(
                defaults.answer_acquire_timeout_seconds
                if answer_acquire_timeout_seconds is None
                else answer_acquire_timeout_seconds
            ),
        ),
        synthetic_model_latency_ms=max(
            0.0,
            float(
                defaults.synthetic_model_latency_ms
                if synthetic_model_latency_ms is None
                else synthetic_model_latency_ms
            ),
        ),
        synthetic_input_tokens_per_request=max(
            0,
            int(
                defaults.synthetic_input_tokens_per_request
                if synthetic_input_tokens_per_request is None
                else synthetic_input_tokens_per_request
            ),
        ),
        synthetic_output_tokens_per_request=max(
            0,
            int(
                defaults.synthetic_output_tokens_per_request
                if synthetic_output_tokens_per_request is None
                else synthetic_output_tokens_per_request
            ),
        ),
        input_cost_per_million_tokens=max(
            0.0,
            float(
                defaults.input_cost_per_million_tokens
                if input_cost_per_million_tokens is None
                else input_cost_per_million_tokens
            ),
        ),
        output_cost_per_million_tokens=max(
            0.0,
            float(
                defaults.output_cost_per_million_tokens
                if output_cost_per_million_tokens is None
                else output_cost_per_million_tokens
            ),
        ),
        retrieval_degraded_every=max(
            0,
            int(
                defaults.retrieval_degraded_every
                if retrieval_degraded_every is None
                else retrieval_degraded_every
            ),
        ),
        retrieval_degraded_source=str(
            retrieval_degraded_source or defaults.retrieval_degraded_source
        ),
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


def _retrieval_metrics_from_scenario(
    *,
    scenario: PressureScenario,
    completed_requests: int,
) -> RetrievalMetrics:
    if completed_requests <= 0 or scenario.retrieval_degraded_every <= 0:
        return RetrievalMetrics()
    degraded_count = completed_requests // scenario.retrieval_degraded_every
    degraded_rate = degraded_count / completed_requests
    source_counts = {scenario.retrieval_degraded_source: degraded_count} if degraded_count else {}
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
                    "answer_acquire_timeout_seconds": (scenario.answer_acquire_timeout_seconds),
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


def run_pressure_test(
    *,
    scenario_name: str | None = None,
    requests: int | None = None,
    workers: int | None = None,
    answer_delay_ms: float | None = None,
    trace_delay_ms: float | None = None,
    trace_queue_size: int | None = None,
    max_concurrent_answers: int | None = None,
    answer_acquire_timeout_seconds: float | None = None,
    synthetic_model_latency_ms: float | None = None,
    synthetic_input_tokens_per_request: int | None = None,
    synthetic_output_tokens_per_request: int | None = None,
    input_cost_per_million_tokens: float | None = None,
    output_cost_per_million_tokens: float | None = None,
    retrieval_degraded_every: int | None = None,
    retrieval_degraded_source: str | None = None,
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
                    "answer_acquire_timeout_seconds": (scenario.answer_acquire_timeout_seconds),
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


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    defaults = DEFAULT_PRESSURE_SCENARIO
    parser = argparse.ArgumentParser(
        description="Local pressure test for GraphRAGServingApiService concurrency and trace backpressure.",
    )
    parser.add_argument("--requests", type=int, default=defaults.requests)
    parser.add_argument("--workers", type=int, default=defaults.workers)
    parser.add_argument("--answer-delay-ms", type=float, default=defaults.answer_delay_ms)
    parser.add_argument("--trace-delay-ms", type=float, default=defaults.trace_delay_ms)
    parser.add_argument("--trace-queue-size", type=int, default=defaults.trace_queue_size)
    parser.add_argument("--scenario-name", default=defaults.name)
    parser.add_argument(
        "--max-concurrent-answers",
        type=int,
        default=defaults.max_concurrent_answers,
    )
    parser.add_argument(
        "--answer-acquire-timeout-seconds",
        type=float,
        default=defaults.answer_acquire_timeout_seconds,
    )
    parser.add_argument(
        "--synthetic-model-latency-ms",
        type=float,
        default=defaults.synthetic_model_latency_ms,
    )
    parser.add_argument(
        "--synthetic-input-tokens-per-request",
        type=int,
        default=defaults.synthetic_input_tokens_per_request,
    )
    parser.add_argument(
        "--synthetic-output-tokens-per-request",
        type=int,
        default=defaults.synthetic_output_tokens_per_request,
    )
    parser.add_argument(
        "--input-cost-per-million-tokens",
        type=float,
        default=defaults.input_cost_per_million_tokens,
    )
    parser.add_argument(
        "--output-cost-per-million-tokens",
        type=float,
        default=defaults.output_cost_per_million_tokens,
    )
    parser.add_argument(
        "--retrieval-degraded-every",
        type=int,
        default=defaults.retrieval_degraded_every,
    )
    parser.add_argument(
        "--retrieval-degraded-source",
        default=defaults.retrieval_degraded_source,
    )
    parser.add_argument("--json", action="store_true", help="Emit report as JSON.")
    return parser.parse_args(argv)


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


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
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
    else:
        _print_human_report(payload)
    return report.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
