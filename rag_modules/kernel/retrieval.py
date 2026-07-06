"""Pure retrieval configuration values."""

from __future__ import annotations

from enum import Enum


class CandidateSourceDegradationStrategy(str, Enum):
    CONTINUE = "continue"
    FAIL_FAST = "fail_fast"


SOURCE_DEGRADATION_STRATEGY_CONTINUE = CandidateSourceDegradationStrategy.CONTINUE.value
SOURCE_DEGRADATION_STRATEGY_FAIL_FAST = CandidateSourceDegradationStrategy.FAIL_FAST.value
SUPPORTED_SOURCE_DEGRADATION_STRATEGIES = {
    strategy.value for strategy in CandidateSourceDegradationStrategy
}


def candidate_source_degradation_strategy(
    value: CandidateSourceDegradationStrategy | str,
) -> CandidateSourceDegradationStrategy:
    if isinstance(value, CandidateSourceDegradationStrategy):
        return value
    normalized = str(value or CandidateSourceDegradationStrategy.CONTINUE.value).strip().lower()
    try:
        return CandidateSourceDegradationStrategy(normalized)
    except ValueError:
        supported = ", ".join(strategy.value for strategy in CandidateSourceDegradationStrategy)
        raise ValueError(f"source_degradation_strategy must be one of: {supported}") from None


__all__ = [
    "CandidateSourceDegradationStrategy",
    "SOURCE_DEGRADATION_STRATEGY_CONTINUE",
    "SOURCE_DEGRADATION_STRATEGY_FAIL_FAST",
    "SUPPORTED_SOURCE_DEGRADATION_STRATEGIES",
    "candidate_source_degradation_strategy",
]
