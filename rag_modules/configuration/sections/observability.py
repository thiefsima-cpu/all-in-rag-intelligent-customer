"""Observability configuration section loader."""

from __future__ import annotations

from typing import Any, Mapping

from ..env import EnvConfigSource
from ..models import ObservabilitySettings
from .common import mapping_defaults


def load_observability_settings(
    source: EnvConfigSource,
    defaults: Mapping[str, Any] | None = None,
) -> ObservabilitySettings:
    observability_defaults = mapping_defaults(defaults)
    return ObservabilitySettings(
        enable_query_tracing=source.get_bool(
            "ENABLE_QUERY_TRACING",
            bool(observability_defaults.get("enable_query_tracing", True)),
        ),
        query_trace_path=source.get_str(
            "QUERY_TRACE_PATH",
            str(observability_defaults.get("query_trace_path", "storage/traces/query_trace.jsonl")),
        ),
        query_trace_async_enabled=source.get_bool(
            "QUERY_TRACE_ASYNC_ENABLED",
            bool(observability_defaults.get("query_trace_async_enabled", True)),
        ),
        query_trace_max_queue_size=source.get_int(
            "QUERY_TRACE_MAX_QUEUE_SIZE",
            int(observability_defaults.get("query_trace_max_queue_size", 256)),
        ),
        query_trace_fingerprint_salt=source.get_str(
            "QUERY_TRACE_FINGERPRINT_SALT",
            str(observability_defaults.get("query_trace_fingerprint_salt", "")),
        ),
        enable_opentelemetry=source.get_bool(
            "ENABLE_OPENTELEMETRY",
            bool(observability_defaults.get("enable_opentelemetry", False)),
        ),
        otel_service_name=source.get_str(
            "OTEL_SERVICE_NAME",
            str(observability_defaults.get("otel_service_name", "graphrag")),
        ),
        otel_exporter_otlp_endpoint=source.get_str(
            "OTEL_EXPORTER_OTLP_ENDPOINT",
            str(
                observability_defaults.get(
                    "otel_exporter_otlp_endpoint",
                    "",
                )
            ),
        ),
        otel_trace_sample_ratio=min(
            1.0,
            max(
                0.0,
                source.get_float(
                    "OTEL_TRACE_SAMPLE_RATIO",
                    float(
                        observability_defaults.get(
                            "otel_trace_sample_ratio",
                            1.0,
                        )
                    ),
                ),
            ),
        ),
        enable_prometheus=source.get_bool(
            "ENABLE_PROMETHEUS",
            bool(observability_defaults.get("enable_prometheus", True)),
        ),
        prometheus_public=source.get_bool(
            "PROMETHEUS_METRICS_PUBLIC",
            bool(observability_defaults.get("prometheus_public", False)),
        ),
    )


__all__ = ["load_observability_settings"]
