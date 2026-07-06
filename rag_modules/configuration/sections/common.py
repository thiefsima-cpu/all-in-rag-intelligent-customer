"""Shared helpers for schema-backed configuration section loaders."""

from __future__ import annotations

from typing import Any, Mapping

from ...query_policy.selector import (
    resolve_query_policy_bundle_from_selector,
    resolve_query_policy_selector,
)
from ..assembly import (
    apply_overrides,
    build_config_from_domain_dict,
    policy_resolved_domain_payload,
)
from ..env import EnvConfigSource, build_env_overrides
from ..models import default_domain_payload


def load_section_from_schema(
    section_name: str,
    source: EnvConfigSource,
    defaults: Mapping[str, Any] | None = None,
) -> Any:
    default_overrides = {section_name: dict(defaults)} if defaults else {}
    selector = resolve_query_policy_selector(default_domain_payload(), default_overrides, source)
    bundle = resolve_query_policy_bundle_from_selector(selector)
    payload = policy_resolved_domain_payload(bundle)
    if defaults:
        apply_overrides(payload, default_overrides)
    env_overrides = build_env_overrides(source, section_name=section_name)
    if env_overrides:
        apply_overrides(payload, env_overrides)
    config = build_config_from_domain_dict(
        payload,
        source_kind="environment",
        source=section_name,
    )
    return getattr(config, section_name)


__all__ = ["load_section_from_schema"]
