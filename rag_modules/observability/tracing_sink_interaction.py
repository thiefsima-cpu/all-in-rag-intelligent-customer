"""Trace sink interaction helpers."""

from __future__ import annotations

import logging
from typing import Protocol

from ..runtime import QueryTraceEvent
from ..runtime.json_types import JsonObject, coerce_json_object
from ..safe_logging import log_failure
from .tracing_sinks import QueryTraceSink

logger = logging.getLogger(__name__)


class _TraceSinkInteractionHost(Protocol):
    enabled: bool
    sink: QueryTraceSink
    trace_path: str


class _TraceSinkInteractionMixin(_TraceSinkInteractionHost):
    """Own trace sink writes, close, and stats interactions."""

    def _write_event(self, event: QueryTraceEvent) -> None:
        if not self.enabled:
            return
        try:
            self.sink.write(event)
        except Exception as exc:
            log_failure(
                logger,
                logging.WARNING,
                "query_trace_sink_failed",
                code="TRACE_SINK_FAILED",
                error=exc,
            )

    def close(self) -> None:
        try:
            self.sink.close()
        except Exception as exc:
            log_failure(
                logger,
                logging.WARNING,
                "query_trace_sink_failed",
                code="TRACE_SINK_FAILED",
                error=exc,
            )

    def stats(self) -> JsonObject:
        sink_stats: JsonObject = {}
        sink_stats_getter = getattr(self.sink, "stats", None)
        if callable(sink_stats_getter):
            try:
                sink_stats = coerce_json_object(sink_stats_getter() or {})
            except Exception as exc:
                log_failure(
                    logger,
                    logging.DEBUG,
                    "query_trace_sink_failed",
                    code="TRACE_SINK_FAILED",
                    error=exc,
                )
        return coerce_json_object(
            {
                "enabled": self.enabled,
                "path": self.trace_path,
                **sink_stats,
            }
        )


__all__ = ["_TraceSinkInteractionMixin"]
