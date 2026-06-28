"""Shared coercion helpers for contract DTOs."""

from __future__ import annotations

from typing import Any


def coerce_str(value: Any) -> str:
    if value is None:
        return ""
    return str(value)


def coerce_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def coerce_int(value: Any, default: int = 0, *, minimum: int = 0) -> int:
    try:
        resolved = int(value)
    except (TypeError, ValueError):
        resolved = default
    return max(minimum, resolved)


def bounded_float(
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

