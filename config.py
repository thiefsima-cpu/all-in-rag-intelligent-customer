"""Compatibility facade for GraphRAG configuration."""

from rag_modules.configuration import (
    ApiConfig,
    DEFAULT_CONFIG,
    GenerationConfig,
    GraphConfig,
    GraphRAGConfig,
    ModelConfig,
    ObservabilityConfig,
    QueryUnderstandingConfig,
    RetrievalConfig,
    StorageConfig,
    get_default_config,
    load_config,
)

__all__ = [
    "ApiConfig",
    "DEFAULT_CONFIG",
    "GenerationConfig",
    "GraphConfig",
    "GraphRAGConfig",
    "ModelConfig",
    "ObservabilityConfig",
    "QueryUnderstandingConfig",
    "RetrievalConfig",
    "StorageConfig",
    "get_default_config",
    "load_config",
]
