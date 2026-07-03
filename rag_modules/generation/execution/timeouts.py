"""Generation execution timeout collaborators."""

from __future__ import annotations

import time
from dataclasses import dataclass

from ..clients import GenerationLatencyBudgetExceeded


@dataclass(frozen=True)
class GenerationExecutionDeadline:
    started_at: float
    expires_at: float

    def remaining_timeout(self, configured_timeout: int | float) -> float:
        remaining = self.expires_at - time.perf_counter()
        if remaining <= 0:
            raise GenerationLatencyBudgetExceeded("Generation latency budget was exhausted.")
        return max(0.1, min(float(configured_timeout), remaining))

    @staticmethod
    def elapsed_ms_since(start_time: float) -> float:
        return round((time.perf_counter() - start_time) * 1000, 2)

    def total_elapsed_ms(self) -> float:
        return self.elapsed_ms_since(self.started_at)


class GenerationTimeoutBudget:
    def __init__(self, latency_budget_seconds: int | float) -> None:
        self.latency_budget_seconds = max(0.1, float(latency_budget_seconds or 0.1))

    def start(self) -> GenerationExecutionDeadline:
        started_at = time.perf_counter()
        return GenerationExecutionDeadline(
            started_at=started_at,
            expires_at=started_at + self.latency_budget_seconds,
        )

    @staticmethod
    def elapsed_ms_since(start_time: float) -> float:
        return GenerationExecutionDeadline.elapsed_ms_since(start_time)


__all__ = ["GenerationExecutionDeadline", "GenerationTimeoutBudget"]
