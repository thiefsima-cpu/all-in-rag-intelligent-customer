"""Provider boundary and default runtime provider for application assembly."""

from __future__ import annotations

from typing import Protocol, cast

from ..build_pipeline.contracts import (
    DocumentArtifactBuilderPort,
    SemanticGraphSchemaSyncPort,
)
from ..build_pipeline.document_artifacts import DocumentArtifactBuildService, DocumentIndexCache
from ..build_pipeline.graph_preparation import GraphDataPreparationModule
from ..build_pipeline.schema_sync import SemanticGraphSchemaSyncService
from ..configuration.models import GraphRAGConfig
from ..generation.service import GenerationWorkflowService
from ..graph.retrieval import GraphRAGRetrieval
from ..infra.milvus import MilvusIndexConstructionModule
from ..infra.neo4j import Neo4jConnectionManager
from ..observability.tracing import QueryTracer
from ..observability.tracing_sinks import (
    JsonlQueryTraceSinkFactory,
    NullQueryTraceSink,
    QueryTraceSink,
    QueryTraceSinkFactory,
)
from ..query_understanding.service import QueryUnderstandingService
from ..retrieval import HybridRetrievalService
from ..retrieval.runtime_profile import RetrievalRuntimeProfile, RetrievalRuntimeProfileFactory
from ..routing import RoutingWorkflowProtocol, RoutingWorkflowService
from ..runtime.artifact_adapters import DefaultRuntimeArtifactAccess
from ..runtime.artifact_ports import (
    ArtifactManifestStorePort,
    DocumentArtifactCachePort,
    RuntimeArtifactAccessPort,
)
from ..runtime.artifacts import ArtifactManifestStore
from ..runtime.stats_adapters import DefaultRuntimeStatsAccess
from ..runtime.stats_ports import RuntimeStatsAccessPort
from .runtime_contracts import (
    GraphDataModulePort,
    LLMClientPort,
    Neo4jDriverPort,
    Neo4jManagerPort,
    QueryTracerPort,
    VectorIndexModulePort,
)
from .services.answer_workflow import AnswerWorkflow
from .services.knowledge_base_service import KnowledgeBaseService
from .services.runtime_diagnostics_service import RuntimeDiagnosticsService
from .services.runtime_shutdown_service import RuntimeShutdownService


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


class _DefaultInfrastructureProvider:
    """Default infrastructure adapters for storage, graph access, and tracing."""

    def __init__(
        self,
        *,
        query_trace_sink_factory: QueryTraceSinkFactory | None = None,
    ) -> None:
        self.query_trace_sink_factory = query_trace_sink_factory

    def provide_neo4j_manager(
        self,
        config: GraphRAGConfig,
        existing: Neo4jManagerPort | None = None,
    ) -> Neo4jManagerPort:
        if existing is not None:
            return existing
        storage = config.storage
        return cast(
            Neo4jManagerPort,
            Neo4jConnectionManager(
                uri=storage.neo4j_uri,
                user=storage.neo4j_user,
                password=storage.neo4j_password,
                database=storage.neo4j_database,
                max_connection_pool_size=storage.neo4j_max_connection_pool_size,
                connection_acquisition_timeout_seconds=(
                    storage.neo4j_connection_acquisition_timeout_seconds
                ),
                max_connection_lifetime_seconds=(storage.neo4j_max_connection_lifetime_seconds),
                connection_timeout_seconds=storage.neo4j_connection_timeout_seconds,
            ),
        )

    def provide_data_module(
        self,
        config: GraphRAGConfig,
        neo4j_manager: Neo4jManagerPort,
        existing: GraphDataModulePort | None = None,
    ) -> GraphDataModulePort:
        if existing is not None:
            return existing
        storage = config.storage
        return GraphDataPreparationModule(
            uri=storage.neo4j_uri,
            user=storage.neo4j_user,
            password=storage.neo4j_password,
            database=storage.neo4j_database,
            driver=cast(Neo4jDriverPort, neo4j_manager.driver),
        )

    def provide_index_module(
        self,
        config: GraphRAGConfig,
        existing: VectorIndexModulePort | None = None,
    ) -> VectorIndexModulePort:
        if existing is not None:
            return existing
        storage = config.storage
        models = config.models
        retrieval = config.retrieval
        return MilvusIndexConstructionModule(
            host=storage.milvus_host,
            port=storage.milvus_port,
            collection_name=storage.milvus_collection_name,
            dimension=storage.milvus_dimension,
            model_name=models.embedding_model,
            api_key=models.api_key,
            embedding_base_url=models.embedding_base_url,
            embedding_batch_size=models.embedding_batch_size,
            embedding_timeout_seconds=models.embedding_timeout_seconds,
            http_pool_connections=models.http_pool_connections,
            http_pool_maxsize=models.http_pool_maxsize,
            circuit_breaker_failure_threshold=(models.circuit_breaker_failure_threshold),
            circuit_breaker_recovery_seconds=(models.circuit_breaker_recovery_seconds),
            vector_search_ef=retrieval.vector_search_ef,
            vector_search_max_k=retrieval.vector_search_max_k,
            blue_green_enabled=bool(getattr(storage, "milvus_blue_green_enabled", True)),
            collection_alias_suffix=str(
                getattr(storage, "milvus_collection_alias_suffix", "__active")
            ),
        )

    def provide_query_trace_sink(
        self,
        config: GraphRAGConfig,
        existing: QueryTraceSink | None = None,
    ) -> QueryTraceSink:
        if existing is not None:
            return existing
        if not config.observability.enable_query_tracing:
            return NullQueryTraceSink()
        factory = self.query_trace_sink_factory or JsonlQueryTraceSinkFactory(
            async_enabled=config.observability.query_trace_async_enabled,
            max_queue_size=config.observability.query_trace_max_queue_size,
        )
        return factory.create(config.observability.query_trace_path)

    def provide_artifact_manifest_store(
        self,
        config: GraphRAGConfig,
        existing: ArtifactManifestStorePort | None = None,
    ) -> ArtifactManifestStorePort:
        if existing is not None:
            return existing
        return ArtifactManifestStore(config)

    def provide_document_artifact_cache(
        self,
        config: GraphRAGConfig,
        existing: DocumentArtifactCachePort | None = None,
        *,
        manifest_store: ArtifactManifestStorePort | None = None,
    ) -> DocumentArtifactCachePort:
        if existing is not None:
            return existing
        return DocumentIndexCache(
            config,
            manifest_store=manifest_store or self.provide_artifact_manifest_store(config),
        )

    def provide_runtime_artifact_access(
        self,
        config: GraphRAGConfig,
        existing: RuntimeArtifactAccessPort | None = None,
    ) -> RuntimeArtifactAccessPort:
        del config
        if existing is not None:
            return existing
        return DefaultRuntimeArtifactAccess()

    def provide_query_tracer(
        self,
        config: GraphRAGConfig,
        existing: QueryTracerPort | None = None,
        *,
        sink: QueryTraceSink | None = None,
    ) -> QueryTracerPort:
        if existing is not None:
            return existing
        return QueryTracer(
            config,
            sink=self.provide_query_trace_sink(config, sink),
        )


class _DefaultBuildPipelineProvider:
    """Default build-pipeline service providers."""

    def provide_document_artifact_builder(
        self,
        *,
        config: GraphRAGConfig,
        existing: DocumentArtifactBuilderPort | None = None,
        manifest_store: ArtifactManifestStorePort | None = None,
        cache: DocumentArtifactCachePort | None = None,
    ) -> DocumentArtifactBuilderPort:
        if existing is not None:
            return existing
        return DocumentArtifactBuildService(
            config,
            cache=cache
            or DocumentIndexCache(
                config,
                manifest_store=manifest_store,
            ),
        )

    def provide_semantic_graph_schema_sync(
        self,
        *,
        config: GraphRAGConfig,
        neo4j_manager: Neo4jManagerPort,
        existing: SemanticGraphSchemaSyncPort | None = None,
    ) -> SemanticGraphSchemaSyncPort:
        if existing is not None:
            return existing
        return SemanticGraphSchemaSyncService(
            config,
            neo4j_manager=neo4j_manager,
        )


class _DefaultRetrievalRuntimeProvider:
    """Default query-understanding, retrieval, and routing providers."""

    def __init__(
        self,
        *,
        profile_factory: RetrievalRuntimeProfileFactory | None = None,
    ) -> None:
        self.profile_factory = profile_factory or RetrievalRuntimeProfileFactory()

    def provide_retrieval_runtime_profile(
        self,
        config: GraphRAGConfig,
    ) -> RetrievalRuntimeProfile:
        return self.profile_factory.build(config)

    def provide_query_understanding_service(
        self,
        *,
        config: GraphRAGConfig,
        llm_client: LLMClientPort,
        retrieval_profile: RetrievalRuntimeProfile,
    ) -> QueryUnderstandingService:
        return QueryUnderstandingService(
            llm_client=llm_client,
            config=config,
            planner_settings=retrieval_profile.planner,
            semantic_settings=retrieval_profile.semantics,
        )

    def provide_traditional_retrieval(
        self,
        *,
        config: GraphRAGConfig,
        milvus_module: VectorIndexModulePort,
        data_module: GraphDataModulePort,
        llm_client: LLMClientPort,
        neo4j_manager: Neo4jManagerPort,
        retrieval_profile: RetrievalRuntimeProfile,
    ) -> HybridRetrievalService:
        return HybridRetrievalService(
            config=config,
            milvus_module=milvus_module,
            data_module=data_module,
            llm_client=llm_client,
            neo4j_manager=neo4j_manager,
            retrieval_profile=retrieval_profile,
        )

    def provide_graph_rag_retrieval(
        self,
        *,
        config: GraphRAGConfig,
        llm_client: LLMClientPort,
        neo4j_manager: Neo4jManagerPort,
        retrieval_profile: RetrievalRuntimeProfile,
    ) -> GraphRAGRetrieval:
        return GraphRAGRetrieval(
            config=config,
            llm_client=llm_client,
            neo4j_manager=neo4j_manager,
            retrieval_profile=retrieval_profile,
        )

    def provide_routing_workflow(
        self,
        *,
        config: GraphRAGConfig,
        traditional_retrieval: HybridRetrievalService,
        graph_rag_retrieval: GraphRAGRetrieval,
        llm_client: LLMClientPort,
        retrieval_profile: RetrievalRuntimeProfile,
        query_understanding_service: QueryUnderstandingService,
    ) -> RoutingWorkflowProtocol:
        return RoutingWorkflowService(
            traditional_retrieval=traditional_retrieval,
            graph_rag_retrieval=graph_rag_retrieval,
            llm_client=llm_client,
            config=config,
            retrieval_profile=retrieval_profile,
            query_understanding_service=query_understanding_service,
        )


class _DefaultApplicationServiceProvider:
    """Default application use-case, diagnostics, and shutdown providers."""

    def provide_runtime_stats_access(
        self,
        *,
        config: GraphRAGConfig,
        existing: RuntimeStatsAccessPort | None = None,
    ) -> RuntimeStatsAccessPort:
        del config
        if existing is not None:
            return existing
        return DefaultRuntimeStatsAccess()

    def provide_runtime_diagnostics_service(
        self,
        *,
        config: GraphRAGConfig,
        existing: RuntimeDiagnosticsService | None = None,
        runtime_stats_access: RuntimeStatsAccessPort | None = None,
    ) -> RuntimeDiagnosticsService:
        if existing is not None:
            return existing
        return RuntimeDiagnosticsService(
            config,
            runtime_stats_access=runtime_stats_access,
        )

    def provide_runtime_shutdown_service(
        self,
        *,
        config: GraphRAGConfig,
        existing: RuntimeShutdownService | None = None,
    ) -> RuntimeShutdownService:
        del config
        if existing is not None:
            return existing
        return RuntimeShutdownService()

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
    ) -> KnowledgeBaseService:
        return KnowledgeBaseService(
            config=config,
            neo4j_manager=neo4j_manager,
            data_module=data_module,
            index_module=index_module,
            manifest_store=manifest_store,
            runtime_artifact_access=runtime_artifact_access,
            runtime_stats_access=runtime_stats_access,
            document_artifact_builder=document_artifact_builder,
            semantic_graph_schema_sync=semantic_graph_schema_sync,
        )

    def provide_answer_workflow(
        self,
        *,
        config: GraphRAGConfig,
        query_router: RoutingWorkflowProtocol,
        generation_module: GenerationWorkflowService,
        query_tracer: QueryTracerPort,
    ) -> AnswerWorkflow:
        return AnswerWorkflow(
            config=config,
            query_router=query_router,
            generation_module=generation_module,
            query_tracer=query_tracer,
        )


class DefaultRuntimeProvider:
    """Default provider used by application composition."""

    def __init__(
        self,
        *,
        infrastructure: InfrastructureProvider | None = None,
        build_pipeline: BuildPipelineProvider | None = None,
        retrieval_runtime: RetrievalRuntimeProvider | None = None,
        services: ApplicationServiceProvider | None = None,
        query_trace_sink_factory: QueryTraceSinkFactory | None = None,
        retrieval_profile_factory: RetrievalRuntimeProfileFactory | None = None,
    ) -> None:
        self.infrastructure = infrastructure or _DefaultInfrastructureProvider(
            query_trace_sink_factory=query_trace_sink_factory,
        )
        self.build_pipeline = build_pipeline or _DefaultBuildPipelineProvider()
        self.retrieval_runtime = retrieval_runtime or _DefaultRetrievalRuntimeProvider(
            profile_factory=retrieval_profile_factory,
        )
        self.services = services or _DefaultApplicationServiceProvider()

    def provide_generation_module(self, config: GraphRAGConfig) -> GenerationWorkflowService:
        return GenerationWorkflowService.from_config(config)

    @property
    def provider(self) -> "DefaultRuntimeProvider":
        return self


def create_default_runtime_provider() -> RuntimeComponentProvider:
    """Create the default runtime provider through the app facade."""

    return DefaultRuntimeProvider()


__all__ = [
    "ApplicationServiceProvider",
    "BuildPipelineProvider",
    "DefaultRuntimeProvider",
    "InfrastructureProvider",
    "RetrievalRuntimeProvider",
    "RuntimeComponentProvider",
    "create_default_runtime_provider",
]
