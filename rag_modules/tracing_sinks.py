"""Persistence sinks for structured query traces."""

from __future__ import annotations

import json
import logging
import os
import queue
import threading
from typing import Protocol

from .runtime import QueryTraceEvent
from .trace_privacy import TraceSanitizer

logger = logging.getLogger(__name__)


class _QueueSentinel:
    pass


_QUEUE_SENTINEL = _QueueSentinel()


class QueryTraceSink(Protocol):
    """Persist or forward structured query trace events."""

    def write(self, event: QueryTraceEvent) -> None: ...

    def close(self) -> None: ...


class QueryTraceSinkFactory(Protocol):
    """Create trace sinks for concrete runtime environments."""

    def create(self, path: str) -> QueryTraceSink: ...


class NullQueryTraceSink:
    """No-op trace sink used when tracing is disabled."""

    def __init__(self) -> None:
        self._closed = False

    def write(self, event: QueryTraceEvent) -> None:
        del event

    def close(self) -> None:
        self._closed = True

    def stats(self) -> dict[str, int | bool | str]:
        return {
            "sink_type": "null",
            "async_enabled": False,
            "queued_events": 0,
            "dropped_events": 0,
            "written_events": 0,
            "failed_events": 0,
            "closed": self._closed,
            "max_queue_size": 0,
        }


class JsonlQueryTraceSink:
    """Append query traces to a UTF-8 JSONL file."""

    def __init__(self, path: str, *, sanitizer: TraceSanitizer | None = None) -> None:
        self.path = str(path or "storage/traces/query_trace.jsonl")
        self.sanitizer = sanitizer or TraceSanitizer()
        self._written_events = 0
        self._closed = False

    def write(self, event: QueryTraceEvent) -> None:
        if self._closed:
            logger.debug("Ignoring query trace after JSONL sink closure.")
            return
        event = self.sanitizer.sanitize_event(event)
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        with open(self.path, "a", encoding="utf-8") as file:
            file.write(json.dumps(event.to_dict(), ensure_ascii=False) + "\n")
        self._written_events += 1

    def close(self) -> None:
        self._closed = True

    def stats(self) -> dict[str, int | bool | str]:
        return {
            "sink_type": "jsonl",
            "async_enabled": False,
            "queued_events": 0,
            "dropped_events": 0,
            "written_events": self._written_events,
            "failed_events": 0,
            "closed": self._closed,
            "max_queue_size": 0,
            "path": self.path,
        }


class JsonlQueryTraceSinkFactory:
    """Create JSONL sinks, optionally wrapped in an async worker."""

    def __init__(
        self,
        *,
        async_enabled: bool = False,
        max_queue_size: int = 0,
        worker_name: str = "query-trace-sink",
    ) -> None:
        self.async_enabled = bool(async_enabled)
        self.max_queue_size = max(0, int(max_queue_size or 0))
        self.worker_name = str(worker_name or "query-trace-sink")

    def create(self, path: str) -> QueryTraceSink:
        sink: QueryTraceSink = JsonlQueryTraceSink(path)
        if self.async_enabled:
            sink = AsyncQueryTraceSink(
                sink,
                max_queue_size=self.max_queue_size,
                worker_name=self.worker_name,
            )
        return sink


class AsyncQueryTraceSink:
    """Write traces to another sink from a background worker."""

    def __init__(
        self,
        delegate: QueryTraceSink,
        *,
        max_queue_size: int = 0,
        worker_name: str = "query-trace-sink",
    ) -> None:
        self.delegate = delegate
        self._queue: queue.Queue[QueryTraceEvent | _QueueSentinel] = queue.Queue(
            maxsize=max(0, int(max_queue_size or 0))
        )
        self._max_queue_size = max(0, int(max_queue_size or 0))
        self._closed = False
        self._dropped_events = 0
        self._written_events = 0
        self._failed_events = 0
        self._stats_lock = threading.Lock()
        self._worker = threading.Thread(
            target=self._drain_queue,
            name=worker_name,
            daemon=True,
        )
        self._worker.start()

    def write(self, event: QueryTraceEvent) -> None:
        with self._stats_lock:
            if self._closed:
                logger.debug("Ignoring query trace after sink closure.")
                return
        cloned_event = QueryTraceEvent.from_dict(event.to_dict())
        try:
            self._queue.put_nowait(cloned_event)
        except queue.Full:
            with self._stats_lock:
                self._dropped_events += 1
                dropped_events = self._dropped_events
            if dropped_events == 1 or dropped_events % 100 == 0:
                logger.warning(
                    "Dropping query trace events because the async sink queue is full. dropped=%s",
                    dropped_events,
                )

    def close(self) -> None:
        with self._stats_lock:
            if self._closed:
                return
            self._closed = True
        while True:
            try:
                self._queue.put(_QUEUE_SENTINEL, timeout=0.1)
                break
            except queue.Full:
                continue
        self._worker.join(timeout=5.0)
        try:
            self.delegate.close()
        except Exception as exc:
            logger.warning("Failed to close query trace delegate sink: %s", exc)

    def stats(self) -> dict[str, int | bool | str]:
        base_stats = {}
        stats_getter = getattr(self.delegate, "stats", None)
        if callable(stats_getter):
            try:
                base_stats = dict(stats_getter() or {})
            except Exception as exc:
                logger.debug("Failed to read delegate trace sink stats: %s", exc)
        with self._stats_lock:
            closed = self._closed
            dropped_events = self._dropped_events
            written_events = self._written_events
            failed_events = self._failed_events
        return {
            **base_stats,
            "sink_type": base_stats.get("sink_type", "async"),
            "async_enabled": True,
            "queued_events": self._queue.qsize(),
            "dropped_events": dropped_events,
            "written_events": written_events,
            "failed_events": failed_events,
            "closed": closed,
            "max_queue_size": self._max_queue_size,
        }

    def _drain_queue(self) -> None:
        while True:
            event = self._queue.get()
            if isinstance(event, _QueueSentinel):
                break
            try:
                self.delegate.write(event)
            except Exception as exc:
                with self._stats_lock:
                    self._failed_events += 1
                logger.warning("Failed to persist async query trace event: %s", exc)
            else:
                with self._stats_lock:
                    self._written_events += 1
