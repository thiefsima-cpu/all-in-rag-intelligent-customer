"""Configuration package exports."""

from __future__ import annotations

from functools import lru_cache

from .loader import load_config
from .models import (
    ApiSettings,
    GenerationSettings,
    GraphRAGConfig,
    GraphSettings,
    ModelSettings,
    ObservabilitySettings,
    QueryPlannerSettings,
    QuerySemanticAdaptiveTraversalSettings,
    QuerySemanticExtractionSettings,
    QuerySemanticRoutingSettings,
    QuerySemanticScoringSettings,
    QuerySemanticSettings,
    QuerySemanticTraversalSettings,
    QueryUnderstandingSettings,
    RetrievalSettings,
    StorageSettings,
)
from .profiles import ConfigProfile, default_profiles_dir, load_profile


@lru_cache(maxsize=1)
def get_default_config() -> GraphRAGConfig:
    """Build and cache the process-wide default config on first use."""

    return load_config()


def reset_default_config_cache() -> None:
    """Clear the cached default config for tests or controlled reloads."""

    get_default_config.cache_clear()


__all__ = [
    "ApiSettings",
    "ConfigProfile",
    "GenerationSettings",
    "GraphRAGConfig",
    "GraphSettings",
    "ModelSettings",
    "ObservabilitySettings",
    "QueryPlannerSettings",
    "QuerySemanticAdaptiveTraversalSettings",
    "QuerySemanticExtractionSettings",
    "QuerySemanticRoutingSettings",
    "QuerySemanticScoringSettings",
    "QuerySemanticSettings",
    "QuerySemanticTraversalSettings",
    "QueryUnderstandingSettings",
    "RetrievalSettings",
    "StorageSettings",
    "default_profiles_dir",
    "get_default_config",
    "load_config",
    "load_profile",
    "reset_default_config_cache",
]
