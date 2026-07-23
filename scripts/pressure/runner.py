from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from functools import partial

from rag_modules.app.diagnostics import ArtifactManifestDiagnostics, StartupDiagnostics
from rag_modules.application.answering.answer_models import (
    QuestionAnswerResponse,
    QuestionAnswerSummary,
)
from rag_modules.configuration.env import EnvConfigSource
from rag_modules.configuration.loader import load_config
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
    SseExecutorMetrics,
    SseMetrics,
    TraceMetrics,
    _percentile,
)
from scripts.pressure.reporter import PressureReport, build_pressure_report
from scripts.pressure.scenario import PressureScenario, default_pressure_scenario
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
        del explain_routing, message_callback
        if control is not None:
            control.raise_if_cancelled()
        if stream and chunk_callback is not None:
            chunk_callback("synthetic-first-token")
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
            documents=[EvidenceDocument(content="pressure-doc", entity_name="pressure")],
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


@dataclass
class _AnswerRunState:
    scenario: PressureScenario
    next_request: int = 0
    completed_requests: int = 0
    rejected_requests: int = 0
    latencies: list[float] = field(default_factory=list)
    request_lock: threading.Lock = field(default_factory=threading.Lock)
    counts_lock: threading.Lock = field(default_factory=threading.Lock)
    latencies_lock: threading.Lock = field(default_factory=threading.Lock)

    def claim_request(self) -> int | None:
        with self.request_lock:
            if self.next_request >= self.scenario.requests:
                return None
            request_id = self.next_request
            self.next_request += 1
            return request_id


@dataclass
class _SseRunState:
    scenario: PressureScenario
    next_request: int = 0
    done_events: int = 0
    result_events: int = 0
    error_events: int = 0
    rate_limited_error_events: int = 0
    unfinished_streams: int = 0
    first_token_latencies_ms: list[float] = field(default_factory=list)
    request_lock: threading.Lock = field(default_factory=threading.Lock)
    counts_lock: threading.Lock = field(default_factory=threading.Lock)

    def claim_request(self) -> int | None:
        with self.request_lock:
            if self.next_request >= self.scenario.requests:
                return None
            request_id = self.next_request
            self.next_request += 1
            return request_id


def _build_tracer(*, queue_size: int, trace_delay_ms: float) -> QueryTracer:
    delegate = _SlowCaptureTraceSink(write_delay_ms=trace_delay_ms)
    sink = AsyncQueryTraceSink(delegate, max_queue_size=queue_size)
    config = load_config(
        source=EnvConfigSource(environ={}),
        overrides={
            "observability": {
                "enable_query_tracing": True,
                "query_trace_path": "pressure-trace.jsonl",
                "query_trace_async_enabled": True,
                "query_trace_max_queue_size": queue_size,
            }
        },
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


def _build_service(
    scenario: PressureScenario,
    tracer: QueryTracer,
    *,
    enable_sse: bool,
) -> GraphRAGServingApiService:
    api_config = {
        "max_concurrent_answers": scenario.max_concurrent_answers,
        "answer_acquire_timeout_seconds": scenario.answer_acquire_timeout_seconds,
    }
    if enable_sse:
        api_config.update(
            {
                "stream_executor_max_workers": scenario.stream_executor_max_workers,
                "stream_executor_max_outstanding": scenario.stream_executor_max_outstanding,
                "stream_event_queue_max_size": scenario.stream_event_queue_max_size,
            }
        )
    system = _PressureTestSystem(
        answer_delay_ms=scenario.answer_delay_ms,
        query_tracer=tracer,
    )
    return GraphRAGServingApiService(
        system=system,
        config=load_config(
            source=EnvConfigSource(environ={}),
            overrides={"api": api_config},
        ),
    )


def _run_answer_worker(
    service: GraphRAGServingApiService,
    state: _AnswerRunState,
    worker_id: int,
) -> None:
    while True:
        request_id = state.claim_request()
        if request_id is None:
            return
        question = f"pressure-{worker_id}-{request_id}"
        start = time.perf_counter()
        try:
            service.answer_question(question=question)
        except ApiBackpressureError:
            with state.counts_lock:
                state.rejected_requests += 1
        else:
            latency_ms = (time.perf_counter() - start) * 1000
            with state.counts_lock:
                state.completed_requests += 1
            with state.latencies_lock:
                state.latencies.append(latency_ms)


def _run_sse_worker(
    service: GraphRAGServingApiService,
    state: _SseRunState,
    worker_id: int,
) -> None:
    while True:
        request_id = state.claim_request()
        if request_id is None:
            return
        started = time.perf_counter()
        events = []
        first_token_latency_ms = None
        for event in service.stream_answer_question_events(
            question=f"sse-pressure-{worker_id}-{request_id}",
            request_id=f"sse-pressure-{request_id}",
            include_traces=False,
        ):
            events.append(event)
            if first_token_latency_ms is None and str(event.event.value) == "chunk":
                first_token_latency_ms = (time.perf_counter() - started) * 1000
        event_names = [str(event.event.value) for event in events]
        stream_done = "done" in event_names
        stream_result_events = event_names.count("result")
        stream_error_events = event_names.count("error")
        stream_rate_limited = any(
            getattr(getattr(event.data, "error", None), "code", None) == "RATE_LIMITED"
            or str(getattr(getattr(event.data, "error", None), "code", "")) == "RATE_LIMITED"
            for event in events
        )
        with state.counts_lock:
            state.done_events += 1 if stream_done else 0
            state.result_events += stream_result_events
            state.error_events += stream_error_events
            state.rate_limited_error_events += 1 if stream_rate_limited else 0
            state.unfinished_streams += 0 if stream_done else 1
            if first_token_latency_ms is not None:
                state.first_token_latencies_ms.append(first_token_latency_ms)


def _run_threads(*, name: str, workers: int, target: Callable[[int], None]) -> None:
    threads = [
        threading.Thread(
            target=target,
            args=(worker_id,),
            name=f"{name}-{worker_id}",
        )
        for worker_id in range(workers)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()


def _answer_metrics(
    *,
    scenario: PressureScenario,
    state: _AnswerRunState,
    total_duration_ms: float,
    trace: TraceMetrics,
) -> PressureMetrics:
    return PressureMetrics(
        requests=scenario.requests,
        workers=scenario.workers,
        completed_requests=state.completed_requests,
        rejected_requests=state.rejected_requests,
        total_duration_ms=total_duration_ms,
        throughput_rps=(state.completed_requests / (total_duration_ms / 1000.0))
        if total_duration_ms
        else 0.0,
        avg_latency_ms=(sum(state.latencies) / len(state.latencies)) if state.latencies else 0.0,
        p95_latency_ms=_percentile(state.latencies, 0.95),
        trace=trace,
        sse=SseMetrics(),
        model=_model_metrics_from_scenario(
            scenario=scenario,
            completed_requests=state.completed_requests,
        ),
        retrieval=_retrieval_metrics_from_scenario(
            scenario=scenario,
            completed_requests=state.completed_requests,
        ),
    )


def _sse_metrics(
    *,
    scenario: PressureScenario,
    state: _SseRunState,
    trace: TraceMetrics,
    executor: SseExecutorMetrics,
) -> PressureMetrics:
    sse = SseMetrics(
        attempted_streams=scenario.requests,
        done_events=state.done_events,
        result_events=state.result_events,
        error_events=state.error_events,
        rate_limited_error_events=state.rate_limited_error_events,
        unfinished_streams=state.unfinished_streams,
        cancelled_after_done=0,
        p95_first_token_latency_ms=_percentile(state.first_token_latencies_ms, 0.95),
        executor=executor,
    )
    return _empty_pressure_metrics(scenario=scenario, trace=trace, sse=sse)


def _run_answer_pressure_scenario(scenario: PressureScenario) -> PressureReport:
    tracer = _build_tracer(
        queue_size=scenario.trace_queue_size,
        trace_delay_ms=scenario.trace_delay_ms,
    )
    service = _build_service(scenario, tracer, enable_sse=False)
    state = _AnswerRunState(scenario=scenario)
    started = time.perf_counter()
    _run_threads(
        name="pressure-worker",
        workers=scenario.workers,
        target=partial(_run_answer_worker, service, state),
    )
    total_duration_ms = (time.perf_counter() - started) * 1000
    service.shutdown()
    return build_pressure_report(
        scenario=scenario,
        metrics=_answer_metrics(
            scenario=scenario,
            state=state,
            total_duration_ms=total_duration_ms,
            trace=TraceMetrics.from_stats(tracer.stats()),
        ),
        thresholds=default_pressure_thresholds(scenario),
    )


def _run_sse_pressure_scenario(scenario: PressureScenario) -> PressureReport:
    tracer = _build_tracer(
        queue_size=scenario.trace_queue_size,
        trace_delay_ms=scenario.trace_delay_ms,
    )
    service = _build_service(scenario, tracer, enable_sse=True)
    state = _SseRunState(scenario=scenario)
    _run_threads(
        name="pressure-sse-worker",
        workers=scenario.workers,
        target=partial(_run_sse_worker, service, state),
    )
    executor = SseExecutorMetrics.from_snapshot(service.stream_executor_snapshot())
    service.shutdown()
    return build_pressure_report(
        scenario=scenario,
        metrics=_sse_metrics(
            scenario=scenario,
            state=state,
            trace=TraceMetrics.from_stats(tracer.stats()),
            executor=executor,
        ),
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
    stream_executor_max_workers: int | None = None,
    stream_executor_max_outstanding: int | None = None,
    stream_event_queue_max_size: int | None = None,
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
        stream_executor_max_workers=stream_executor_max_workers,
        stream_executor_max_outstanding=stream_executor_max_outstanding,
        stream_event_queue_max_size=stream_event_queue_max_size,
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
    return _run_answer_pressure_scenario(scenario)
