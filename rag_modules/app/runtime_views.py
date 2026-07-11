"""Grouped runtime view dataclasses exposed by the application runtime surface."""

from __future__ import annotations

from dataclasses import dataclass

from ..generation.ports import GenerationWorkflowPort
from ..query_understanding.ports import QueryUnderstandingPort
from ..retrieval.runtime_profile import RetrievalRuntimeProfile
from ..routing import RoutingWorkflowProtocol
from .ports import (
    AnswerWorkflowPort,
    GraphDataModulePort,
    KnowledgeBaseServicePort,
    Neo4jManagerPort,
    QueryTracerPort,
    ServingGraphRAGRetrievalPort,
    ServingHybridRetrievalPort,
    VectorIndexModulePort,
)


@dataclass(frozen=True)
class SystemInfrastructureView:
    """Infrastructure-facing runtime dependencies."""

    query_tracer: QueryTracerPort | None = None
    neo4j_manager: Neo4jManagerPort | None = None
    data_module: GraphDataModulePort | None = None
    index_module: VectorIndexModulePort | None = None


@dataclass(frozen=True)
class SystemRetrievalView:
    """Retrieval and routing-facing runtime dependencies."""

    retrieval_runtime_profile: RetrievalRuntimeProfile | None = None
    query_understanding_service: QueryUnderstandingPort | None = None
    traditional_retrieval: ServingHybridRetrievalPort | None = None
    graph_rag_retrieval: ServingGraphRAGRetrievalPort | None = None
    routing_workflow: RoutingWorkflowProtocol | None = None


@dataclass(frozen=True)
class SystemServicesView:
    """Application service-facing runtime dependencies."""

    generation_service: GenerationWorkflowPort | None = None
    answer_workflow: AnswerWorkflowPort | None = None
    knowledge_base_service: KnowledgeBaseServicePort | None = None


__all__ = [
    "SystemInfrastructureView",
    "SystemRetrievalView",
    "SystemServicesView",
]
