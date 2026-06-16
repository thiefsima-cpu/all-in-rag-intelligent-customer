"""
Top-level package exports for the GraphRAG system.

Keep package initialization lightweight so config and utility modules can import
submodules without triggering the full application bootstrap.
"""

from __future__ import annotations

from importlib import import_module
from typing import Dict

_EXPORTS: Dict[str, str] = {
    "AdvancedGraphRAGSystem": ".app.system",
    "GraphDataPreparationModule": ".build_pipeline.graph_data_preparation",
    "GenerationIntegrationModule": ".generation.integration",
    "GenerationWorkflowService": ".generation.service",
    "HybridRetrievalModule": ".retrieval",
    "KnowledgeBaseService": ".app.services.knowledge_base_service",
    "MilvusIndexConstructionModule": ".infra.milvus_index_construction",
    "QuestionAnswerService": ".app.services.question_answer_service",
}

__all__ = list(_EXPORTS)


def __getattr__(name: str):
    module_name = _EXPORTS.get(name)
    if not module_name:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module = import_module(module_name, __name__)
    return getattr(module, name)


def __dir__():
    return sorted(list(globals().keys()) + list(__all__))
