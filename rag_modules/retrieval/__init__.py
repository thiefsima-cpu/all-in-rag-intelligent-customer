"""Lazy exports for retrieval submodules."""

from __future__ import annotations

from importlib import import_module
from typing import Dict


_EXPORTS: Dict[str, str] = {
    "BM25Retriever": ".adapters",
    "ConstraintRetriever": ".adapters",
    "DualLevelRetriever": ".dual_level_retriever",
    "EvidenceDocument": ".contracts",
    "ensure_evidence_documents": ".contracts",
    "from_langchain_documents": ".contracts",
    "GraphKVRetriever": ".adapters",
    "HybridIndexArtifacts": ".hybrid_index_service",
    "HybridIndexService": ".hybrid_index_service",
    "HybridLegacyResultTranslator": ".hybrid_facade",
    "HybridRetrievalModule": ".hybrid_facade",
    "QueryKeywordExtractor": ".keyword_service",
    "QueryPlannerRuntimeSettings": ".runtime_profile",
    "QuerySemanticRuntimeSettings": ".runtime_profile",
    "RetrievalResult": ".hybrid_facade",
    "RetrievalCandidateSizingSettings": ".runtime_profile",
    "RetrievalPostProcessSettings": ".runtime_profile",
    "RetrievalRequest": ".contracts",
    "RetrievalRuntimeProfile": ".runtime_profile",
    "to_langchain_documents": ".contracts",
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
