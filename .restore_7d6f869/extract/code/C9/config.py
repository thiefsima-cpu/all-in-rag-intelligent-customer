"""Compatibility facade for GraphRAG configuration."""

from rag_modules.configuration import (
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
