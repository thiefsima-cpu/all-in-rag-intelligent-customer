"""Runtime request budget and cancellation controls."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field

from .json_types import JsonObject, coerce_json_object

_MIN_TIMEOUT_SECONDS = 0.1
_REASON_ATTR = "_request_control_reason"


class RequestControlError(RuntimeError):
    """Base class for request-control runtime exits."""


class RequestCancelled(RequestControlError):
    """Raised when request execution observes a cancellation signal."""


class RequestBudgetExceeded(RequestControlError):
    """Raised when request execution observes an exhausted budget."""


@dataclass(slots=True)
class RequestControl:
    deadline: float
    scope: str = "request"
    cancel_event: threading.Event = field(default_factory=threading.Event)
    _reason: str = ""

    @classmethod
    def for_timeout(cls, timeout_seconds: float, *, scope: str = "request") -> "RequestControl":
        timeout = max(_MIN_TIMEOUT_SECONDS, float(timeout_seconds or _MIN_TIMEOUT_SECONDS))
        return cls(deadline=time.perf_counter() + timeout, scope=str(scope or "request"))

    @property
    def cancelled(self) -> bool:
        return self.cancel_event.is_set()

    @property
    def reason(self) -> str:
        return self._reason or str(getattr(self.cancel_event, _REASON_ATTR, "") or "")

    @property
    def budget_exhausted(self) -> bool:
        return self.remaining_seconds(minimum=0.0) <= 0

    def remaining_seconds(self, *, minimum: float = _MIN_TIMEOUT_SECONDS) -> float:
        remaining = self.deadline - time.perf_counter()
        if minimum <= 0:
            return max(0.0, remaining)
        return max(float(minimum), remaining)

    def cancel(self, reason: str = "request_cancelled") -> None:
        if not self.reason:
            self._reason = str(reason or "request_cancelled")
            setattr(self.cancel_event, _REASON_ATTR, self._reason)
        self.cancel_event.set()

    def child(self, timeout_seconds: float, *, scope: str) -> "RequestControl":
        timeout = max(_MIN_TIMEOUT_SECONDS, float(timeout_seconds or _MIN_TIMEOUT_SECONDS))
        child_deadline = min(self.deadline, time.perf_counter() + timeout)
        return RequestControl(
            deadline=child_deadline,
            scope=str(scope or self.scope),
            cancel_event=self.cancel_event,
            _reason=self.reason,
        )

    def raise_if_cancelled(self) -> None:
        if self.cancelled:
            raise RequestCancelled(self.reason or f"{self.scope}_cancelled")
        if self.budget_exhausted:
            self._reason = self.reason or f"{self.scope}_budget_exhausted"
            setattr(self.cancel_event, _REASON_ATTR, self._reason)
            raise RequestBudgetExceeded(self._reason)

    def to_trace_details(self) -> JsonObject:
        remaining_ms = round(self.remaining_seconds(minimum=0.0) * 1000, 2)
        return coerce_json_object(
            {
                "scope": self.scope,
                "cancelled": self.cancelled,
                "reason": self.reason,
                "budget_exhausted": self.budget_exhausted,
                "remaining_ms": remaining_ms,
            }
        )


def control_trace_details(control: RequestControl | None) -> JsonObject:
    return control.to_trace_details() if control is not None else {}


__all__ = [
    "RequestBudgetExceeded",
    "RequestCancelled",
    "RequestControl",
    "RequestControlError",
    "control_trace_details",
]
