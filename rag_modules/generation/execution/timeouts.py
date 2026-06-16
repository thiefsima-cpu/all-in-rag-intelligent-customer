"""Generation execution timeout helpers."""

from __future__ import annotations

import time

from ..client import GenerationLatencyBudgetExceeded


class _GenerationTimeoutMixin:
    def _deadline(self, start_time: float) -> float:
        return start_time + float(self.settings.latency_budget_seconds)

    @staticmethod
    def _remaining_timeout(deadline: float, configured_timeout: int) -> float:
        remaining = deadline - time.perf_counter()
        if remaining <= 0:
            raise GenerationLatencyBudgetExceeded(
                "Generation latency budget was exhausted."
            )
        return max(0.1, min(float(configured_timeout), remaining))

    @staticmethod
    def _elapsed_ms(start_time: float) -> float:
        return round((time.perf_counter() - start_time) * 1000, 2)
