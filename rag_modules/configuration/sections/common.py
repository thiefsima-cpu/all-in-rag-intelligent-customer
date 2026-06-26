"""Shared helpers for schema-backed configuration section loaders."""

from __future__ import annotations

from typing import Any, Mapping

from ..assembly import apply_overrides, build_config_from_domain_dict
from ..env import EnvConfigSource, build_env_overrides
from ..models import default_domain_payload


def load_section_from_schema(
    section_name: str,
    source: EnvConfigSource,
    defaults: Mapping[str, Any] | None = None,
) -> Any:
    payload = default_domain_payload()
    if defaults:
        apply_overrides(payload, {section_name: dict(defaults)})
    env_overrides = build_env_overrides(source)
    if env_overrides:
        apply_overrides(payload, env_overrides)
    config = build_config_from_domain_dict(
        payload,
        source_kind="environment",
        source=section_name,
    )
    return getattr(config, section_name)


__all__ = ["load_section_from_schema"]
