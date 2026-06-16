"""Shared helpers for retrieval runtime profiles."""

from __future__ import annotations

from typing import Any

from ...query_policy import get_query_policy

_POLICY = get_query_policy()
_PLANNER_DEFAULTS = _POLICY.runtime_section("planner")
_SEMANTIC_DEFAULTS = _POLICY.runtime_section("semantics")
_CANDIDATE_DEFAULTS = _POLICY.runtime_section("candidates")
_POSTPROCESS_DEFAULTS = _POLICY.runtime_section("postprocess")


def _as_int(value: Any, default: int, *, minimum: int = 0) -> int:
    try:
        resolved = int(value)
    except (TypeError, ValueError):
        resolved = default
    return max(minimum, resolved)


def _as_float(
    value: Any,
    default: float,
    *,
    minimum: float = 0.0,
    maximum: float = 1.0,
) -> float:
    try:
        resolved = float(value)
    except (TypeError, ValueError):
        resolved = default
    return max(minimum, min(maximum, resolved))


__all__ = [
    "_CANDIDATE_DEFAULTS",
    "_PLANNER_DEFAULTS",
    "_POSTPROCESS_DEFAULTS",
    "_SEMANTIC_DEFAULTS",
    "_as_float",
    "_as_int",
]
