"""Runtime state containers for build-time and serving-time dependencies."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from ..configuration.models import GraphRAGConfig

from ..artifacts import ArtifactManifest


@dataclass
class SharedRuntime:
    """Infrastructure shared by build and serving lifecycles."""

    config: GraphRAGConfig
    neo4j_manager: Any
    data_module: Optional[Any] = None
    index_module: Optional[Any] = None

    def has_shared_dependencies(self) -> bool:
        return all([self.neo4j_manager, self.data_module, self.index_module])


@dataclass
class BuildRuntime(SharedRuntime):
    """Offline/runtime artifact preparation surface."""

    knowledge_base_service: Optional[Any] = None
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

    query_tracer: Optional[Any] = None
    generation_module: Optional[Any] = None
    retrieval_runtime_profile: Optional[Any] = None
    query_understanding_service: Optional[Any] = None
    traditional_retrieval: Optional[Any] = None
    graph_rag_retrieval: Optional[Any] = None
    query_router: Optional[Any] = None
    answer_workflow: Optional[Any] = None
    question_answer_service: Optional[Any] = None
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
    def generation_service(self) -> Any:
        return self.generation_module

    @property
    def routing_workflow(self) -> Any:
        return self.query_router


__all__ = [
    "SharedRuntime",
    "BuildRuntime",
    "ServingRuntime",
]
