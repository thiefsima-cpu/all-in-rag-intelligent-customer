from __future__ import annotations

from dataclasses import dataclass, field


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


def _percentile(values: list[float], ratio: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int((len(ordered) - 1) * ratio)))
    return ordered[index]
