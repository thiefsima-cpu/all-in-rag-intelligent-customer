"""Configuration loading from environment sources."""

from __future__ import annotations

from typing import Any, Mapping

from dotenv import load_dotenv

from .assembly import apply_overrides
from .env import EnvConfigSource, default_env_source
from .models import GraphRAGConfig
from .profiles import load_profile
from .query_understanding_loader import load_query_understanding_settings
from .section_loaders import (
    load_api_settings,
    load_generation_settings,
    load_graph_settings,
    load_model_settings,
    load_observability_settings,
    load_retrieval_settings,
    load_storage_settings,
)


def _load_domain_payload(
    source: EnvConfigSource,
    *,
    defaults: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, dict[str, Any]]:
    section_defaults = dict(defaults or {})
    return {
        "storage": load_storage_settings(source, section_defaults.get("storage")).to_dict(),
        "models": load_model_settings(source, section_defaults.get("models")).to_dict(),
        "retrieval": load_retrieval_settings(source, section_defaults.get("retrieval")).to_dict(),
        "query_understanding": load_query_understanding_settings(
            source,
            section_defaults.get("query_understanding"),
        ).to_dict(),
        "generation": load_generation_settings(
            source, section_defaults.get("generation")
        ).to_dict(),
        "graph": load_graph_settings(source, section_defaults.get("graph")).to_dict(),
        "observability": load_observability_settings(
            source,
            section_defaults.get("observability"),
        ).to_dict(),
        "api": load_api_settings(source, section_defaults.get("api")).to_dict(),
    }


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

    default_source = EnvConfigSource(environ={})
    domain_payload = _load_domain_payload(default_source)
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

    config = GraphRAGConfig(
        storage=load_storage_settings(env_source, domain_payload.get("storage")),
        models=load_model_settings(env_source, domain_payload.get("models")),
        retrieval=load_retrieval_settings(env_source, domain_payload.get("retrieval")),
        query_understanding=load_query_understanding_settings(
            env_source,
            domain_payload.get("query_understanding"),
        ),
        generation=load_generation_settings(env_source, domain_payload.get("generation")),
        graph=load_graph_settings(env_source, domain_payload.get("graph")),
        observability=load_observability_settings(
            env_source,
            domain_payload.get("observability"),
        ),
        api=load_api_settings(
            env_source,
            domain_payload.get("api"),
        ),
        profile_name=resolved_profile.name,
        profile_path=resolved_profile.path,
        profile_hash=resolved_profile.profile_hash,
    )
    if overrides:
        return config.with_overrides(overrides)
    return config


__all__ = ["load_config"]
