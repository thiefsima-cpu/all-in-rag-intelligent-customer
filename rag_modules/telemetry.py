"""OpenTelemetry tracing and Prometheus metrics for the RAG runtime."""

from __future__ import annotations

import atexit
import threading
from collections.abc import Mapping
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
from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram, generate_latest


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

        self._configure_query_metrics()
        self._configure_serving_metrics()
        self._configure_runtime_metrics()
        self._state_lock = threading.Lock()
        self._readiness_states: dict[str, str] = {}

    def _configure_query_metrics(self) -> None:
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
        self.first_token_latency = Histogram(
            "graphrag_generation_first_token_latency_seconds",
            "Time from generation start until the first streamed model token.",
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

    def _configure_serving_metrics(self) -> None:
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
        self.sse_queue_wait = Histogram(
            "graphrag_sse_queue_wait_seconds",
            "Time accepted SSE work spent waiting for an executor worker.",
            buckets=(0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2, 5),
            registry=self.registry,
        )
        self.admission_wait = Histogram(
            "graphrag_admission_wait_seconds",
            "Time answer requests spent waiting for admission.",
            ("outcome",),
            buckets=(0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2, 5),
            registry=self.registry,
        )
        self.admission_rejected = Counter(
            "graphrag_admission_rejected_total",
            "Answer requests rejected by admission control.",
            registry=self.registry,
        )

    def _configure_runtime_metrics(self) -> None:
        self.retrieval_degradation = Counter(
            "graphrag_retrieval_degradation_total",
            "Retrieval candidate-source degradations by low-cardinality reason.",
            ("source", "reason"),
            registry=self.registry,
        )
        self.circuit_breaker_state = Gauge(
            "graphrag_circuit_breaker_state",
            "Current observed candidate-source circuit-breaker state as a one-hot gauge.",
            ("source", "state"),
            registry=self.registry,
        )
        self.cache_access = Counter(
            "graphrag_cache_access_total",
            "Cache lookups by cache and hit result.",
            ("cache", "result"),
            registry=self.registry,
        )
        self.hot_refresh = Counter(
            "graphrag_hot_refresh_total",
            "Serving hot-refresh checks and outcomes.",
            ("outcome",),
            registry=self.registry,
        )
        self.readiness_state = Gauge(
            "graphrag_readiness_state",
            "Current runtime readiness state (1 ready, 0 not ready).",
            ("component",),
            registry=self.registry,
        )
        self.readiness_transitions = Counter(
            "graphrag_readiness_transitions_total",
            "Observed runtime readiness transitions.",
            ("component", "from_state", "to_state"),
            registry=self.registry,
        )
        self.build_leases_active = Gauge(
            "graphrag_build_leases_active",
            "Build-job leases currently held by this process.",
            ("backend",),
            registry=self.registry,
        )
        self.build_lease_events = Counter(
            "graphrag_build_lease_events_total",
            "Build-job lease lifecycle events.",
            ("backend", "event"),
            registry=self.registry,
        )
        self.build_job_repository_operation = Histogram(
            "graphrag_build_job_repository_operation_seconds",
            "Build-job repository operation duration.",
            ("backend", "operation", "outcome"),
            buckets=(0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2, 5),
            registry=self.registry,
        )
        self.build_job_claim = Counter(
            "graphrag_build_job_claim_total",
            "Build-job claim attempts by outcome.",
            ("backend", "outcome"),
            registry=self.registry,
        )
        self.build_job_repository_errors = Counter(
            "graphrag_build_job_repository_errors_total",
            "Build-job repository failures by safe category.",
            ("backend", "category"),
            registry=self.registry,
        )
        self.build_job_retention = Counter(
            "graphrag_build_job_retention_total",
            "Build-job retention records archived or purged.",
            ("backend", "action"),
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
                span.set_attribute("error.type", type(exc).__name__)
                span.set_status(Status(StatusCode.ERROR, "INTERNAL_ERROR"))
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
        first_token_latency_ms = max(
            0.0,
            float(getattr(generation, "first_token_latency_ms", 0.0) or 0.0),
        )
        if first_token_latency_ms:
            self.first_token_latency.labels(
                model=self.identity.model_name,
                mode=mode,
            ).observe(first_token_latency_ms / 1000.0)
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
        self._record_answer_runtime_signals(result)

    def _record_answer_runtime_signals(self, result: object) -> None:
        route_trace = getattr(result, "route_trace", None)
        diagnostics = getattr(route_trace, "diagnostics", None)
        planner_used_cache = getattr(diagnostics, "planner_used_cache", None)
        if planner_used_cache is not None:
            self.record_cache_access(cache="query_plan", hit=bool(planner_used_cache))

        degraded_candidates = getattr(diagnostics, "degraded_candidates", ()) or ()
        observed_sources: set[str] = set()
        for candidate in degraded_candidates:
            if not isinstance(candidate, Mapping):
                continue
            source = _metric_label(candidate.get("source"), default="unknown")
            observed_sources.add(source)
            error = candidate.get("error")
            error_payload = error if isinstance(error, Mapping) else {}
            reason = _degradation_reason(error_payload)
            self.retrieval_degradation.labels(source=source, reason=reason).inc()
            if reason == "circuit_open":
                self.record_circuit_breaker_state(source=source, state="open")

        for source_value in getattr(diagnostics, "degraded_sources", ()) or ():
            source = _metric_label(source_value, default="unknown")
            if source not in observed_sources:
                self.retrieval_degradation.labels(source=source, reason="unknown").inc()

    def record_admission(self, *, wait_seconds: float, accepted: bool) -> None:
        if not self.identity.prometheus_enabled:
            return
        outcome = "accepted" if accepted else "rejected"
        self.admission_wait.labels(outcome=outcome).observe(max(0.0, float(wait_seconds)))
        if not accepted:
            self.admission_rejected.inc()

    def record_sse_executor_state(
        self,
        *,
        active_delta: int = 0,
        queued_delta: int = 0,
        rejected_delta: int = 0,
        queue_wait_seconds: float | None = None,
    ) -> None:
        if not self.identity.prometheus_enabled:
            return
        if active_delta:
            self.sse_executor_active.inc(active_delta)
        if queued_delta:
            self.sse_executor_queued.inc(queued_delta)
        if rejected_delta:
            self.sse_executor_rejected.inc(rejected_delta)
        if queue_wait_seconds is not None:
            self.sse_queue_wait.observe(max(0.0, float(queue_wait_seconds)))

    def record_circuit_breaker_state(self, *, source: str, state: str) -> None:
        if not self.identity.prometheus_enabled:
            return
        normalized_source = _metric_label(source, default="unknown")
        normalized_state = state if state in {"closed", "half_open", "open"} else "unknown"
        for candidate_state in ("closed", "half_open", "open", "unknown"):
            self.circuit_breaker_state.labels(
                source=normalized_source,
                state=candidate_state,
            ).set(1 if candidate_state == normalized_state else 0)

    def record_cache_access(self, *, cache: str, hit: bool) -> None:
        if not self.identity.prometheus_enabled:
            return
        self.cache_access.labels(
            cache=_metric_label(cache, default="unknown"),
            result="hit" if hit else "miss",
        ).inc()

    def record_hot_refresh(self, outcome: str) -> None:
        if not self.identity.prometheus_enabled:
            return
        self.hot_refresh.labels(outcome=_metric_label(outcome, default="unknown")).inc()

    def record_readiness_state(self, *, component: str, ready: bool) -> None:
        if not self.identity.prometheus_enabled:
            return
        normalized_component = _metric_label(component, default="runtime")
        current = "ready" if ready else "not_ready"
        self.readiness_state.labels(component=normalized_component).set(1 if ready else 0)
        with self._state_lock:
            previous = self._readiness_states.get(normalized_component)
            self._readiness_states[normalized_component] = current
        if previous is not None and previous != current:
            self.readiness_transitions.labels(
                component=normalized_component,
                from_state=previous,
                to_state=current,
            ).inc()

    def record_build_lease_event(
        self,
        *,
        backend: str,
        event: str,
        active_delta: int = 0,
    ) -> None:
        if not self.identity.prometheus_enabled:
            return
        normalized_backend = _metric_label(backend, default="unknown")
        normalized_event = _metric_label(event, default="unknown")
        self.build_lease_events.labels(
            backend=normalized_backend,
            event=normalized_event,
        ).inc()
        if active_delta:
            self.build_leases_active.labels(backend=normalized_backend).inc(active_delta)

    def record_build_job_repository_operation(
        self,
        *,
        backend: str,
        operation: str,
        outcome: str,
        duration_seconds: float,
    ) -> None:
        if not self.identity.prometheus_enabled:
            return
        self.build_job_repository_operation.labels(
            backend=_build_job_metric_label(backend, _BUILD_JOB_BACKENDS),
            operation=_build_job_metric_label(operation, _BUILD_JOB_OPERATIONS),
            outcome=_build_job_metric_label(outcome, _BUILD_JOB_OPERATION_OUTCOMES),
        ).observe(max(0.0, float(duration_seconds)))

    def record_build_job_claim(self, *, backend: str, outcome: str) -> None:
        if not self.identity.prometheus_enabled:
            return
        self.build_job_claim.labels(
            backend=_build_job_metric_label(backend, _BUILD_JOB_BACKENDS),
            outcome=_build_job_metric_label(outcome, _BUILD_JOB_CLAIM_OUTCOMES),
        ).inc()

    def record_build_job_repository_error(self, *, backend: str, category: str) -> None:
        if not self.identity.prometheus_enabled:
            return
        self.build_job_repository_errors.labels(
            backend=_build_job_metric_label(backend, _BUILD_JOB_BACKENDS),
            category=_build_job_metric_label(category, _BUILD_JOB_ERROR_CATEGORIES),
        ).inc()

    def record_build_job_retention(self, *, backend: str, action: str, count: int) -> None:
        if not self.identity.prometheus_enabled:
            return
        increment = max(0, int(count))
        if not increment:
            return
        self.build_job_retention.labels(
            backend=_build_job_metric_label(backend, _BUILD_JOB_BACKENDS),
            action=_build_job_metric_label(action, _BUILD_JOB_RETENTION_ACTIONS),
        ).inc(increment)

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
        error = getattr(result, "error", None)
        if error:
            error_code = str(getattr(error, "code", "") or "INTERNAL_ERROR")
            span.set_status(Status(StatusCode.ERROR, error_code))

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


def _metric_label(value: object, *, default: str) -> str:
    text = str(value or "").strip().lower().replace("-", "_")
    if not text or len(text) > 64:
        return default
    if not all(character.isalnum() or character in {"_", "."} for character in text):
        return default
    return text


_BUILD_JOB_BACKENDS = frozenset({"file", "postgresql"})
_BUILD_JOB_OPERATIONS = frozenset(
    {
        "initialize",
        "submit",
        "get",
        "list",
        "list_events",
        "claim",
        "renew_lease",
        "apply",
        "find_dispatchable",
        "recover_expired_leases",
        "apply_retention",
        "diagnostics",
        "close",
    }
)
_BUILD_JOB_OPERATION_OUTCOMES = frozenset(
    {"success", "claimed", "empty", "ready", "not_ready", "error"}
)
_BUILD_JOB_CLAIM_OUTCOMES = frozenset({"claimed", "empty", "error"})
_BUILD_JOB_ERROR_CATEGORIES = frozenset({"connection", "data", "domain", "unknown"})
_BUILD_JOB_RETENTION_ACTIONS = frozenset({"archived", "purged"})


def _build_job_metric_label(value: object, allowed: frozenset[str]) -> str:
    normalized = _metric_label(value, default="unknown")
    return normalized if normalized in allowed else "unknown"


def _degradation_reason(error: Mapping[object, object]) -> str:
    code = _metric_label(error.get("code"), default="unknown")
    detail = _metric_label(error.get("detail"), default="unknown")
    if "circuit_open" in detail or "circuit_open" in code:
        return "circuit_open"
    if "request_skipped" in detail or "request_skipped" in code:
        return "request_skip"
    if "retrieval_failed" in detail or "retrieval_failed" in code:
        return "retrieval_failed"
    if "degraded" in detail or "degraded" in code:
        return "degraded"
    return "unknown"


atexit.register(shutdown_runtime_telemetry)


__all__ = [
    "RuntimeTelemetry",
    "TelemetryIdentity",
    "get_runtime_telemetry",
    "shutdown_runtime_telemetry",
]
