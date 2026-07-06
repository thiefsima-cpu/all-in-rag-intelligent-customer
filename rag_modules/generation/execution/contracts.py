"""Shared contracts for generation execution collaborators."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass


def non_negative_int(value: object) -> int:
    if isinstance(value, (bool, int, float, str)):
        try:
            return max(0, int(value or 0))
        except (TypeError, ValueError):
            return 0
    return 0


@dataclass(frozen=True)
class GenerationTokenUsage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    token_usage_source: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "prompt_tokens", non_negative_int(self.prompt_tokens))
        object.__setattr__(self, "completion_tokens", non_negative_int(self.completion_tokens))
        object.__setattr__(self, "total_tokens", non_negative_int(self.total_tokens))
        object.__setattr__(self, "token_usage_source", str(self.token_usage_source or ""))

    @classmethod
    def from_payload(cls, value: object) -> "GenerationTokenUsage":
        payload: Mapping[object, object] = value if isinstance(value, Mapping) else {}
        return cls(
            prompt_tokens=non_negative_int(payload.get("prompt_tokens")),
            completion_tokens=non_negative_int(payload.get("completion_tokens")),
            total_tokens=non_negative_int(payload.get("total_tokens")),
            token_usage_source=str(payload.get("token_usage_source") or ""),
        )


@dataclass(frozen=True)
class GenerationAttemptResult:
    answer: str
    plan_latency_ms: float = 0.0
    compose_latency_ms: float = 0.0
    direct_latency_ms: float = 0.0
    request_retries: int = 0
    status: str = "success"
    fallback_used: bool = False
    fallback_reason: str = ""
    failure: Exception | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "answer", str(self.answer or ""))
        object.__setattr__(self, "plan_latency_ms", max(0.0, float(self.plan_latency_ms or 0.0)))
        object.__setattr__(
            self,
            "compose_latency_ms",
            max(0.0, float(self.compose_latency_ms or 0.0)),
        )
        object.__setattr__(
            self,
            "direct_latency_ms",
            max(0.0, float(self.direct_latency_ms or 0.0)),
        )
        object.__setattr__(self, "request_retries", non_negative_int(self.request_retries))
        object.__setattr__(self, "status", str(self.status or "success"))
        object.__setattr__(self, "fallback_reason", str(self.fallback_reason or ""))

    @property
    def provider_latency_ms(self) -> float:
        return self.plan_latency_ms + self.compose_latency_ms + self.direct_latency_ms


class GenerationAttemptFailed(Exception):
    """Wrap a failed execution attempt with already-consumed retry state."""

    def __init__(self, error: Exception, *, request_retries: int = 0) -> None:
        super().__init__(str(error) or error.__class__.__name__)
        self.error = error
        self.request_retries = non_negative_int(request_retries)


__all__ = [
    "GenerationAttemptFailed",
    "GenerationAttemptResult",
    "GenerationTokenUsage",
    "non_negative_int",
]
