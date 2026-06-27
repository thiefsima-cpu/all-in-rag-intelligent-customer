from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import time
from dataclasses import dataclass

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from rag_modules.app.diagnostics import ArtifactManifestDiagnostics, StartupDiagnostics
from rag_modules.configuration.testing import build_test_config
from rag_modules.interfaces.api.services import GraphRAGServingApiService
from rag_modules.interfaces.api.services.errors import ApiBackpressureError
from rag_modules.observability.tracing import QueryTracer
from rag_modules.observability.tracing_sinks import AsyncQueryTraceSink
from rag_modules.retrieval.contracts import EvidenceDocument
from rag_modules.runtime.artifacts import ARTIFACT_HEALTH_READY


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


class _DummyAnswerResponse:
    def __init__(self, *, question: str, latency_ms: float) -> None:
        self.question = question
        self.latency_ms = latency_ms

    def to_dict(self) -> dict:
        return {
            "summary": {
                "answer": f"answer:{self.question}",
                "strategy": "hybrid_traditional",
                "latency_ms": self.latency_ms,
                "doc_count": 1,
                "has_evidence": True,
                "error": "",
            }
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
    ):
        del stream, explain_routing, message_callback, chunk_callback
        with self._lock:
            self.answer_calls += 1
        start = time.perf_counter()
        if self.answer_delay_seconds > 0:
            time.sleep(self.answer_delay_seconds)
        latency_ms = (time.perf_counter() - start) * 1000
        self.query_tracer.record(
            query=question,
            analysis=None,
            documents=[EvidenceDocument(content="pressure-doc", recipe_name="pressure")],
            latency_ms=latency_ms,
            answer="ok",
        )
        return _DummyAnswerResponse(question=question, latency_ms=latency_ms)

    def close(self) -> None:
        self.query_tracer.close()


@dataclass
class PressureResult:
    requests: int
    workers: int
    completed_requests: int
    rejected_requests: int
    total_duration_ms: float
    throughput_rps: float
    avg_latency_ms: float
    p95_latency_ms: float
    trace_stats: dict

    def to_dict(self) -> dict:
        return {
            "requests": self.requests,
            "workers": self.workers,
            "completed_requests": self.completed_requests,
            "rejected_requests": self.rejected_requests,
            "total_duration_ms": round(self.total_duration_ms, 2),
            "throughput_rps": round(self.throughput_rps, 2),
            "avg_latency_ms": round(self.avg_latency_ms, 2),
            "p95_latency_ms": round(self.p95_latency_ms, 2),
            "trace_stats": dict(self.trace_stats),
        }


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
    tracer = _build_tracer(queue_size=trace_queue_size, trace_delay_ms=trace_delay_ms)
    system = _PressureTestSystem(
        answer_delay_ms=answer_delay_ms,
        query_tracer=tracer,
    )
    service = GraphRAGServingApiService(
        system=system,
        config=build_test_config(
            {
                "api": {
                    "max_concurrent_answers": max(0, int(max_concurrent_answers)),
                    "answer_acquire_timeout_seconds": max(
                        0.0,
                        float(answer_acquire_timeout_seconds),
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
                if next_request >= requests:
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
        threading.Thread(target=worker_loop, args=(worker_id,), name=f"pressure-worker-{worker_id}")
        for worker_id in range(max(1, workers))
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    total_duration_ms = (time.perf_counter() - started) * 1000
    service.shutdown()
    trace_stats = tracer.stats()
    return PressureResult(
        requests=requests,
        workers=workers,
        completed_requests=completed_requests,
        rejected_requests=rejected_requests,
        total_duration_ms=total_duration_ms,
        throughput_rps=(completed_requests / (total_duration_ms / 1000.0))
        if total_duration_ms
        else 0.0,
        avg_latency_ms=(sum(latencies) / len(latencies)) if latencies else 0.0,
        p95_latency_ms=_percentile(latencies, 0.95),
        trace_stats=trace_stats,
    )


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Local pressure test for GraphRAGServingApiService concurrency and trace backpressure.",
    )
    parser.add_argument("--requests", type=int, default=200)
    parser.add_argument("--workers", type=int, default=16)
    parser.add_argument("--answer-delay-ms", type=float, default=20.0)
    parser.add_argument("--trace-delay-ms", type=float, default=5.0)
    parser.add_argument("--trace-queue-size", type=int, default=32)
    parser.add_argument("--max-concurrent-answers", type=int, default=0)
    parser.add_argument("--answer-acquire-timeout-seconds", type=float, default=0.25)
    parser.add_argument("--json", action="store_true", help="Emit summary as JSON.")
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    result = run_pressure_test(
        requests=max(1, args.requests),
        workers=max(1, args.workers),
        answer_delay_ms=max(0.0, args.answer_delay_ms),
        trace_delay_ms=max(0.0, args.trace_delay_ms),
        trace_queue_size=max(0, args.trace_queue_size),
        max_concurrent_answers=max(0, args.max_concurrent_answers),
        answer_acquire_timeout_seconds=max(0.0, args.answer_acquire_timeout_seconds),
    )
    payload = result.to_dict()
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    print("Pressure test summary")
    print("---------------------")
    print(f"Requests: {payload['requests']}")
    print(f"Workers: {payload['workers']}")
    print(f"Completed requests: {payload['completed_requests']}")
    print(f"Rejected requests: {payload['rejected_requests']}")
    print(f"Total duration (ms): {payload['total_duration_ms']}")
    print(f"Throughput (req/s): {payload['throughput_rps']}")
    print(f"Average latency (ms): {payload['avg_latency_ms']}")
    print(f"P95 latency (ms): {payload['p95_latency_ms']}")
    print(
        "Trace stats: "
        f"dropped={payload['trace_stats'].get('dropped_events', 0)}, "
        f"queued={payload['trace_stats'].get('queued_events', 0)}, "
        f"written={payload['trace_stats'].get('written_events', 0)}, "
        f"failed={payload['trace_stats'].get('failed_events', 0)}, "
        f"closed={payload['trace_stats'].get('closed', False)}, "
        f"max_queue_size={payload['trace_stats'].get('max_queue_size', 0)}, "
        f"async_enabled={payload['trace_stats'].get('async_enabled', False)}"
    )


if __name__ == "__main__":
    main()
