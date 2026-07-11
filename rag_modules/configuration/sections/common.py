"""Shared helpers for schema-backed configuration section loaders."""

from __future__ import annotations

from typing import Any, Literal, Mapping, TypeAlias, overload

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
from ..models import (
    ApiSettings,
    GenerationSettings,
    GraphSettings,
    ModelSettings,
    ObservabilitySettings,
    RetrievalSettings,
    StorageSettings,
    default_domain_payload,
)

SectionLoaderName: TypeAlias = Literal[
    "api",
    "generation",
    "graph",
    "models",
    "observability",
    "retrieval",
    "storage",
]
SectionSettings: TypeAlias = (
    ApiSettings
    | GenerationSettings
    | GraphSettings
    | ModelSettings
    | ObservabilitySettings
    | RetrievalSettings
    | StorageSettings
)


@overload
def load_section_from_schema(
    section_name: Literal["api"],
    source: EnvConfigSource,
    defaults: Mapping[str, Any] | None = None,
) -> ApiSettings: ...


@overload
def load_section_from_schema(
    section_name: Literal["generation"],
    source: EnvConfigSource,
    defaults: Mapping[str, Any] | None = None,
) -> GenerationSettings: ...


@overload
def load_section_from_schema(
    section_name: Literal["graph"],
    source: EnvConfigSource,
    defaults: Mapping[str, Any] | None = None,
) -> GraphSettings: ...


@overload
def load_section_from_schema(
    section_name: Literal["models"],
    source: EnvConfigSource,
    defaults: Mapping[str, Any] | None = None,
) -> ModelSettings: ...


@overload
def load_section_from_schema(
    section_name: Literal["observability"],
    source: EnvConfigSource,
    defaults: Mapping[str, Any] | None = None,
) -> ObservabilitySettings: ...


@overload
def load_section_from_schema(
    section_name: Literal["retrieval"],
    source: EnvConfigSource,
    defaults: Mapping[str, Any] | None = None,
) -> RetrievalSettings: ...


@overload
def load_section_from_schema(
    section_name: Literal["storage"],
    source: EnvConfigSource,
    defaults: Mapping[str, Any] | None = None,
) -> StorageSettings: ...


def load_section_from_schema(
    section_name: SectionLoaderName,
    source: EnvConfigSource,
    defaults: Mapping[str, Any] | None = None,
) -> SectionSettings:
    default_overrides: dict[str, Any] = {section_name: dict(defaults)} if defaults else {}
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
    if section_name == "api":
        return config.api
    if section_name == "generation":
        return config.generation
    if section_name == "graph":
        return config.graph
    if section_name == "models":
        return config.models
    if section_name == "observability":
        return config.observability
    if section_name == "retrieval":
        return config.retrieval
    return config.storage


__all__ = ["load_section_from_schema"]
