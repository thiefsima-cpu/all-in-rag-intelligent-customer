"""Value coercion helpers for retrieval runtime profiles."""

from __future__ import annotations


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
    "_as_float",
    "_as_int",
]
