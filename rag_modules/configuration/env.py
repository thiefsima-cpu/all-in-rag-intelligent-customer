"""Environment-backed configuration helpers."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, Dict, List, Mapping

from .env_specs import ENV_FIELD_SPECS as _ENV_FIELD_SPEC_GROUPS
from .env_specs.base import EnvFieldSpec, EnvValueKind
from .validation import raise_parser_error

_TRUE_TOKENS = {"1", "true", "yes", "y", "on"}
_FALSE_TOKENS = {"0", "false", "no", "n", "off"}


@dataclass(slots=True)
class EnvConfigSource:
    """Typed access helpers over environment variables."""

    environ: Mapping[str, str | None]

    def get_str(self, name: str, default: str = "") -> str:
        value = self.environ.get(name)
        return str(value) if value not in (None, "") else default

    def get_int(self, name: str, default: int) -> int:
        value = self.environ.get(name)
        if value in (None, ""):
            return default
        return int(str(value))

    def get_float(self, name: str, default: float) -> float:
        value = self.environ.get(name)
        if value in (None, ""):
            return default
        return float(str(value))

    def get_bool(self, name: str, default: bool) -> bool:
        value = self.environ.get(name)
        if value in (None, ""):
            return default
        return str(value).strip().lower() in _TRUE_TOKENS

    def get_first_with_name(self, *names: str) -> tuple[str, str] | None:
        for name in names:
            value = self.environ.get(name)
            if value not in (None, ""):
                return name, str(value)
        return None

    def get_first(self, *names: str) -> str | None:
        found = self.get_first_with_name(*names)
        return found[1] if found is not None else None

    def get_int_alias(self, *names: str, default: int) -> int:
        value = self.get_first(*names)
        return int(value) if value is not None else default

    def get_float_alias(self, *names: str, default: float) -> float:
        value = self.get_first(*names)
        return float(value) if value is not None else default

    def get_json_dict(self, name: str, default: Dict[str, List[str]]) -> Dict[str, List[str]]:
        value = self.environ.get(name)
        if value in (None, ""):
            return {key: list(items) for key, items in default.items()}
        try:
            parsed = json.loads(str(value))
        except json.JSONDecodeError:
            return {key: list(items) for key, items in default.items()}
        if not isinstance(parsed, dict):
            return {key: list(items) for key, items in default.items()}

        normalized: Dict[str, List[str]] = {}
        for key, items in parsed.items():
            if isinstance(items, list):
                normalized[str(key)] = [str(item).strip() for item in items if str(item).strip()]
        return normalized or {key: list(items) for key, items in default.items()}


ENV_FIELD_SPECS: dict[str, EnvFieldSpec] = {
    name: spec for spec in _ENV_FIELD_SPEC_GROUPS for name in spec.names
}


def _parse_bool(value: str, source: str, path: str) -> bool:
    normalized = value.strip().lower()
    if normalized in _TRUE_TOKENS:
        return True
    if normalized in _FALSE_TOKENS:
        return False
    raise_parser_error(
        source_kind="environment",
        source=source,
        path=path,
        message="expected boolean",
    )


def _parse_int(value: str, source: str, path: str) -> int:
    try:
        return int(value)
    except ValueError as exc:
        raise_parser_error(
            source_kind="environment",
            source=source,
            path=path,
            message="expected integer",
        )
        raise AssertionError("unreachable") from exc


def _parse_float(value: str, source: str, path: str) -> float:
    try:
        return float(value)
    except ValueError as exc:
        raise_parser_error(
            source_kind="environment",
            source=source,
            path=path,
            message="expected number",
        )
        raise AssertionError("unreachable") from exc


def _parse_json_dict(value: str, source: str, path: str) -> dict[str, list[str]]:
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise_parser_error(
            source_kind="environment",
            source=source,
            path=path,
            message="expected JSON object",
        )
        raise AssertionError("unreachable") from exc

    if not isinstance(parsed, dict):
        raise_parser_error(
            source_kind="environment",
            source=source,
            path=path,
            message="expected JSON object",
        )

    normalized: dict[str, list[str]] = {}
    for key, items in parsed.items():
        if not isinstance(key, str) or not isinstance(items, list):
            raise_parser_error(
                source_kind="environment",
                source=source,
                path=path,
                message="expected JSON object with string keys and string-list values",
            )
        if not all(isinstance(item, str) for item in items):
            raise_parser_error(
                source_kind="environment",
                source=source,
                path=path,
                message="expected JSON object with string keys and string-list values",
            )
        normalized[key] = list(items)
    return normalized


def _parse_value(spec: EnvFieldSpec, source: str, value: str) -> Any:
    path = spec.dotted_path
    if spec.value_kind == "str":
        return value
    if spec.value_kind == "int":
        return _parse_int(value, source, path)
    if spec.value_kind == "float":
        return _parse_float(value, source, path)
    if spec.value_kind == "bool":
        return _parse_bool(value, source, path)
    return _parse_json_dict(value, source, path)


def _assign_path(payload: dict[str, Any], path: tuple[str, ...], value: Any) -> None:
    target = payload
    for part in path[:-1]:
        next_value = target.setdefault(part, {})
        if not isinstance(next_value, dict):
            next_value = {}
            target[part] = next_value
        target = next_value
    target[path[-1]] = value


def build_env_overrides(
    source: EnvConfigSource,
    *,
    section_name: str | None = None,
) -> dict[str, Any]:
    """Build strict nested configuration overrides from supported environment variables."""

    payload: dict[str, Any] = {}
    seen_specs: set[EnvFieldSpec] = set()
    for spec in ENV_FIELD_SPECS.values():
        if section_name is not None and spec.path[:1] != (section_name,):
            continue
        if spec in seen_specs:
            continue
        seen_specs.add(spec)
        found = source.get_first_with_name(*spec.names)
        if found is None:
            continue
        env_name, raw_value = found
        _assign_path(payload, spec.path, _parse_value(spec, env_name, raw_value))
    return payload


def default_env_source() -> EnvConfigSource:
    return EnvConfigSource(environ=os.environ)


__all__ = [
    "ENV_FIELD_SPECS",
    "EnvConfigSource",
    "EnvFieldSpec",
    "EnvValueKind",
    "build_env_overrides",
    "default_env_source",
]
