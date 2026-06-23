"""Grouped runtime view dataclasses exposed by the application runtime surface."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from ..graph.retrieval import GraphRAGRetrieval
from ..retrieval import HybridRetrievalService
from ..retrieval.runtime_profile import RetrievalRuntimeProfile
from ..routing import RoutingWorkflowProtocol
from .runtime_contracts import (
    GraphDataModulePort,
    Neo4jManagerPort,
    QueryTracerPort,
    VectorIndexModulePort,
)

if TYPE_CHECKING:
    from ..generation.service import GenerationWorkflowService
    from ..query_understanding.service import QueryUnderstandingService
    from .services.answer_workflow import AnswerWorkflow
    from .services.knowledge_base_service import KnowledgeBaseService


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
    query_understanding_service: QueryUnderstandingService | None = None
    traditional_retrieval: HybridRetrievalService | None = None
    graph_rag_retrieval: GraphRAGRetrieval | None = None
    routing_workflow: RoutingWorkflowProtocol | None = None


@dataclass(frozen=True)
class SystemServicesView:
    """Application service-facing runtime dependencies."""

    generation_service: GenerationWorkflowService | None = None
    answer_workflow: AnswerWorkflow | None = None
    knowledge_base_service: KnowledgeBaseService | None = None


__all__ = [
    "SystemInfrastructureView",
    "SystemRetrievalView",
    "SystemServicesView",
]
