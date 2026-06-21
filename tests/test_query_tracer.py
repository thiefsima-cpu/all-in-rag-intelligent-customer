from __future__ import annotations

import json
import tempfile
import threading
import time
import unittest
from pathlib import Path

from rag_modules.configuration.testing import build_test_config
from rag_modules.retrieval.contracts import EvidenceDocument
from rag_modules.runtime import (
    GenerationSnapshot,
    GraphRetrievalSnapshot,
    QueryTraceEvent,
    RouteSnapshot,
    RouteStageSnapshot,
)
from rag_modules.tracing import QueryTracer
from rag_modules.tracing_sinks import AsyncQueryTraceSink, JsonlQueryTraceSink


class _CapturingSink:
    def __init__(self) -> None:
        self.events: list[QueryTraceEvent] = []
        self.closed = False

    def write(self, event: QueryTraceEvent) -> None:
        self.events.append(event)

    def close(self) -> None:
        self.closed = True


class _BlockingSink:
    def __init__(self) -> None:
        self.events: list[QueryTraceEvent] = []
        self.started = threading.Event()
        self.release = threading.Event()
        self.closed = False

    def write(self, event: QueryTraceEvent) -> None:
        self.events.append(event)
        if len(self.events) == 1:
            self.started.set()
            self.release.wait(timeout=2.0)

    def close(self) -> None:
        self.closed = True


class QueryTracerTests(unittest.TestCase):
    def _build_config(self, *, enabled: bool = True, trace_path: str = "unused.jsonl"):
        return build_test_config(
            {
                "observability": {
                    "enable_query_tracing": enabled,
                    "query_trace_path": trace_path,
                }
            }
        )

    def test_query_tracer_uses_injected_sink(self) -> None:
        sink = _CapturingSink()
        tracer = QueryTracer(self._build_config(), sink=sink)

        event = tracer.record(
            query="麻婆豆腐为什么更适合走图检索？",
            analysis=None,
            documents=[EvidenceDocument(content="图证据", recipe_name="麻婆豆腐", score=0.93)],
            latency_ms=18.6,
            answer="因为关系链更密集。",
        )

        self.assertEqual(len(sink.events), 1)
        self.assertNotIn("麻婆豆腐", sink.events[0].query)
        self.assertEqual(sink.events[0].query, event.query)
        self.assertTrue(event.answer.preview.startswith("sha256:"))
        self.assertEqual(event.models.llm, "qwen3.7-plus")
        self.assertEqual(event.models.embedding, "qwen3-vl-embedding")
        self.assertEqual(event.models.rerank, "qwen3-vl-rerank")
        self.assertEqual(event.retrieval.doc_count, 1)
        self.assertFalse(hasattr(tracer, "last_event"))

    def test_query_tracer_recursively_redacts_content_and_credentials(self) -> None:
        sink = _CapturingSink()
        tracer = QueryTracer(
            self._build_config(),
            sink=sink,
        )
        secret = "sk-secret-value"
        question = "我的手机号是 13800138000，怎么做宫保鸡丁？"

        event = tracer.record(
            query=question,
            analysis=None,
            documents=[EvidenceDocument(content="private evidence")],
            latency_ms=3.0,
            answer="private answer",
            error=f"Authorization: Bearer {secret}",
            route_trace=RouteSnapshot(
                query=question,
                stages={
                    "plan": RouteStageSnapshot(
                        details={
                            "prompt": question,
                            "api_key": secret,
                            "exclude_terms": [question],
                            "category_terms": [question],
                            "cuisine_terms": [question],
                            "nested": {"password": "database-password"},
                        }
                    )
                },
                error=f"request failed with token={secret}",
            ),
            graph_trace=GraphRetrievalSnapshot(
                query=question,
                retrieval_plan={"question": question, "authorization": secret},
                error=f"provider rejected {secret}",
            ),
        )

        serialized = json.dumps(event.to_dict(), ensure_ascii=False)
        self.assertNotIn(question, serialized)
        self.assertNotIn(secret, serialized)
        self.assertNotIn("database-password", serialized)
        self.assertNotIn("private answer", serialized)
        self.assertNotIn("private evidence", serialized)
        self.assertIn("sha256:", serialized)

    def test_query_tracer_honors_disabled_flag(self) -> None:
        sink = _CapturingSink()
        tracer = QueryTracer(self._build_config(enabled=False), sink=sink)

        tracer.record(
            query="不落盘的追踪",
            analysis=None,
            documents=[],
            latency_ms=5.0,
        )

        self.assertEqual(sink.events, [])

    def test_query_tracer_exposes_sink_stats(self) -> None:
        sink = _CapturingSink()
        tracer = QueryTracer(self._build_config(), sink=sink)

        stats = tracer.stats()

        self.assertTrue(stats["enabled"])
        self.assertEqual(stats["path"], "unused.jsonl")

    def test_jsonl_sink_writes_utf8_trace_line(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            trace_path = Path(tmp_dir) / "trace.jsonl"
            sink = JsonlQueryTraceSink(str(trace_path))
            event = QueryTraceEvent(query_id="q1", timestamp=1, query="宫保鸡丁")

            sink.write(event)

            lines = trace_path.read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(lines), 1)
            payload = json.loads(lines[0])
            self.assertNotEqual(payload["query"], "宫保鸡丁")
            self.assertTrue(payload["query"].startswith("sha256:"))

    def test_async_sink_flushes_delegate_on_close(self) -> None:
        delegate = _CapturingSink()
        sink = AsyncQueryTraceSink(delegate)

        sink.write(QueryTraceEvent(query_id="a", timestamp=1, query="问题 A"))
        sink.write(QueryTraceEvent(query_id="b", timestamp=2, query="问题 B"))
        sink.close()

        self.assertTrue(delegate.closed)
        self.assertEqual([event.query for event in delegate.events], ["问题 A", "问题 B"])

    def test_async_sink_drops_when_queue_is_full_without_blocking_writer(self) -> None:
        delegate = _BlockingSink()
        sink = AsyncQueryTraceSink(delegate, max_queue_size=1)

        sink.write(QueryTraceEvent(query_id="a", timestamp=1, query="first"))
        self.assertTrue(delegate.started.wait(timeout=0.5))

        sink.write(QueryTraceEvent(query_id="b", timestamp=2, query="second"))
        start = time.perf_counter()
        sink.write(QueryTraceEvent(query_id="c", timestamp=3, query="third"))
        elapsed = time.perf_counter() - start

        self.assertLess(
            elapsed,
            0.1,
            "trace writes should not block the caller when the async queue is full",
        )

        delegate.release.set()
        sink.close()

        self.assertTrue(delegate.closed)
        self.assertEqual([event.query for event in delegate.events], ["first", "second"])

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
        self.assertTrue(stats["closed"])
        self.assertGreaterEqual(stats["written_events"], 1)
        self.assertGreaterEqual(stats["dropped_events"], 1)
        self.assertEqual(stats["failed_events"], 0)

    def test_generation_snapshot_is_recorded_tracks_non_default_values(self) -> None:
        self.assertFalse(GenerationSnapshot().is_recorded())
        self.assertTrue(GenerationSnapshot(mode="direct").is_recorded())
        self.assertTrue(GenerationSnapshot(request_retries=1).is_recorded())

    def test_generation_fallback_is_classified_as_degraded(self) -> None:
        tracer = QueryTracer(self._build_config(), sink=_CapturingSink())

        event = tracer.record(
            query="fallback query",
            analysis=None,
            documents=[EvidenceDocument(content="evidence")],
            latency_ms=20.0,
            generation_trace=GenerationSnapshot(
                status="degraded",
                mode="direct",
                fallback_used=True,
                fallback_reason="generation_provider_empty_choices",
                failure_code="generation_provider_empty_choices",
            ),
        )

        self.assertEqual(event.diagnostics.generation_bucket, "generation_fallback")
        self.assertEqual(event.diagnostics.overall_bucket, "degraded_response")
        self.assertIn(
            "generation_provider_empty_choices",
            event.diagnostics.failure_reasons,
        )

    def test_retrieval_source_degradation_is_exposed_in_query_diagnostics(self) -> None:
        tracer = QueryTracer(self._build_config(), sink=_CapturingSink())
        route_trace = RouteSnapshot(
            query="degraded retrieval query",
            strategy="hybrid_traditional",
            stages={
                "hybrid": RouteStageSnapshot(
                    doc_count=1,
                    details={
                        "retrieval_degraded": True,
                        "degraded_sources": ["vector"],
                        "circuit_breaker_triggered": True,
                        "answer_impacted": False,
                        "degraded_candidates": [
                            {
                                "source": "vector",
                                "rank_name": "vector",
                                "reason": "circuit_open",
                                "error_type": "CircuitOpenError",
                                "message": "Circuit breaker open",
                                "circuit_state": "open",
                                "failure_count": 2,
                            }
                        ],
                    },
                )
            },
            final_doc_count=1,
        )

        event = tracer.record(
            query="degraded retrieval query",
            analysis=None,
            documents=[EvidenceDocument(content="evidence")],
            latency_ms=20.0,
            route_trace=route_trace,
            generation_trace=GenerationSnapshot(status="success", mode="direct"),
        )

        self.assertEqual(event.diagnostics.retrieval_bucket, "retrieval_degraded")
        self.assertTrue(event.diagnostics.retrieval_degraded)
        self.assertEqual(event.diagnostics.degraded_sources, ["vector"])
        self.assertTrue(event.diagnostics.circuit_breaker_triggered)
        self.assertFalse(event.diagnostics.answer_impacted)
        self.assertEqual(event.diagnostics.degraded_candidates[0]["reason"], "circuit_open")
        self.assertIn("retrieval_degraded", event.diagnostics.failure_reasons)


if __name__ == "__main__":
    unittest.main()
