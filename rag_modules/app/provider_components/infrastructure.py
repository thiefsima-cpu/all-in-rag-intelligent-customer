"""Infrastructure component providers."""

from __future__ import annotations

from typing import Any, cast

from ...build_pipeline.document_artifacts import DocumentIndexCache
from ...build_pipeline.graph_preparation import GraphDataPreparationModule
from ...configuration.models import GraphRAGConfig
from ...infra.milvus import MilvusIndexConstructionModule
from ...neo4j_pool import Neo4jConnectionManager
from ...observability.tracing import QueryTracer
from ...observability.tracing_sinks import (
    JsonlQueryTraceSinkFactory,
    NullQueryTraceSink,
    QueryTraceSink,
    QueryTraceSinkFactory,
)
from ...runtime.artifact_adapters import DefaultRuntimeArtifactAccess
from ...runtime.artifact_ports import (
    ArtifactManifestStorePort,
    DocumentArtifactCachePort,
    RuntimeArtifactAccessPort,
)
from ...runtime.artifacts import ArtifactManifestStore
from ..runtime_contracts import (
    GraphDataModulePort,
    Neo4jManagerPort,
    QueryTracerPort,
    VectorIndexModulePort,
)


class DefaultInfrastructureComponentProvider:
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
            driver=cast(Any, neo4j_manager.driver),
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
