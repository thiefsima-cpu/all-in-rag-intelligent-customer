"""Shared JSON-shaped payload types and primitive normalization helpers."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import TypeAlias

from pydantic import JsonValue

JsonScalar: TypeAlias = str | int | float | bool | None
JsonObject: TypeAlias = dict[str, JsonValue]


def coerce_json_value(value: object) -> JsonValue:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Mapping):
        return {str(key): coerce_json_value(item) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [coerce_json_value(item) for item in value]
    if isinstance(value, set):
        return [coerce_json_value(item) for item in value]
    return str(value)


def coerce_json_object(value: object) -> JsonObject:
    payload = coerce_json_value(value)
    if isinstance(payload, dict):
        return payload
    return {}


def coerce_str(value: object) -> str:
    if value is None:
        return ""
    return str(value)


def coerce_float(value: object, default: float = 0.0) -> float:
    if not isinstance(value, (bool, int, float, str)):
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def coerce_int(value: object, default: int = 0, *, minimum: int = 0) -> int:
    if isinstance(value, (bool, int, float, str)):
        try:
            resolved = int(value)
        except (TypeError, ValueError):
            resolved = default
    else:
        resolved = default
    return max(minimum, resolved)


def bounded_float(
    value: object,
    default: float,
    *,
    minimum: float = 0.0,
    maximum: float = 1.0,
) -> float:
    return max(minimum, min(maximum, coerce_float(value, default)))


def as_string_list(value: object) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value).strip()
    return [text] if text else []


def clamp_float(value: object, default: float = 0.5) -> float:
    return bounded_float(value, default)


def clamp_int(value: object, default: int = 2, minimum: int = 1, maximum: int = 32) -> int:
    return max(minimum, min(maximum, coerce_int(value, default, minimum=minimum)))


def dedupe_preserve_order(values: Iterable[object] | None) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values or []:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


__all__ = [
    "JsonObject",
    "JsonScalar",
    "JsonValue",
    "as_string_list",
    "bounded_float",
    "clamp_float",
    "clamp_int",
    "coerce_float",
    "coerce_int",
    "coerce_json_object",
    "coerce_json_value",
    "coerce_str",
    "dedupe_preserve_order",
]
