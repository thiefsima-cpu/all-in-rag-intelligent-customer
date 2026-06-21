"""OpenTelemetry tracing and Prometheus metrics for the RAG runtime."""

from __future__ import annotations

import atexit
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Iterator

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.sdk.trace.sampling import ParentBased, TraceIdRatioBased
from opentelemetry.trace import Span, Status, StatusCode
from prometheus_client import CollectorRegistry, Counter, Histogram, generate_latest


@dataclass(frozen=True, slots=True)
class TelemetryIdentity:
    service_name: str
    model_name: str
    opentelemetry_enabled: bool
    otlp_endpoint: str
    sample_ratio: float
    prometheus_enabled: bool
    input_cost_per_million_tokens: float
    output_cost_per_million_tokens: float


class RuntimeTelemetry:
    """Request-scoped spans plus process-safe Prometheus instruments."""

    def __init__(self, identity: TelemetryIdentity) -> None:
        self.identity = identity
        self.registry = CollectorRegistry(auto_describe=True)
        self.tracer_provider: TracerProvider | None = None
        self.tracer = trace.get_tracer(__name__)
        if identity.opentelemetry_enabled:
            self.tracer_provider = self._build_tracer_provider(identity)
            self.tracer = self.tracer_provider.get_tracer("graphrag.runtime")

        self.query_total = Counter(
            "graphrag_queries_total",
            "Completed RAG queries.",
            ("strategy", "status"),
            registry=self.registry,
        )
        self.query_latency = Histogram(
            "graphrag_query_latency_seconds",
            "End-to-end RAG query latency.",
            ("strategy",),
            buckets=(0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10, 20, 45, 90),
            registry=self.registry,
        )
        self.retrieved_documents = Histogram(
            "graphrag_retrieved_documents",
            "Evidence documents returned per query.",
            ("strategy",),
            buckets=(0, 1, 2, 3, 5, 8, 13, 21),
            registry=self.registry,
        )
        self.generation_latency = Histogram(
            "graphrag_generation_provider_latency_seconds",
            "Model-provider latency for answer generation.",
            ("model", "mode"),
            buckets=(0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10, 20, 45, 90),
            registry=self.registry,
        )
        self.generation_tokens = Counter(
            "graphrag_generation_tokens_total",
            "Generation tokens reported by the model provider.",
            ("model", "type"),
            registry=self.registry,
        )
        self.generation_cost = Counter(
            "graphrag_generation_cost_usd_total",
            "Estimated model cost in USD from configured token prices.",
            ("model",),
            registry=self.registry,
        )

    @staticmethod
    def _build_tracer_provider(identity: TelemetryIdentity) -> TracerProvider:
        provider = TracerProvider(
            resource=Resource.create({"service.name": identity.service_name}),
            sampler=ParentBased(TraceIdRatioBased(identity.sample_ratio)),
        )
        endpoint = _trace_endpoint(identity.otlp_endpoint)
        if endpoint:
            provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint)))
        return provider

    @contextmanager
    def span(
        self,
        name: str,
        *,
        attributes: dict[str, Any] | None = None,
    ) -> Iterator[Span]:
        with self.tracer.start_as_current_span(
            name,
            attributes=_span_attributes(attributes or {}),
        ) as span:
            try:
                yield span
            except Exception as exc:
                span.record_exception(exc)
                span.set_status(Status(StatusCode.ERROR, str(exc)))
                raise

    def record_answer(self, result) -> None:
        if not self.identity.prometheus_enabled:
            return
        strategy = str(getattr(result, "strategy", "") or "unknown")
        status = str(getattr(result, "status", "") or "unknown")
        latency_ms = max(0.0, float(getattr(result, "latency_ms", 0.0) or 0.0))
        doc_count = max(0, int(getattr(result, "doc_count", 0) or 0))
        generation = getattr(result, "generation_trace", None)

        self.query_total.labels(strategy=strategy, status=status).inc()
        self.query_latency.labels(strategy=strategy).observe(latency_ms / 1000.0)
        self.retrieved_documents.labels(strategy=strategy).observe(doc_count)
        if generation is None:
            return

        mode = str(getattr(generation, "mode", "") or "unknown")
        provider_latency_ms = max(
            0.0,
            float(getattr(generation, "provider_latency_ms", 0.0) or 0.0),
        )
        self.generation_latency.labels(
            model=self.identity.model_name,
            mode=mode,
        ).observe(provider_latency_ms / 1000.0)
        for token_type, value in (
            ("prompt", getattr(generation, "prompt_tokens", 0)),
            ("completion", getattr(generation, "completion_tokens", 0)),
        ):
            token_count = max(0, int(value or 0))
            if token_count:
                self.generation_tokens.labels(
                    model=self.identity.model_name,
                    type=token_type,
                ).inc(token_count)
        estimated_cost = max(
            0.0,
            float(getattr(generation, "estimated_cost_usd", 0.0) or 0.0),
        )
        if estimated_cost:
            self.generation_cost.labels(model=self.identity.model_name).inc(estimated_cost)

    @staticmethod
    def enrich_answer_span(span: Span, result) -> None:
        generation = getattr(result, "generation_trace", None)
        attributes = {
            "rag.strategy": getattr(result, "strategy", "") or "unknown",
            "rag.status": getattr(result, "status", "") or "unknown",
            "rag.document.count": int(getattr(result, "doc_count", 0) or 0),
            "rag.latency_ms": float(getattr(result, "latency_ms", 0.0) or 0.0),
            "gen_ai.operation.name": "chat",
            "gen_ai.usage.input_tokens": int(getattr(generation, "prompt_tokens", 0) or 0),
            "gen_ai.usage.output_tokens": int(getattr(generation, "completion_tokens", 0) or 0),
        }
        for key, value in _span_attributes(attributes).items():
            span.set_attribute(key, value)
        if getattr(result, "error", ""):
            span.set_status(Status(StatusCode.ERROR, str(result.error)))

    def prometheus_payload(self) -> bytes:
        return generate_latest(self.registry)

    def shutdown(self) -> None:
        if self.tracer_provider is not None:
            self.tracer_provider.shutdown()


_TELEMETRY_LOCK = threading.Lock()
_TELEMETRY: dict[TelemetryIdentity, RuntimeTelemetry] = {}


def get_runtime_telemetry(config) -> RuntimeTelemetry:
    observability = config.observability
    models = config.models
    identity = TelemetryIdentity(
        service_name=str(observability.otel_service_name or "graphrag"),
        model_name=str(models.llm_model or "unknown"),
        opentelemetry_enabled=bool(observability.enable_opentelemetry),
        otlp_endpoint=str(observability.otel_exporter_otlp_endpoint or ""),
        sample_ratio=float(observability.otel_trace_sample_ratio),
        prometheus_enabled=bool(observability.enable_prometheus),
        input_cost_per_million_tokens=float(models.llm_input_cost_per_million_tokens),
        output_cost_per_million_tokens=float(models.llm_output_cost_per_million_tokens),
    )
    telemetry = _TELEMETRY.get(identity)
    if telemetry is not None:
        return telemetry
    with _TELEMETRY_LOCK:
        telemetry = _TELEMETRY.get(identity)
        if telemetry is None:
            telemetry = RuntimeTelemetry(identity)
            _TELEMETRY[identity] = telemetry
    return telemetry


def shutdown_runtime_telemetry() -> None:
    with _TELEMETRY_LOCK:
        instances = list(_TELEMETRY.values())
        _TELEMETRY.clear()
    for telemetry in instances:
        telemetry.shutdown()


def _trace_endpoint(endpoint: str) -> str:
    value = str(endpoint or "").strip().rstrip("/")
    if not value:
        return ""
    if value.endswith("/v1/traces"):
        return value
    return f"{value}/v1/traces"


def _span_attributes(attributes: dict[str, Any]) -> dict[str, Any]:
    return {
        str(key): value
        for key, value in attributes.items()
        if isinstance(value, (bool, str, int, float))
    }


atexit.register(shutdown_runtime_telemetry)


__all__ = [
    "RuntimeTelemetry",
    "TelemetryIdentity",
    "get_runtime_telemetry",
    "shutdown_runtime_telemetry",
]
