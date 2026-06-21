"""Thread-safe connection pooling and circuit-breaker primitives."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, TypeVar

import requests
from requests.adapters import HTTPAdapter

T = TypeVar("T")


class CircuitOpenError(RuntimeError):
    """Raised when a dependency circuit is open."""


@dataclass(frozen=True, slots=True)
class CircuitBreakerSnapshot:
    state: str
    failure_count: int
    opened_at: float


class CircuitBreaker:
    """Small in-process circuit breaker with one half-open probe."""

    def __init__(
        self,
        *,
        failure_threshold: int = 5,
        recovery_timeout_seconds: float = 30.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.failure_threshold = max(1, int(failure_threshold))
        self.recovery_timeout_seconds = max(
            0.1,
            float(recovery_timeout_seconds),
        )
        self._clock = clock
        self._lock = threading.Lock()
        self._state = "closed"
        self._failure_count = 0
        self._opened_at = 0.0
        self._half_open_probe_active = False

    def call(self, operation: Callable[..., T], *args: Any, **kwargs: Any) -> T:
        self.before_call()
        try:
            result = operation(*args, **kwargs)
        except Exception:
            self.record_failure()
            raise
        self.record_success()
        return result

    def before_call(self) -> None:
        with self._lock:
            if self._state == "closed":
                return
            if self._state == "open":
                elapsed = self._clock() - self._opened_at
                if elapsed < self.recovery_timeout_seconds:
                    raise CircuitOpenError("Dependency circuit is open.")
                self._state = "half_open"
            if self._half_open_probe_active:
                raise CircuitOpenError("Dependency circuit is half-open.")
            self._half_open_probe_active = True

    def record_success(self) -> None:
        with self._lock:
            self._state = "closed"
            self._failure_count = 0
            self._opened_at = 0.0
            self._half_open_probe_active = False

    def record_failure(self) -> None:
        with self._lock:
            self._half_open_probe_active = False
            self._failure_count += 1
            if self._state == "half_open" or self._failure_count >= self.failure_threshold:
                self._state = "open"
                self._opened_at = self._clock()

    def snapshot(self) -> CircuitBreakerSnapshot:
        with self._lock:
            return CircuitBreakerSnapshot(
                state=self._state,
                failure_count=self._failure_count,
                opened_at=self._opened_at,
            )


def build_pooled_requests_session(
    *,
    pool_connections: int = 10,
    pool_maxsize: int = 20,
) -> requests.Session:
    """Create a requests session with bounded reusable HTTP connection pools."""

    session = requests.Session()
    adapter = HTTPAdapter(
        pool_connections=max(1, int(pool_connections)),
        pool_maxsize=max(1, int(pool_maxsize)),
        max_retries=0,
        pool_block=True,
    )
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session


__all__ = [
    "CircuitBreaker",
    "CircuitBreakerSnapshot",
    "CircuitOpenError",
    "build_pooled_requests_session",
]
