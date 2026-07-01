"""Configuration assembly helpers."""

from __future__ import annotations

from typing import Any, Dict, Mapping

from pydantic import ValidationError

from .models import GraphRAGConfig
from .validation import raise_validation_error


def _merge_nested_mapping(target: Dict[str, Any], updates: Mapping[str, Any]) -> None:
    for key, value in updates.items():
        key_text = str(key)
        current = target.get(key_text)
        if isinstance(current, dict) and isinstance(value, Mapping):
            _merge_nested_mapping(current, value)
        else:
            target[key_text] = dict(value) if isinstance(value, Mapping) else value


def apply_overrides(domain_payload: Dict[str, Any], overrides: Mapping[str, Any]) -> None:
    _merge_nested_mapping(domain_payload, overrides)


def build_config_from_domain_dict(
    domain_payload: Mapping[str, Any],
    *,
    source_kind: str = "configuration",
    source: str = "",
) -> GraphRAGConfig:
    try:
        return GraphRAGConfig.model_validate(dict(domain_payload))
    except ValidationError as exc:
        raise_validation_error(exc, source_kind=source_kind, source=source)
        raise AssertionError("unreachable") from exc


__all__ = ["apply_overrides", "build_config_from_domain_dict"]
