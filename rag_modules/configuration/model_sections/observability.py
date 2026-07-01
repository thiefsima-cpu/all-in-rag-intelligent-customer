"""Observability configuration section model."""

from __future__ import annotations

from pydantic import Field

from .base import ConfigSection


class ObservabilitySettings(ConfigSection):
    enable_query_tracing: bool = True
    query_trace_path: str = "storage/traces/query_trace.jsonl"
    query_trace_async_enabled: bool = True
    query_trace_max_queue_size: int = 256
    query_trace_fingerprint_salt: str = Field(default="", repr=False)
    enable_opentelemetry: bool = False
    otel_service_name: str = "graphrag"
    otel_exporter_otlp_endpoint: str = ""
    otel_trace_sample_ratio: float = Field(default=1.0, ge=0.0, le=1.0)
    enable_prometheus: bool = True
    prometheus_public: bool = False


__all__ = ["ObservabilitySettings"]
