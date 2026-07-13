from __future__ import annotations

import argparse
import os
import sys
import threading
import time
from collections.abc import Sequence

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
from scripts.pressure.metrics import (
    ModelMetrics,
    PressureMetrics,
    RetrievalMetrics,
    SseMetrics,
    TraceMetrics,
    _percentile,
)
from scripts.pressure.reporter import (
    PressureReport,
    build_pressure_report,
    print_human_report,
    print_json_report,
)
from scripts.pressure.scenario import (
    DEFAULT_PRESSURE_SCENARIO,
    PressureScenario,
    default_pressure_scenario,
)
from scripts.pressure.thresholds import default_pressure_thresholds


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
    if args.json:
        print_json_report(report)
    else:
        print_human_report(report)
    return report.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
