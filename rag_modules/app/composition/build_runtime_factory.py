"""Build-runtime assembly boundary."""

from __future__ import annotations

from ...configuration.models import GraphRAGConfig
from ..runtime_state import BuildRuntime
from .shared import ProgressCallback, emit_progress, resolve_config


class BuildRuntimeFactory:
    """Assemble build-side dependencies needed for offline artifact creation."""

    def __init__(
        self,
        *,
        provider,
    ) -> None:
        self.provider = provider
        self.infrastructure = provider.infrastructure
        self.build_pipeline = provider.build_pipeline
        self.diagnostics = provider.diagnostics
        self.services = provider.services

    def build(
        self,
        config: GraphRAGConfig | None = None,
        *,
        neo4j_manager=None,
        data_module=None,
        index_module=None,
        progress: ProgressCallback = None,
    ) -> BuildRuntime:
        config = resolve_config(config)
        infrastructure = self.infrastructure
        build_pipeline = self.build_pipeline
        diagnostics = self.diagnostics
        services = self.services

        graph_manager = infrastructure.provide_neo4j_manager(config, neo4j_manager)
        emit_progress(progress, "Initializing graph data module...")
        data_module = infrastructure.provide_data_module(config, graph_manager, data_module)
        emit_progress(progress, "Initializing Milvus vector index module...")
        index_module = infrastructure.provide_index_module(config, index_module)
        manifest_store = infrastructure.provide_artifact_manifest_store(config)
        document_artifact_cache = infrastructure.provide_document_artifact_cache(
            config,
            manifest_store=manifest_store,
        )
        runtime_artifact_access = infrastructure.provide_runtime_artifact_access(config)
        runtime_stats_access = diagnostics.provide_runtime_stats_access(config=config)
        document_artifact_builder = build_pipeline.provide_document_artifact_builder(
            config=config,
            manifest_store=manifest_store,
            cache=document_artifact_cache,
        )
        semantic_graph_schema_sync = build_pipeline.provide_semantic_graph_schema_sync(
            config=config,
            neo4j_manager=graph_manager,
        )
        knowledge_base_service = services.provide_knowledge_base_service(
            config=config,
            neo4j_manager=graph_manager,
            data_module=data_module,
            index_module=index_module,
            manifest_store=manifest_store,
            runtime_artifact_access=runtime_artifact_access,
            runtime_stats_access=runtime_stats_access,
            document_artifact_builder=document_artifact_builder,
            semantic_graph_schema_sync=semantic_graph_schema_sync,
        )
        runtime = BuildRuntime(
            config=config,
            neo4j_manager=graph_manager,
            data_module=data_module,
            index_module=index_module,
            knowledge_base_service=knowledge_base_service,
            artifact_manifest=knowledge_base_service.artifact_manifest,
        )
        emit_progress(progress, "[OK] Build runtime assembled.")
        return runtime


__all__ = ["BuildRuntimeFactory"]
