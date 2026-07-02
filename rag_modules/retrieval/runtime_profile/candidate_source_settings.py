"""Candidate-source resilience runtime settings."""

from __future__ import annotations

from dataclasses import dataclass

from ..candidate_generator import (
    CandidateSourceDegradationStrategy,
    _normalize_source_degradation_strategy,
)
from .shared import _CANDIDATE_SOURCE_DEFAULTS, _as_int

CANDIDATE_SOURCE_DEGRADATION_CONTINUE = CandidateSourceDegradationStrategy.CONTINUE.value
CANDIDATE_SOURCE_DEGRADATION_FAIL_FAST = CandidateSourceDegradationStrategy.FAIL_FAST.value
SUPPORTED_CANDIDATE_SOURCE_DEGRADATION_STRATEGIES = {
    strategy.value for strategy in CandidateSourceDegradationStrategy
}


def _as_recovery_seconds(value: object, default: float) -> float:
    resolved = default
    if isinstance(value, (bool, int, float, str)):
        try:
            resolved = float(value)
        except (TypeError, ValueError):
            resolved = default
    return max(0.1, resolved)


def _normalize_degradation_strategy(value: object) -> CandidateSourceDegradationStrategy:
    default = str(_CANDIDATE_SOURCE_DEFAULTS.degradation_strategy).strip().lower()
    candidate = value if isinstance(value, (CandidateSourceDegradationStrategy, str)) else default
    try:
        return _normalize_source_degradation_strategy(candidate or default)
    except ValueError:
        supported = ", ".join(strategy.value for strategy in CandidateSourceDegradationStrategy)
        raise ValueError(
            f"candidate_source_degradation_strategy must be one of: {supported}"
        ) from None


@dataclass
class RetrievalCandidateSourceSettings:
    failure_threshold: int = _CANDIDATE_SOURCE_DEFAULTS.failure_threshold
    recovery_timeout_seconds: float = _CANDIDATE_SOURCE_DEFAULTS.recovery_timeout_seconds
    degradation_strategy: CandidateSourceDegradationStrategy | str = str(
        _CANDIDATE_SOURCE_DEFAULTS.degradation_strategy
    )

    def __post_init__(self) -> None:
        self.failure_threshold = _as_int(
            self.failure_threshold,
            _CANDIDATE_SOURCE_DEFAULTS.failure_threshold,
            minimum=1,
        )
        self.recovery_timeout_seconds = _as_recovery_seconds(
            self.recovery_timeout_seconds,
            _CANDIDATE_SOURCE_DEFAULTS.recovery_timeout_seconds,
        )
        self.degradation_strategy = _normalize_degradation_strategy(
            self.degradation_strategy,
        )

    @classmethod
    def from_config(cls, config) -> "RetrievalCandidateSourceSettings":
        retrieval = config.retrieval
        return cls(
            failure_threshold=retrieval.candidate_source_failure_threshold,
            recovery_timeout_seconds=retrieval.candidate_source_recovery_seconds,
            degradation_strategy=retrieval.candidate_source_degradation_strategy,
        )

    def to_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {}
        for field in self.__dataclass_fields__.values():
            value = getattr(self, field.name)
            payload[field.name] = (
                value.value if isinstance(value, CandidateSourceDegradationStrategy) else value
            )
        return payload


__all__ = [
    "CANDIDATE_SOURCE_DEGRADATION_CONTINUE",
    "CANDIDATE_SOURCE_DEGRADATION_FAIL_FAST",
    "RetrievalCandidateSourceSettings",
    "SUPPORTED_CANDIDATE_SOURCE_DEGRADATION_STRATEGIES",
]
