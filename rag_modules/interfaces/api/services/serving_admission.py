"""Admission control for serving answer requests."""

from __future__ import annotations

import threading
from collections.abc import Iterator
from contextlib import contextmanager

from .errors import ApiBackpressureError

DEFAULT_MAX_CONCURRENT_ANSWERS = 4


class ServingAnswerAdmissionController:
    """Limit concurrent answer work at the API boundary."""

    def __init__(self, *, max_concurrent_answers: int, acquire_timeout_seconds: float) -> None:
        self.max_concurrent_answers = max(
            1,
            int(max_concurrent_answers or DEFAULT_MAX_CONCURRENT_ANSWERS),
        )
        self.acquire_timeout_seconds = max(0.0, float(acquire_timeout_seconds or 0.0))
        self._semaphore = threading.BoundedSemaphore(self.max_concurrent_answers)

    @contextmanager
    def permit(self) -> Iterator[None]:
        semaphore = self._semaphore
        if not semaphore.acquire(timeout=self.acquire_timeout_seconds):
            raise ApiBackpressureError()
        try:
            yield
        finally:
            semaphore.release()


__all__ = ["DEFAULT_MAX_CONCURRENT_ANSWERS", "ServingAnswerAdmissionController"]
