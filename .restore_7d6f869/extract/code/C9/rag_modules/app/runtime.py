"""Runtime containers for build-time and serving-time GraphRAG dependencies."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from config import GraphRAGConfig


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
    artifacts_ready: bool = False

    def is_initialized(self) -> bool:
        return all(
            [
                self.has_shared_dependencies(),
                self.knowledge_base_service,
            ]
        )


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
    question_answer_service: Optional[Any] = None
    retrieval_engines_initialized: bool = False
    system_ready: bool = False

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
                self.question_answer_service,
            ]
        )


@dataclass
class SystemRuntime:
    """Compatibility container that exposes split build and serving runtimes."""

    build_runtime: Optional[BuildRuntime] = None
    serving_runtime: Optional[ServingRuntime] = None

    def is_initialized(self) -> bool:
        return bool(
            (self.build_runtime and self.build_runtime.is_initialized())
            or (self.serving_runtime and self.serving_runtime.is_initialized())
        )

    @property
    def config(self) -> Optional[GraphRAGConfig]:
        if self.serving_runtime:
            return self.serving_runtime.config
        if self.build_runtime:
            return self.build_runtime.config
        return None

    @property
    def query_tracer(self) -> Any:
        return self.serving_runtime.query_tracer if self.serving_runtime else None

    @property
    def neo4j_manager(self) -> Any:
        if self.serving_runtime:
            return self.serving_runtime.neo4j_manager
        if self.build_runtime:
            return self.build_runtime.neo4j_manager
        return None

    @property
    def data_module(self) -> Any:
        if self.serving_runtime and self.serving_runtime.data_module:
            return self.serving_runtime.data_module
        if self.build_runtime:
            return self.build_runtime.data_module
        return None

    @property
    def index_module(self) -> Any:
        if self.serving_runtime and self.serving_runtime.index_module:
            return self.serving_runtime.index_module
        if self.build_runtime:
            return self.build_runtime.index_module
        return None

    @property
    def generation_module(self) -> Any:
        return self.serving_runtime.generation_module if self.serving_runtime else None

    @property
    def retrieval_runtime_profile(self) -> Any:
        return self.serving_runtime.retrieval_runtime_profile if self.serving_runtime else None

    @property
    def query_understanding_service(self) -> Any:
        return self.serving_runtime.query_understanding_service if self.serving_runtime else None

    @property
    def traditional_retrieval(self) -> Any:
        return self.serving_runtime.traditional_retrieval if self.serving_runtime else None

    @property
    def graph_rag_retrieval(self) -> Any:
        return self.serving_runtime.graph_rag_retrieval if self.serving_runtime else None

    @property
    def query_router(self) -> Any:
        return self.serving_runtime.query_router if self.serving_runtime else None

    @property
    def knowledge_base_service(self) -> Any:
        return self.build_runtime.knowledge_base_service if self.build_runtime else None

    @property
    def question_answer_service(self) -> Any:
        return self.serving_runtime.question_answer_service if self.serving_runtime else None

    @property
    def artifacts_ready(self) -> bool:
        return bool(self.build_runtime and self.build_runtime.artifacts_ready)

    @property
    def system_ready(self) -> bool:
        return bool(self.serving_runtime and self.serving_runtime.system_ready)
