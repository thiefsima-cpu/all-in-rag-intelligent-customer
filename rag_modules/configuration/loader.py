"""Configuration loading from environment sources."""

from __future__ import annotations

from typing import Any, Mapping

from dotenv import load_dotenv

from .assembly import apply_overrides, build_config_from_domain_dict
from .env import EnvConfigSource, build_env_overrides, default_env_source
from .models import GraphRAGConfig, default_domain_payload
from .profiles import load_profile


def _default_domain_payload() -> dict[str, dict[str, Any]]:
    return default_domain_payload()


def load_config(
    overrides: Mapping[str, Any] | None = None,
    *,
    source: EnvConfigSource | None = None,
    profile: str | None = None,
    profile_path: str | None = None,
    profiles_dir: str | None = None,
) -> GraphRAGConfig:
    if source is None:
        load_dotenv()
        env_source = default_env_source()
    else:
        env_source = source

    domain_payload = _default_domain_payload()
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
    if resolved_profile.overrides:
        apply_overrides(domain_payload, resolved_profile.overrides)
        build_config_from_domain_dict(
            domain_payload,
            source_kind="profile",
            source=resolved_profile.path or resolved_profile.name,
        )

    env_overrides = build_env_overrides(env_source)
    if env_overrides:
        apply_overrides(domain_payload, env_overrides)
        build_config_from_domain_dict(
            domain_payload,
            source_kind="environment",
            source="",
        )

    if overrides:
        apply_overrides(domain_payload, overrides)
        build_config_from_domain_dict(
            domain_payload,
            source_kind="overrides",
            source="load_config",
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
