"""Configuration loading from environment sources."""

from __future__ import annotations

from typing import Any, Mapping

from dotenv import load_dotenv

from ..domains import get_domain_pack
from ..query_policy.selector import (
    resolve_query_policy_bundle_from_selector,
    resolve_query_policy_selector,
)
from .assembly import (
    apply_overrides,
    build_config_from_domain_dict,
    policy_resolved_domain_payload,
)
from .env import EnvConfigSource, build_env_overrides, default_env_source
from .models import GraphRAGConfig, default_domain_payload
from .profiles import load_profile


def _default_domain_payload() -> dict[str, dict[str, Any]]:
    return default_domain_payload()


def _align_domain_pack_storage(
    domain_payload: dict[str, dict[str, Any]],
    *,
    layer: Mapping[str, Any] | None = None,
) -> None:
    domain_layer = (layer or {}).get("domain")
    if layer is not None and not (isinstance(domain_layer, Mapping) and "name" in domain_layer):
        return
    storage_layer = (layer or {}).get("storage")
    if isinstance(storage_layer, Mapping) and "milvus_collection_name" in storage_layer:
        return
    domain_name = str(domain_payload.get("domain", {}).get("name") or "recipe")
    domain_payload.setdefault("storage", {})["milvus_collection_name"] = get_domain_pack(
        domain_name
    ).vector_collection_name


def load_config(
    overrides: Mapping[str, Any] | None = None,
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

    base_domain_payload = _default_domain_payload()
    resolved_profile = load_profile(
        profile=profile or env_source.get_first("GRAPH_RAG_PROFILE", "CONFIG_PROFILE"),
        profile_path=profile_path
        or env_source.get_first(
            "GRAPH_RAG_PROFILE_PATH",
            "CONFIG_PROFILE_PATH",
        ),
        profiles_dir=profiles_dir
        or env_source.get_first(
            "GRAPH_RAG_PROFILES_DIR",
            "CONFIG_PROFILES_DIR",
        ),
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
        apply_overrides(domain_payload, resolved_profile.overrides)
        _align_domain_pack_storage(
            domain_payload,
            layer=resolved_profile.overrides,
        )
        build_config_from_domain_dict(
            domain_payload,
            source_kind="profile",
            source=resolved_profile.path or resolved_profile.name,
        )

    env_overrides = build_env_overrides(env_source)
    if env_overrides:
        apply_overrides(domain_payload, env_overrides)
        _align_domain_pack_storage(domain_payload, layer=env_overrides)
        build_config_from_domain_dict(
            domain_payload,
            source_kind="environment",
            source="",
        )

    if overrides:
        apply_overrides(domain_payload, overrides)
        _align_domain_pack_storage(domain_payload, layer=overrides)
        build_config_from_domain_dict(
            domain_payload,
            source_kind="overrides",
            source=_overrides_source,
        )

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
