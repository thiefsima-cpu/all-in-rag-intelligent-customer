"""Configuration package exports."""

from __future__ import annotations

from functools import lru_cache
from typing import Any

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

StorageConfig = StorageSettings
ModelConfig = ModelSettings
RetrievalConfig = RetrievalSettings
QueryUnderstandingConfig = QueryUnderstandingSettings
GenerationConfig = GenerationSettings
GraphConfig = GraphSettings
ObservabilityConfig = ObservabilitySettings
ApiConfig = ApiSettings


@lru_cache(maxsize=1)
def get_default_config() -> GraphRAGConfig:
    """Build and cache the process-wide default config on first use."""

    return load_config()


def reset_default_config_cache() -> None:
    """Clear the cached default config for tests or controlled reloads."""

    get_default_config.cache_clear()


class _DefaultConfigProxy:
    """Compatibility proxy that preserves the old DEFAULT_CONFIG surface lazily."""

    def _resolve(self) -> GraphRAGConfig:
        return get_default_config()

    def __getattr__(self, name: str) -> Any:
        return getattr(self._resolve(), name)

    def __dir__(self) -> list[str]:
        return sorted(set(object.__dir__(self)) | set(dir(self._resolve())))

    def __repr__(self) -> str:
        return repr(self._resolve())

    def to_dict(self) -> dict[str, Any]:
        return self._resolve().to_dict()

    def to_domain_dict(self) -> dict[str, dict[str, Any]]:
        return self._resolve().to_domain_dict()


DEFAULT_CONFIG = _DefaultConfigProxy()

__all__ = [
    "ApiConfig",
    "ApiSettings",
    "DEFAULT_CONFIG",
    "ConfigProfile",
    "GenerationConfig",
    "GenerationSettings",
    "GraphConfig",
    "GraphRAGConfig",
    "GraphSettings",
    "ModelConfig",
    "ModelSettings",
    "ObservabilityConfig",
    "ObservabilitySettings",
    "QueryPlannerSettings",
    "QuerySemanticAdaptiveTraversalSettings",
    "QuerySemanticExtractionSettings",
    "QuerySemanticRoutingSettings",
    "QuerySemanticScoringSettings",
    "QuerySemanticSettings",
    "QuerySemanticTraversalSettings",
    "QueryUnderstandingConfig",
    "QueryUnderstandingSettings",
    "RetrievalConfig",
    "RetrievalSettings",
    "StorageConfig",
    "StorageSettings",
    "default_profiles_dir",
    "get_default_config",
    "load_config",
    "load_profile",
    "reset_default_config_cache",
]
