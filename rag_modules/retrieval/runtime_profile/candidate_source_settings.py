"""Candidate-source resilience runtime settings."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict

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


def _as_recovery_seconds(value: Any, default: float) -> float:
    try:
        resolved = float(value)
    except (TypeError, ValueError):
        resolved = default
    return max(0.1, resolved)


def _normalize_degradation_strategy(value: Any) -> CandidateSourceDegradationStrategy:
    default = (
        str(
            _CANDIDATE_SOURCE_DEFAULTS.get(
                "degradation_strategy",
                CANDIDATE_SOURCE_DEGRADATION_CONTINUE,
            )
        )
        .strip()
        .lower()
    )
    try:
        return _normalize_source_degradation_strategy(value or default)
    except ValueError:
        supported = ", ".join(strategy.value for strategy in CandidateSourceDegradationStrategy)
        raise ValueError(
            f"candidate_source_degradation_strategy must be one of: {supported}"
        ) from None


@dataclass
class RetrievalCandidateSourceSettings:
    failure_threshold: int = int(_CANDIDATE_SOURCE_DEFAULTS.get("failure_threshold", 1))
    recovery_timeout_seconds: float = float(
        _CANDIDATE_SOURCE_DEFAULTS.get("recovery_timeout_seconds", 30.0)
    )
    degradation_strategy: CandidateSourceDegradationStrategy | str = str(
        _CANDIDATE_SOURCE_DEFAULTS.get(
            "degradation_strategy", CANDIDATE_SOURCE_DEGRADATION_CONTINUE
        )
    )

    def __post_init__(self) -> None:
        self.failure_threshold = _as_int(
            self.failure_threshold,
            int(_CANDIDATE_SOURCE_DEFAULTS.get("failure_threshold", 1)),
            minimum=1,
        )
        self.recovery_timeout_seconds = _as_recovery_seconds(
            self.recovery_timeout_seconds,
            float(_CANDIDATE_SOURCE_DEFAULTS.get("recovery_timeout_seconds", 30.0)),
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

    def to_dict(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = {}
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
