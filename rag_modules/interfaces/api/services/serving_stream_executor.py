"""Bounded background execution for serving SSE sessions."""

from __future__ import annotations

import threading
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from typing import Protocol, TypeVar

from .errors import ApiBackpressureError

_T = TypeVar("_T")


class StreamExecutorObserver(Protocol):
    def record_sse_executor_state(
        self,
        *,
        active_delta: int = 0,
        queued_delta: int = 0,
        rejected_delta: int = 0,
    ) -> None: ...


@dataclass(frozen=True, slots=True)
class StreamExecutorSnapshot:
    max_workers: int
    max_outstanding: int
    active: int
    queued: int
    peak_active: int
    peak_queued: int
    peak_outstanding: int
    rejected: int

    def to_dict(self) -> dict[str, int]:
        return {
            "max_workers": self.max_workers,
            "max_outstanding": self.max_outstanding,
            "active": self.active,
            "queued": self.queued,
            "peak_active": self.peak_active,
            "peak_queued": self.peak_queued,
            "peak_outstanding": self.peak_outstanding,
            "rejected": self.rejected,
        }


class _Submission:
    def __init__(self) -> None:
        self.state = "queued"


class BoundedStreamExecutor:
    """Bound running plus queued work before it reaches ThreadPoolExecutor."""

    def __init__(
        self,
        *,
        max_workers: int,
        max_outstanding: int,
        observer: StreamExecutorObserver | None = None,
    ) -> None:
        if max_workers < 1:
            raise ValueError("max_workers must be at least 1")
        if max_outstanding < max_workers:
            raise ValueError("max_outstanding must be at least max_workers")
        self.max_workers = int(max_workers)
        self.max_outstanding = int(max_outstanding)
        self._observer = observer
        self._slots = threading.BoundedSemaphore(self.max_outstanding)
        self._state_lock = threading.Lock()
        self._lifecycle_lock = threading.Lock()
        self._closed = False
        self._active = 0
        self._queued = 0
        self._peak_active = 0
        self._peak_queued = 0
        self._peak_outstanding = 0
        self._rejected = 0
        self._executor = ThreadPoolExecutor(
            max_workers=self.max_workers,
            thread_name_prefix="graph-rag-answer",
        )

    def submit(self, fn: Callable[[], _T]) -> Future[_T]:
        with self._lifecycle_lock:
            if self._closed:
                raise RuntimeError("cannot schedule new futures after shutdown")
            if not self._slots.acquire(blocking=False):
                self._record_rejection()
                raise ApiBackpressureError()
            submission = _Submission()
            self._record_queued()
            try:
                future = self._executor.submit(self._run, submission, fn)
            except BaseException:
                self._release_queued(submission)
                raise
            future.add_done_callback(
                lambda completed: (
                    self._release_queued(submission) if completed.cancelled() else None
                )
            )
            return future

    def _run(self, submission: _Submission, fn: Callable[[], _T]) -> _T:
        self._start(submission)
        try:
            return fn()
        finally:
            self._finish(submission)

    def _record_queued(self) -> None:
        with self._state_lock:
            self._queued += 1
            self._peak_queued = max(self._peak_queued, self._queued)
            self._peak_outstanding = max(
                self._peak_outstanding,
                self._active + self._queued,
            )
            self._observe(queued_delta=1)

    def _start(self, submission: _Submission) -> None:
        with self._state_lock:
            if submission.state != "queued":
                raise RuntimeError("stream submission did not start from queued state")
            submission.state = "active"
            self._queued -= 1
            self._active += 1
            self._peak_active = max(self._peak_active, self._active)
            self._observe(active_delta=1, queued_delta=-1)

    def _finish(self, submission: _Submission) -> None:
        with self._state_lock:
            if submission.state != "active":
                return
            submission.state = "released"
            self._active -= 1
            self._observe(active_delta=-1)
        self._slots.release()

    def _release_queued(self, submission: _Submission) -> None:
        with self._state_lock:
            if submission.state != "queued":
                return
            submission.state = "released"
            self._queued -= 1
            self._observe(queued_delta=-1)
        self._slots.release()

    def _record_rejection(self) -> None:
        with self._state_lock:
            self._rejected += 1
            self._observe(rejected_delta=1)

    def _observe(
        self,
        *,
        active_delta: int = 0,
        queued_delta: int = 0,
        rejected_delta: int = 0,
    ) -> None:
        if self._observer is not None:
            self._observer.record_sse_executor_state(
                active_delta=active_delta,
                queued_delta=queued_delta,
                rejected_delta=rejected_delta,
            )

    def snapshot(self) -> StreamExecutorSnapshot:
        with self._state_lock:
            return StreamExecutorSnapshot(
                max_workers=self.max_workers,
                max_outstanding=self.max_outstanding,
                active=self._active,
                queued=self._queued,
                peak_active=self._peak_active,
                peak_queued=self._peak_queued,
                peak_outstanding=self._peak_outstanding,
                rejected=self._rejected,
            )

    def shutdown(self) -> None:
        with self._lifecycle_lock:
            if self._closed:
                return
            self._closed = True
        self._executor.shutdown(wait=False, cancel_futures=True)


__all__ = ["BoundedStreamExecutor", "StreamExecutorSnapshot"]
