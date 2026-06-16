"""Shared coercion helpers for retrieval runtime contracts."""

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
