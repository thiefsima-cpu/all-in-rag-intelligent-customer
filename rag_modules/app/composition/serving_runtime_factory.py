"""Serving-runtime assembly boundary."""

from __future__ import annotations

from ...configuration.models import GraphRAGConfig
from ...runtime.artifacts import ArtifactManifest
from ..runtime_state import BuildRuntime, ServingRuntime
from .shared import (
    ProgressCallback,
    emit_progress,
    resolve_config,
)


class ServingRuntimeFactory:
    """Assemble the serving object graph without loading artifacts into memory."""

    def __init__(
        self,
        *,
        provider,
    ) -> None:
        self.provider = provider
        self.infrastructure = provider.infrastructure
        self.retrieval_runtime = provider.retrieval_runtime
        self.services = provider.services

    def build(
        self,
        config: GraphRAGConfig | None = None,
        *,
        shared_runtime: BuildRuntime | None = None,
        query_tracer=None,
        neo4j_manager=None,
        data_module=None,
        index_module=None,
        progress: ProgressCallback = None,
    ) -> ServingRuntime:
        config = resolve_config(config)
        infrastructure = self.infrastructure
        retrieval_runtime = self.retrieval_runtime
        services = self.services

        graph_manager = infrastructure.provide_neo4j_manager(
            config,
            neo4j_manager or (shared_runtime.neo4j_manager if shared_runtime else None),
        )
        data_module = infrastructure.provide_data_module(
            config,
            graph_manager,
            data_module or (shared_runtime.data_module if shared_runtime else None),
        )
        index_module = infrastructure.provide_index_module(
            config,
            index_module or (shared_runtime.index_module if shared_runtime else None),
        )
        tracer = infrastructure.provide_query_tracer(config, query_tracer)

        emit_progress(progress, "Initializing generation service...")
        generation_service = self.provider.provide_generation_module(config)
        llm_client = getattr(generation_service, "llm_client", generation_service.client)
        retrieval_runtime_profile = retrieval_runtime.provide_retrieval_runtime_profile(config)

        emit_progress(progress, "Initializing query understanding service...")
        query_understanding_service = retrieval_runtime.provide_query_understanding_service(
            config=config,
            llm_client=llm_client,
            retrieval_profile=retrieval_runtime_profile,
        )

        emit_progress(progress, "Initializing hybrid retrieval module...")
        traditional_retrieval = retrieval_runtime.provide_traditional_retrieval(
            config=config,
            milvus_module=index_module,
            data_module=data_module,
            llm_client=llm_client,
            neo4j_manager=graph_manager,
            retrieval_profile=retrieval_runtime_profile,
        )

        emit_progress(progress, "Initializing graph retrieval module...")
        graph_rag_retrieval = retrieval_runtime.provide_graph_rag_retrieval(
            config=config,
            llm_client=llm_client,
            neo4j_manager=graph_manager,
            retrieval_profile=retrieval_runtime_profile,
        )

        emit_progress(progress, "Initializing routing workflow...")
        query_router = retrieval_runtime.provide_routing_workflow(
            config=config,
            traditional_retrieval=traditional_retrieval,
            graph_rag_retrieval=graph_rag_retrieval,
            llm_client=llm_client,
            retrieval_profile=retrieval_runtime_profile,
            query_understanding_service=query_understanding_service,
        )

        answer_workflow = services.provide_answer_workflow(
            config=config,
            query_router=query_router,
            generation_module=generation_service,
            query_tracer=tracer,
        )
        artifact_manifest = (
            shared_runtime.artifact_manifest
            if shared_runtime
            else ArtifactManifest.missing(manifest_path=config.storage.artifact_manifest_path)
        )
        runtime = ServingRuntime(
            config=config,
            query_tracer=tracer,
            neo4j_manager=graph_manager,
            data_module=data_module,
            index_module=index_module,
            generation_module=generation_service,
            retrieval_runtime_profile=retrieval_runtime_profile,
            query_understanding_service=query_understanding_service,
            traditional_retrieval=traditional_retrieval,
            graph_rag_retrieval=graph_rag_retrieval,
            query_router=query_router,
            answer_workflow=answer_workflow,
            artifact_manifest=artifact_manifest,
            retrieval_engines_initialized=False,
        )
        emit_progress(progress, "[OK] Serving runtime assembled.")
        return runtime


__all__ = ["ServingRuntimeFactory"]
