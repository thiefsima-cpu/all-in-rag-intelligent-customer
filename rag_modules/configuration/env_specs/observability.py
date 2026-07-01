"""Observability environment override specs."""

from __future__ import annotations

from .base import EnvFieldSpec
from .base import spec as _spec

OBSERVABILITY_ENV_FIELD_SPECS: tuple[EnvFieldSpec, ...] = (
    _spec("ENABLE_QUERY_TRACING", ("observability", "enable_query_tracing"), "bool"),
    _spec("QUERY_TRACE_PATH", ("observability", "query_trace_path"), "str"),
    _spec(
        "QUERY_TRACE_ASYNC_ENABLED",
        ("observability", "query_trace_async_enabled"),
        "bool",
    ),
    _spec("QUERY_TRACE_MAX_QUEUE_SIZE", ("observability", "query_trace_max_queue_size"), "int"),
    _spec(
        "QUERY_TRACE_FINGERPRINT_SALT",
        ("observability", "query_trace_fingerprint_salt"),
        "str",
    ),
    _spec("ENABLE_OPENTELEMETRY", ("observability", "enable_opentelemetry"), "bool"),
    _spec("OTEL_SERVICE_NAME", ("observability", "otel_service_name"), "str"),
    _spec(
        "OTEL_EXPORTER_OTLP_ENDPOINT",
        ("observability", "otel_exporter_otlp_endpoint"),
        "str",
    ),
    _spec("OTEL_TRACE_SAMPLE_RATIO", ("observability", "otel_trace_sample_ratio"), "float"),
    _spec("ENABLE_PROMETHEUS", ("observability", "enable_prometheus"), "bool"),
    _spec("PROMETHEUS_METRICS_PUBLIC", ("observability", "prometheus_public"), "bool"),
)


__all__ = ["OBSERVABILITY_ENV_FIELD_SPECS"]
