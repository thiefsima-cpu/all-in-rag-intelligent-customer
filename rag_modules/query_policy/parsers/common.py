"""Shared coercion helpers for query policy section parsers."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import cast

from ..models import PolicyLoadError


def mapping(value: object, root: Path, field_path: str) -> Mapping[str, object]:
    if not isinstance(value, dict):
        raise PolicyLoadError(
            f"Policy field must be an object: {field_path}",
            bundle_path=str(root),
            field_path=field_path,
        )
    return cast(Mapping[str, object], value)


def optional_mapping(value: object, root: Path, field_path: str) -> Mapping[str, object]:
    if value is None:
        return {}
    return mapping(value, root, field_path)


def required_mapping(
    payload: Mapping[str, object],
    key: str,
    root: Path,
    *,
    field_path: str | None = None,
) -> Mapping[str, object]:
    path = field_path or key
    value = payload.get(key)
    if not isinstance(value, dict):
        raise PolicyLoadError(
            f"Policy section must be an object: {path}",
            bundle_path=str(root),
            field_path=path,
        )
    return cast(Mapping[str, object], value)


def require_keys(
    payload: Mapping[str, object],
    keys: tuple[str, ...],
    root: Path,
    field_path: str,
) -> None:
    for key in keys:
        if key not in payload:
            raise PolicyLoadError(
                f"Policy field is required: {field_path}.{key}",
                bundle_path=str(root),
                field_path=f"{field_path}.{key}",
            )


def to_tuple(value: object) -> tuple[str, ...]:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return tuple(str(item) for item in value if str(item).strip())
    if value is None:
        return ()
    text = str(value).strip()
    return (text,) if text else ()


def to_tuple_map(value: object, root: Path, field_path: str) -> dict[str, tuple[str, ...]]:
    payload = optional_mapping(value, root, field_path)
    return {str(key): to_tuple(items) for key, items in payload.items()}


def to_str_map(value: object, root: Path, field_path: str) -> dict[str, str]:
    payload = optional_mapping(value, root, field_path)
    return {
        str(key): str(item)
        for key, item in payload.items()
        if str(key).strip() and str(item).strip()
    }


def to_float_map(value: object, root: Path, field_path: str) -> dict[str, float]:
    result: dict[str, float] = {}
    for key, item in optional_mapping(value, root, field_path).items():
        try:
            result[str(key)] = float(cast(float | int | str | bool, item))
        except (TypeError, ValueError) as exc:
            raise PolicyLoadError(
                f"Invalid float value for {key}",
                bundle_path=str(root),
                field_path=f"{field_path}.{key}",
            ) from exc
    return result


def to_int_map(value: object, root: Path, field_path: str) -> dict[str, int]:
    result: dict[str, int] = {}
    for key, item in optional_mapping(value, root, field_path).items():
        try:
            result[str(key)] = int(cast(float | int | str | bool, item))
        except (TypeError, ValueError) as exc:
            raise PolicyLoadError(
                f"Invalid integer value for {key}",
                bundle_path=str(root),
                field_path=f"{field_path}.{key}",
            ) from exc
    return result


def required_str_tuple(value: object, root: Path, field_path: str) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        raise PolicyLoadError(
            f"Policy field must be a list: {field_path}",
            bundle_path=str(root),
            field_path=field_path,
        )
    return to_tuple(value)


def str_field(payload: Mapping[str, object], key: str, default: str = "") -> str:
    value = payload.get(key, default)
    return str(value if value is not None else default)


def int_field(payload: Mapping[str, object], key: str, default: int) -> int:
    value = payload.get(key, default)
    try:
        return int(cast(float | int | str | bool, value))
    except (TypeError, ValueError):
        return default


def float_field(payload: Mapping[str, object], key: str, default: float) -> float:
    value = payload.get(key, default)
    try:
        return float(cast(float | int | str | bool, value))
    except (TypeError, ValueError):
        return default


def bool_field(payload: Mapping[str, object], key: str, default: bool) -> bool:
    value = payload.get(key, default)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes", "on"}:
            return True
        if normalized in {"false", "0", "no", "off"}:
            return False
    if isinstance(value, (int, float)):
        return bool(value)
    return default
