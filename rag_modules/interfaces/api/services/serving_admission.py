"""Admission control for serving answer requests."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager

from .errors import ApiBackpressureError

DEFAULT_MAX_CONCURRENT_ANSWERS = 4
AdmissionRecorder = Callable[[float, bool], None]


class ServingAnswerAdmissionController:
    """Limit concurrent answer work at the API boundary."""

    def __init__(
        self,
        *,
        max_concurrent_answers: int,
        acquire_timeout_seconds: float,
        recorder: AdmissionRecorder | None = None,
    ) -> None:
        self.max_concurrent_answers = max(
            1,
            int(max_concurrent_answers or DEFAULT_MAX_CONCURRENT_ANSWERS),
        )
        self.acquire_timeout_seconds = max(0.0, float(acquire_timeout_seconds or 0.0))
        self._semaphore = threading.BoundedSemaphore(self.max_concurrent_answers)
        self._recorder = recorder

    @contextmanager
    def permit(self) -> Iterator[None]:
        semaphore = self._semaphore
        started = time.perf_counter()
        acquired = semaphore.acquire(timeout=self.acquire_timeout_seconds)
        wait_seconds = time.perf_counter() - started
        if self._recorder is not None:
            self._recorder(wait_seconds, acquired)
        if not acquired:
            raise ApiBackpressureError()
        try:
            yield
        finally:
            semaphore.release()


__all__ = [
    "DEFAULT_MAX_CONCURRENT_ANSWERS",
    "AdmissionRecorder",
    "ServingAnswerAdmissionController",
]
