"""Payload coercion helpers for diagnostics DTOs."""

from __future__ import annotations

from ..kernel.json_types import (
    JsonObject,
    JsonValue,
    coerce_json_float,
    coerce_json_int,
    coerce_json_object,
)


def int_map(payload: object) -> dict[str, int]:
    data = coerce_json_object(payload)
    return {str(key): coerce_json_int(value, 0) for key, value in data.items()}


def coerce_json_bool(value: object, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
    return default


def optional_json_float(data: JsonObject, key: str) -> float | None:
    if key not in data or data[key] is None:
        return None
    return coerce_json_float(data[key], 0.0)


def extra_payload(data: JsonObject, known_keys: frozenset[str]) -> JsonObject:
    return {key: value for key, value in data.items() if key not in known_keys}


def put_if_present_or_meaningful(
    payload: JsonObject,
    present_keys: frozenset[str],
    key: str,
    value: JsonValue,
) -> None:
    if key in present_keys or is_meaningful_json_value(value):
        payload[key] = value


def is_meaningful_json_value(value: JsonValue) -> bool:
    if value is None:
        return False
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return bool(value)
    return bool(value)


__all__ = [
    "coerce_json_bool",
    "extra_payload",
    "int_map",
    "is_meaningful_json_value",
    "optional_json_float",
    "put_if_present_or_meaningful",
]
