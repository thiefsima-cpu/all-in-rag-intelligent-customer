"""Provider contracts for runtime assembly."""

from __future__ import annotations

from typing import Any, Protocol

from ...build_pipeline.contracts import (
    DocumentArtifactBuilderPort,
    SemanticGraphSchemaSyncPort,
)
from ...configuration.models import GraphRAGConfig
from ...generation.service import GenerationWorkflowService
from ...graph.retrieval import GraphRAGRetrieval
from ...retrieval import HybridRetrievalModule
from ...query_understanding.service import QueryUnderstandingService
from ...retrieval.runtime_profile import RetrievalRuntimeProfile
from ...routing import RoutingWorkflowProtocol
from ...runtime.artifact_ports import (
    ArtifactManifestStorePort,
    DocumentArtifactCachePort,
    RuntimeArtifactAccessPort,
)
from ...runtime.stats_ports import RuntimeStatsAccessPort
from ...tracing_sinks import QueryTraceSink
from ..services.answer_workflow import AnswerWorkflow
from ..services.knowledge_base_service import KnowledgeBaseService
from ..services import QuestionAnswerService
from ..services.runtime_diagnostics_service import RuntimeDiagnosticsService
from ..services.runtime_shutdown_service import RuntimeShutdownService


class InfrastructureComponentProvider(Protocol):
    """Concrete infrastructure adapters such as graph, vector, and tracing."""

    def provide_neo4j_manager(self, config: GraphRAGConfig, existing: Any = None) -> Any: ...

    def provide_data_module(
        self,
        config: GraphRAGConfig,
        neo4j_manager: Any,
        existing: Any = None,
    ) -> Any: ...

    def provide_index_module(self, config: GraphRAGConfig, existing: Any = None) -> Any: ...

    def provide_query_trace_sink(
        self,
        config: GraphRAGConfig,
        existing: QueryTraceSink | None = None,
    ) -> QueryTraceSink: ...

    def provide_artifact_manifest_store(
        self,
        config: GraphRAGConfig,
        existing: ArtifactManifestStorePort | None = None,
    ) -> ArtifactManifestStorePort: ...

    def provide_document_artifact_cache(
        self,
        config: GraphRAGConfig,
        existing: DocumentArtifactCachePort | None = None,
        *,
        manifest_store: ArtifactManifestStorePort | None = None,
    ) -> DocumentArtifactCachePort: ...

    def provide_runtime_artifact_access(
        self,
        config: GraphRAGConfig,
        existing: RuntimeArtifactAccessPort | None = None,
    ) -> RuntimeArtifactAccessPort: ...

    def provide_query_tracer(
        self,
        config: GraphRAGConfig,
        existing: Any = None,
        *,
        sink: QueryTraceSink | None = None,
    ) -> Any: ...


class GenerationComponentProvider(Protocol):
    """Model-facing runtime components for answer generation only."""

    def provide_generation_module(self, config: GraphRAGConfig) -> GenerationWorkflowService: ...


class DiagnosticsComponentProvider(Protocol):
    """Runtime stats and startup diagnostics providers."""

    def provide_runtime_stats_access(
        self,
        *,
        config: GraphRAGConfig,
        existing: RuntimeStatsAccessPort | None = None,
    ) -> RuntimeStatsAccessPort: ...

    def provide_runtime_diagnostics_service(
        self,
        *,
        config: GraphRAGConfig,
        existing: RuntimeDiagnosticsService | None = None,
        runtime_stats_access: RuntimeStatsAccessPort | None = None,
    ) -> RuntimeDiagnosticsService: ...


class LifecycleComponentProvider(Protocol):
    """Shutdown and teardown providers for runtime lifecycle management."""

    def provide_runtime_shutdown_service(
        self,
        *,
        config: GraphRAGConfig,
        existing: RuntimeShutdownService | None = None,
    ) -> RuntimeShutdownService: ...


class BuildPipelineComponentProvider(Protocol):
    """Build-side artifact materialization and semantic schema sync providers."""

    def provide_document_artifact_builder(
        self,
        *,
        config: GraphRAGConfig,
        existing: DocumentArtifactBuilderPort | None = None,
        manifest_store: ArtifactManifestStorePort | None = None,
        cache: DocumentArtifactCachePort | None = None,
    ) -> DocumentArtifactBuilderPort: ...

    def provide_semantic_graph_schema_sync(
        self,
        *,
        config: GraphRAGConfig,
        neo4j_manager: Any,
        existing: SemanticGraphSchemaSyncPort | None = None,
    ) -> SemanticGraphSchemaSyncPort: ...


class QueryUnderstandingComponentProvider(Protocol):
    """Query-understanding and retrieval-profile assembly boundary."""

    def provide_retrieval_runtime_profile(
        self,
        config: GraphRAGConfig,
    ) -> RetrievalRuntimeProfile: ...

    def provide_query_understanding_service(
        self,
        *,
        config: GraphRAGConfig,
        llm_client: Any,
        retrieval_profile: RetrievalRuntimeProfile,
    ) -> QueryUnderstandingService: ...


class RetrievalComponentProvider(Protocol):
    """Retrieval-specific orchestration components."""

    def provide_traditional_retrieval(
        self,
        *,
        config: GraphRAGConfig,
        milvus_module: Any,
        data_module: Any,
        llm_client: Any,
        neo4j_manager: Any,
        retrieval_profile: RetrievalRuntimeProfile,
    ) -> HybridRetrievalModule: ...

    def provide_graph_rag_retrieval(
        self,
        *,
        config: GraphRAGConfig,
        llm_client: Any,
        neo4j_manager: Any,
        retrieval_profile: RetrievalRuntimeProfile,
    ) -> GraphRAGRetrieval: ...

    def provide_routing_workflow(
        self,
        *,
        config: GraphRAGConfig,
        traditional_retrieval: Any,
        graph_rag_retrieval: Any,
        llm_client: Any,
        retrieval_profile: RetrievalRuntimeProfile,
        query_understanding_service: QueryUnderstandingService,
    ) -> RoutingWorkflowProtocol: ...

    def provide_query_router(
        self,
        *,
        config: GraphRAGConfig,
        traditional_retrieval: Any,
        graph_rag_retrieval: Any,
        llm_client: Any,
        retrieval_profile: RetrievalRuntimeProfile,
        query_understanding_service: QueryUnderstandingService,
    ) -> RoutingWorkflowProtocol: ...


class ApplicationServiceComponentProvider(Protocol):
    """Application-layer use-case services."""

    def provide_knowledge_base_service(
        self,
        *,
        config: GraphRAGConfig,
        neo4j_manager: Any,
        data_module: Any,
        index_module: Any,
        manifest_store: ArtifactManifestStorePort | None = None,
        runtime_artifact_access: RuntimeArtifactAccessPort | None = None,
        runtime_stats_access: RuntimeStatsAccessPort | None = None,
        document_artifact_builder: DocumentArtifactBuilderPort | None = None,
        semantic_graph_schema_sync: SemanticGraphSchemaSyncPort | None = None,
    ) -> KnowledgeBaseService: ...

    def provide_answer_workflow(
        self,
        *,
        config: GraphRAGConfig,
        query_router: Any,
        generation_module: GenerationWorkflowService,
        query_tracer: Any,
    ) -> AnswerWorkflow: ...

    def provide_question_answer_service(
        self,
        *,
        config: GraphRAGConfig,
        query_router: Any,
        generation_module: GenerationWorkflowService,
        query_tracer: Any,
        answer_workflow: AnswerWorkflow,
    ) -> QuestionAnswerService: ...


class RuntimeComponentProvider(Protocol):
    """Composite provider surface assembled from narrower capability providers."""

    infrastructure: InfrastructureComponentProvider
    build_pipeline: BuildPipelineComponentProvider
    diagnostics: DiagnosticsComponentProvider
    lifecycle: LifecycleComponentProvider
    generation: GenerationComponentProvider
    query_understanding: QueryUnderstandingComponentProvider
    retrieval: RetrievalComponentProvider
    services: ApplicationServiceComponentProvider
