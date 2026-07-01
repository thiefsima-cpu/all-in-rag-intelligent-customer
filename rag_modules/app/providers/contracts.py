"""Provider protocols consumed by application composition."""

from __future__ import annotations

from typing import Protocol

from ...build_pipeline.contracts import (
    DocumentArtifactBuilderPort,
    SemanticGraphSchemaSyncPort,
)
from ...configuration.models import GraphRAGConfig
from ...generation.service import GenerationWorkflowService
from ...graph.retrieval import GraphRAGRetrieval
from ...observability.tracing_sinks import QueryTraceSink
from ...query_understanding.service import QueryUnderstandingService
from ...retrieval import HybridRetrievalService
from ...retrieval.runtime_profile import RetrievalRuntimeProfile
from ...routing import RoutingWorkflowProtocol
from ...runtime.artifact_ports import (
    ArtifactManifestStorePort,
    DocumentArtifactCachePort,
    RuntimeArtifactAccessPort,
)
from ...runtime.stats_ports import RuntimeStatsAccessPort
from ..runtime_contracts import (
    GraphDataModulePort,
    LLMClientPort,
    Neo4jManagerPort,
    QueryTracerPort,
    VectorIndexModulePort,
)
from ..services.answer_workflow import AnswerWorkflow
from ..services.knowledge_base_service import KnowledgeBaseService
from ..services.runtime_diagnostics_service import RuntimeDiagnosticsService
from ..services.runtime_shutdown_service import RuntimeShutdownService


class InfrastructureProvider(Protocol):
    """Concrete infrastructure adapters such as graph, vector, and tracing."""

    def provide_neo4j_manager(
        self,
        config: GraphRAGConfig,
        existing: Neo4jManagerPort | None = None,
    ) -> Neo4jManagerPort: ...

    def provide_data_module(
        self,
        config: GraphRAGConfig,
        neo4j_manager: Neo4jManagerPort,
        existing: GraphDataModulePort | None = None,
    ) -> GraphDataModulePort: ...

    def provide_index_module(
        self,
        config: GraphRAGConfig,
        existing: VectorIndexModulePort | None = None,
    ) -> VectorIndexModulePort: ...

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
        existing: QueryTracerPort | None = None,
        *,
        sink: QueryTraceSink | None = None,
    ) -> QueryTracerPort: ...


class BuildPipelineProvider(Protocol):
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
        neo4j_manager: Neo4jManagerPort,
        existing: SemanticGraphSchemaSyncPort | None = None,
    ) -> SemanticGraphSchemaSyncPort: ...


class RetrievalRuntimeProvider(Protocol):
    """Query understanding, retrieval, and routing workflow providers."""

    def provide_retrieval_runtime_profile(
        self,
        config: GraphRAGConfig,
    ) -> RetrievalRuntimeProfile: ...

    def provide_query_understanding_service(
        self,
        *,
        config: GraphRAGConfig,
        llm_client: LLMClientPort,
        retrieval_profile: RetrievalRuntimeProfile,
    ) -> QueryUnderstandingService: ...

    def provide_traditional_retrieval(
        self,
        *,
        config: GraphRAGConfig,
        milvus_module: VectorIndexModulePort,
        data_module: GraphDataModulePort,
        llm_client: LLMClientPort,
        neo4j_manager: Neo4jManagerPort,
        retrieval_profile: RetrievalRuntimeProfile,
    ) -> HybridRetrievalService: ...

    def provide_graph_rag_retrieval(
        self,
        *,
        config: GraphRAGConfig,
        llm_client: LLMClientPort,
        neo4j_manager: Neo4jManagerPort,
        retrieval_profile: RetrievalRuntimeProfile,
    ) -> GraphRAGRetrieval: ...

    def provide_routing_workflow(
        self,
        *,
        config: GraphRAGConfig,
        traditional_retrieval: HybridRetrievalService,
        graph_rag_retrieval: GraphRAGRetrieval,
        llm_client: LLMClientPort,
        retrieval_profile: RetrievalRuntimeProfile,
        query_understanding_service: QueryUnderstandingService,
    ) -> RoutingWorkflowProtocol: ...


class ApplicationServiceProvider(Protocol):
    """Application-layer use-case, diagnostics, and shutdown service providers."""

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

    def provide_runtime_shutdown_service(
        self,
        *,
        config: GraphRAGConfig,
        existing: RuntimeShutdownService | None = None,
    ) -> RuntimeShutdownService: ...

    def provide_knowledge_base_service(
        self,
        *,
        config: GraphRAGConfig,
        neo4j_manager: Neo4jManagerPort,
        data_module: GraphDataModulePort,
        index_module: VectorIndexModulePort,
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
        query_router: RoutingWorkflowProtocol,
        generation_module: GenerationWorkflowService,
        query_tracer: QueryTracerPort,
    ) -> AnswerWorkflow: ...


class RuntimeComponentProvider(Protocol):
    """Composite provider surface consumed by app composition."""

    infrastructure: InfrastructureProvider
    build_pipeline: BuildPipelineProvider
    retrieval_runtime: RetrievalRuntimeProvider
    services: ApplicationServiceProvider

    def provide_generation_module(self, config: GraphRAGConfig) -> GenerationWorkflowService: ...


__all__ = [
    "ApplicationServiceProvider",
    "BuildPipelineProvider",
    "InfrastructureProvider",
    "RetrievalRuntimeProvider",
    "RuntimeComponentProvider",
]
