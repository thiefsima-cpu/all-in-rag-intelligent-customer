"""Shared normalization helpers for query contracts."""

from __future__ import annotations

from typing import Any, Iterable, List


def dedupe_preserve_order(values: Iterable[Any]) -> List[str]:
    seen = set()
    result: List[str] = []
    for value in values or []:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def as_list(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return [str(value).strip()] if str(value).strip() else []


def clamp_float(value: Any, default: float = 0.5) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = default
    return max(0.0, min(1.0, number))


def clamp_int(value: Any, default: int = 2, minimum: int = 1, maximum: int = 32) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = default
    return max(minimum, min(maximum, number))


__all__ = ["as_list", "clamp_float", "clamp_int", "dedupe_preserve_order"]
