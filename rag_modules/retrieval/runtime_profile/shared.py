"""Shared helpers for retrieval runtime profiles."""

from __future__ import annotations

from ...query_policy import get_query_policy

_POLICY = get_query_policy()
_PLANNER_DEFAULTS = _POLICY.runtime_defaults.planner
_SEMANTIC_DEFAULTS = _POLICY.runtime_defaults.semantics
_CANDIDATE_DEFAULTS = _POLICY.runtime_defaults.candidates
_CANDIDATE_SOURCE_DEFAULTS = _POLICY.runtime_defaults.candidate_sources
_POSTPROCESS_DEFAULTS = _POLICY.runtime_defaults.postprocess


def _as_int(value: object, default: int, *, minimum: int = 0) -> int:
    resolved = default
    if isinstance(value, (bool, int, float, str)):
        try:
            resolved = int(value)
        except (TypeError, ValueError):
            resolved = default
    return max(minimum, resolved)


def _as_float(
    value: object,
    default: float,
    *,
    minimum: float = 0.0,
    maximum: float = 1.0,
) -> float:
    resolved = default
    if isinstance(value, (bool, int, float, str)):
        try:
            resolved = float(value)
        except (TypeError, ValueError):
            resolved = default
    return max(minimum, min(maximum, resolved))


__all__ = [
    "_CANDIDATE_DEFAULTS",
    "_CANDIDATE_SOURCE_DEFAULTS",
    "_PLANNER_DEFAULTS",
    "_POSTPROCESS_DEFAULTS",
    "_SEMANTIC_DEFAULTS",
    "_as_float",
    "_as_int",
]
