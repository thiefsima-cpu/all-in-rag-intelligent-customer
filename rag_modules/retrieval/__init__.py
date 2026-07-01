"""Lazy exports for retrieval submodules."""

from __future__ import annotations

from importlib import import_module
from typing import Dict

_EXPORTS: Dict[str, str] = {
    "BM25Retriever": ".adapters",
    "ConstraintRetriever": ".adapters",
    "DualLevelRetriever": ".dual_level_retriever",
    "GraphKVRetriever": ".adapters",
    "HybridIndexArtifacts": ".hybrid_index_service",
    "HybridIndexService": ".hybrid_index_service",
    "HybridRetrievalOutcome": ".hybrid_outcome",
    "HybridRetrievalService": ".hybrid_service",
    "QueryKeywordExtractor": ".keyword_service",
    "RetrievalCandidateSizingSettings": ".runtime_profile",
    "RetrievalPostProcessSettings": ".runtime_profile",
    "RetrievalRuntimeProfile": ".runtime_profile",
    "VectorRetriever": ".adapters",
    "tokenize_chinese": ".adapters",
}

__all__ = list(_EXPORTS)


def __getattr__(name: str):
    module_name = _EXPORTS.get(name)
    if not module_name:
        raise AttributeError(name)
    module = import_module(module_name, __name__)
    return getattr(module, name)


def __dir__():
    return sorted(list(globals().keys()) + list(__all__))
