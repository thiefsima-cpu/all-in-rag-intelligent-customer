"""Shared JSON-shaped payload types for API and runtime diagnostics."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
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
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        return coerce_json_value(to_dict())
    return str(value)


def coerce_json_object(value: object) -> JsonObject:
    payload = coerce_json_value(value)
    if isinstance(payload, dict):
        return payload
    return {}


__all__ = ["JsonObject", "JsonScalar", "JsonValue", "coerce_json_object", "coerce_json_value"]
