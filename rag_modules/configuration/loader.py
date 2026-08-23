"""Configuration loading from environment sources."""

from __future__ import annotations

from collections.abc import Mapping

from dotenv import load_dotenv

from ..domains import get_domain_pack
from ..query_policy.selector import (
    resolve_query_policy_bundle_from_selector,
    resolve_query_policy_selector,
)
from .assembly import (
    build_config_from_domain_dict,
    merge_overrides,
    policy_resolved_domain_payload,
)
from .env import EnvConfigSource, build_env_overrides, default_env_source
from .models import GraphRAGConfig, default_domain_payload
from .profiles import load_profile
from .validation import validate_query_policy_selector_payload


def _align_domain_pack_storage(
    domain_payload: dict[str, object],
    *,
    layer: Mapping[str, object] | None = None,
) -> None:
    domain_layer = (layer or {}).get("domain")
    if layer is not None and not (isinstance(domain_layer, Mapping) and "name" in domain_layer):
        return
    storage_layer = (layer or {}).get("storage")
    if isinstance(storage_layer, Mapping) and "milvus_collection_name" in storage_layer:
        return
    domain_section = domain_payload.get("domain")
    domain_name = (
        domain_section.get("name") if isinstance(domain_section, dict) else "customer_service"
    )
    if not isinstance(domain_name, str):
        return
    storage_section = domain_payload.get("storage")
    if not isinstance(storage_section, dict):
        storage_section = {}
        domain_payload["storage"] = storage_section
    storage_section["milvus_collection_name"] = get_domain_pack(domain_name).vector_collection_name


def _validate_selector_layer(
    layer: Mapping[str, object] | None,
    *,
    source_kind: str,
    source: str,
) -> None:
    if layer:
        validate_query_policy_selector_payload(layer, source_kind=source_kind, source=source)


def load_config(
    overrides: Mapping[str, object] | None = None,
    *,
    source: EnvConfigSource | None = None,
    profile: str | None = None,
    profile_path: str | None = None,
    profiles_dir: str | None = None,
    _overrides_source: str = "load_config",
) -> GraphRAGConfig:
    if source is None:
        load_dotenv()
        env_source = default_env_source()
    else:
        env_source = source

    base_domain_payload = default_domain_payload()
    resolved_profile = load_profile(
        profile=profile or env_source.get_first("GRAPH_RAG_PROFILE"),
        profile_path=profile_path or env_source.get_first("GRAPH_RAG_PROFILE_PATH"),
        profiles_dir=profiles_dir or env_source.get_first("GRAPH_RAG_PROFILES_DIR"),
    )
    _validate_selector_layer(
        resolved_profile.overrides,
        source_kind="profile",
        source=resolved_profile.path or resolved_profile.name,
    )
    env_overrides = build_env_overrides(env_source)
    _validate_selector_layer(env_overrides, source_kind="environment", source="")
    _validate_selector_layer(
        overrides,
        source_kind="overrides",
        source=_overrides_source,
    )
    selector = resolve_query_policy_selector(
        base_domain_payload,
        resolved_profile.overrides or {},
        env_source,
        overrides,
    )
    bundle = resolve_query_policy_bundle_from_selector(selector)
    domain_payload = policy_resolved_domain_payload(bundle)
    _align_domain_pack_storage(domain_payload)
    if resolved_profile.overrides:
        merge_overrides(domain_payload, resolved_profile.overrides)
        build_config_from_domain_dict(
            domain_payload,
            source_kind="profile",
            source=resolved_profile.path or resolved_profile.name,
        )
        _align_domain_pack_storage(domain_payload, layer=resolved_profile.overrides)

    if env_overrides:
        merge_overrides(domain_payload, env_overrides)
        build_config_from_domain_dict(
            domain_payload,
            source_kind="environment",
            source="",
        )
        _align_domain_pack_storage(domain_payload, layer=env_overrides)

    if overrides:
        merge_overrides(domain_payload, overrides)
        build_config_from_domain_dict(
            domain_payload,
            source_kind="overrides",
            source=_overrides_source,
        )
        _align_domain_pack_storage(domain_payload, layer=overrides)

    config = build_config_from_domain_dict(
        domain_payload,
        source_kind="configuration",
        source=resolved_profile.path or "runtime",
    )
    config.profile_name = resolved_profile.name
    config.profile_path = resolved_profile.path
    config.profile_hash = resolved_profile.profile_hash
    return config


__all__ = ["load_config"]
