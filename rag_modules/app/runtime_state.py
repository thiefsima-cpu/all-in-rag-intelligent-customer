"""Runtime state containers for build-time and serving-time dependencies."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from ..configuration.models import GraphRAGConfig
from ..graph.retrieval import GraphRAGRetrieval
from ..retrieval import HybridRetrievalService
from ..retrieval.runtime_profile import RetrievalRuntimeProfile
from ..routing import RoutingWorkflowProtocol
from ..runtime.artifacts import ArtifactManifest
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


@dataclass
class SharedRuntime:
    """Infrastructure shared by build and serving lifecycles."""

    config: GraphRAGConfig
    neo4j_manager: Neo4jManagerPort
    data_module: GraphDataModulePort | None = None
    index_module: VectorIndexModulePort | None = None

    def has_shared_dependencies(self) -> bool:
        return all([self.neo4j_manager, self.data_module, self.index_module])


@dataclass
class BuildRuntime(SharedRuntime):
    """Offline/runtime artifact preparation surface."""

    knowledge_base_service: KnowledgeBaseService | None = None
    artifact_manifest: ArtifactManifest = field(default_factory=ArtifactManifest)

    def is_initialized(self) -> bool:
        return all(
            [
                self.has_shared_dependencies(),
                self.knowledge_base_service,
            ]
        )

    @property
    def artifacts_ready(self) -> bool:
        return self.artifact_manifest.is_ready


@dataclass
class ServingRuntime(SharedRuntime):
    """Online answering surface assembled from shared infra plus serving modules."""

    query_tracer: QueryTracerPort | None = None
    generation_module: GenerationWorkflowService | None = None
    retrieval_runtime_profile: RetrievalRuntimeProfile | None = None
    query_understanding_service: QueryUnderstandingService | None = None
    traditional_retrieval: HybridRetrievalService | None = None
    graph_rag_retrieval: GraphRAGRetrieval | None = None
    query_router: RoutingWorkflowProtocol | None = None
    answer_workflow: AnswerWorkflow | None = None
    artifact_manifest: ArtifactManifest = field(default_factory=ArtifactManifest)
    retrieval_engines_initialized: bool = False

    def is_initialized(self) -> bool:
        return all(
            [
                self.has_shared_dependencies(),
                self.query_tracer,
                self.generation_module,
                self.retrieval_runtime_profile,
                self.query_understanding_service,
                self.traditional_retrieval,
                self.graph_rag_retrieval,
                self.query_router,
                self.answer_workflow,
            ]
        )

    @property
    def system_ready(self) -> bool:
        return self.retrieval_engines_initialized and self.artifact_manifest.is_ready

    @property
    def generation_service(self) -> GenerationWorkflowService | None:
        return self.generation_module

    @property
    def routing_workflow(self) -> RoutingWorkflowProtocol | None:
        return self.query_router


__all__ = [
    "SharedRuntime",
    "BuildRuntime",
    "ServingRuntime",
]
