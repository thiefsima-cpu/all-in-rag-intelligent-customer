"""Lazy exports for the graph domain package."""

from __future__ import annotations

from importlib import import_module
from typing import Dict

_EXPORTS: Dict[str, str] = {
    "DefaultGraphRetrievalComponentFactory": ".retrieval_components",
    "EntityKeyValue": ".indexing",
    "GraphCacheStats": ".cache_stats",
    "GraphCacheStatsStore": ".cache_stats",
    "GraphCacheWarmupService": ".cache_warmup",
    "GraphDataPreparationModule": ".data_preparation",
    "GraphDocumentRanker": ".path_ranker",
    "GraphEvidenceBuilder": ".evidence_builder",
    "GraphEvidenceOrchestrator": ".evidence_orchestrator",
    "GraphIndexingModule": ".indexing",
    "GraphNode": ".data_preparation",
    "GraphPath": ".retrieval_types",
    "GraphPlanBuilder": ".retrieval_plan",
    "GraphQuery": ".retrieval_types",
    "GraphQueryExecutor": ".query_executor",
    "GraphQueryFactory": ".query_resolution",
    "GraphQueryIntent": ".query_intent",
    "GraphRAGRetrieval": ".rag_retrieval",
    "GraphRelation": ".data_preparation",
    "GraphReasoningOutcome": ".reasoning_strategy",
    "GraphReasoningStrategy": ".reasoning_strategy",
    "GraphRetrievalComponentFactory": ".retrieval_components",
    "GraphRetrievalComponents": ".retrieval_components",
    "GraphRetrievalExecutor": ".retrieval_executor",
    "GraphRetrievalPlan": ".retrieval_plan",
    "GraphRetrievalPostProcessor": ".retrieval_postprocess",
    "GraphRetrievalRuntime": ".retrieval_runtime",
    "KnowledgeSubgraph": ".retrieval_types",
    "QueryType": ".retrieval_types",
    "RelationKeyValue": ".indexing",
    "SemanticGraphSchemaWriter": ".schema",
    "infer_graph_query_intent": ".query_intent",
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
