"""Structured query tracing."""

from __future__ import annotations

from collections.abc import Mapping

from ..configuration.models import GraphRAGConfig
from ..contracts import EvidenceDocument
from ..runtime import (
    AnswerContext,
    GenerationSnapshot,
    GraphRetrievalSnapshot,
    QueryTraceEvent,
    RetrievalOutcome,
    RouteSnapshot,
    RuntimeErrorDetail,
)
from ..runtime.json_types import JsonValue
from ..trace_privacy import TraceSanitizer
from .tracing_diagnostics import _TraceDiagnosticsMixin
from .tracing_event_builder import _TraceEventBuilderMixin
from .tracing_sink_interaction import _TraceSinkInteractionMixin
from .tracing_sinks import JsonlQueryTraceSink, NullQueryTraceSink, QueryTraceSink


class QueryTracer(
    _TraceDiagnosticsMixin,
    _TraceEventBuilderMixin,
    _TraceSinkInteractionMixin,
):
    def __init__(self, config: GraphRAGConfig, sink: QueryTraceSink | None = None) -> None:
        self.config = config
        self.models = config.models
        self.observability = config.observability
        self.enabled = bool(self.observability.enable_query_tracing)
        self.trace_path = str(self.observability.query_trace_path)
        self.sanitizer = TraceSanitizer(
            getattr(self.observability, "query_trace_fingerprint_salt", "")
        )
        self.sink = sink or (
            JsonlQueryTraceSink(self.trace_path) if self.enabled else NullQueryTraceSink()
        )

    def record(
        self,
        query: str,
        analysis: object,
        documents: list[EvidenceDocument] | RetrievalOutcome | AnswerContext,
        latency_ms: float,
        answer: str | None = None,
        error: RuntimeErrorDetail | Mapping[str, JsonValue] | None = None,
        route_trace: Mapping[str, JsonValue] | RouteSnapshot | None = None,
        graph_trace: Mapping[str, JsonValue] | GraphRetrievalSnapshot | None = None,
        generation_trace: Mapping[str, JsonValue] | GenerationSnapshot | None = None,
    ) -> QueryTraceEvent:
        evidence_documents = self._normalize_evidence_documents(documents)
        event = self._build_event(
            query,
            analysis,
            documents,
            evidence_documents,
            latency_ms,
            answer,
            error,
            route_trace,
            graph_trace,
            generation_trace,
        )
        event = self.sanitizer.sanitize_event(event)
        self._write_event(event)
        return event
