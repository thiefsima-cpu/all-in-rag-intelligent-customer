"""Serving-runtime assembly boundary."""

from __future__ import annotations

from dataclasses import dataclass

from ...configuration.models import GraphRAGConfig
from ...generation.ports import GenerationWorkflowPort
from ...kernel.artifacts import ArtifactManifest
from ...query_policy import resolve_query_policy_bundle
from ...query_policy.models import QueryPolicyBundle
from ...query_understanding.ports import QueryUnderstandingPort
from ...retrieval.runtime_profile import RetrievalRuntimeProfile
from ...routing import RoutingWorkflowProtocol
from ..ports import (
    AnswerWorkflowPort,
    GraphDataModulePort,
    Neo4jManagerPort,
    QueryTracerPort,
    ServingGraphRAGRetrievalPort,
    ServingHybridRetrievalPort,
    VectorIndexModulePort,
)
from ..providers.contracts import RuntimeComponentProvider
from ..runtime_state import BuildRuntime, ServingRuntime
from .shared import (
    ProgressCallback,
    emit_progress,
    resolve_config,
)


@dataclass
class _ServingSharedModules:
    config: GraphRAGConfig
    policy_bundle: QueryPolicyBundle
    graph_manager: Neo4jManagerPort
    data_module: GraphDataModulePort
    index_module: VectorIndexModulePort
    tracer: QueryTracerPort


@dataclass
class _ServingWorkflowModules:
    generation_service: GenerationWorkflowPort
    retrieval_runtime_profile: RetrievalRuntimeProfile
    query_understanding_service: QueryUnderstandingPort
    traditional_retrieval: ServingHybridRetrievalPort
    graph_rag_retrieval: ServingGraphRAGRetrievalPort
    query_router: RoutingWorkflowProtocol
    answer_workflow: AnswerWorkflowPort


class ServingRuntimeFactory:
    """Assemble the serving object graph without loading artifacts into memory."""

    def __init__(
        self,
        *,
        provider: RuntimeComponentProvider,
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
        query_tracer: QueryTracerPort | None = None,
        neo4j_manager: Neo4jManagerPort | None = None,
        data_module: GraphDataModulePort | None = None,
        index_module: VectorIndexModulePort | None = None,
        progress: ProgressCallback = None,
    ) -> ServingRuntime:
        config = resolve_config(config)
        shared = self._resolve_shared_modules(
            config,
            shared_runtime=shared_runtime,
            query_tracer=query_tracer,
            neo4j_manager=neo4j_manager,
            data_module=data_module,
            index_module=index_module,
        )
        workflow = self._resolve_workflow_modules(shared, progress=progress)
        runtime = self._build_runtime(
            shared,
            workflow,
            artifact_manifest=self._artifact_manifest(config, shared_runtime),
        )
        emit_progress(progress, "[OK] Serving runtime assembled.")
        return runtime

    def _resolve_shared_modules(
        self,
        config: GraphRAGConfig,
        *,
        shared_runtime: BuildRuntime | None,
        query_tracer: QueryTracerPort | None,
        neo4j_manager: Neo4jManagerPort | None,
        data_module: GraphDataModulePort | None,
        index_module: VectorIndexModulePort | None,
    ) -> _ServingSharedModules:
        infrastructure = self.infrastructure
        policy_bundle = resolve_query_policy_bundle(config)
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
        return _ServingSharedModules(
            config=config,
            policy_bundle=policy_bundle,
            graph_manager=graph_manager,
            data_module=data_module,
            index_module=index_module,
            tracer=tracer,
        )

    def _resolve_workflow_modules(
        self,
        shared: _ServingSharedModules,
        *,
        progress: ProgressCallback,
    ) -> _ServingWorkflowModules:
        config = shared.config
        retrieval_runtime = self.retrieval_runtime
        emit_progress(progress, "Initializing generation service...")
        generation_service = self.provider.provide_generation_module(
            config,
            policy_bundle=shared.policy_bundle,
        )
        llm_client = generation_service.llm_client
        retrieval_runtime_profile = retrieval_runtime.provide_retrieval_runtime_profile(
            config,
            policy_bundle=shared.policy_bundle,
        )

        emit_progress(progress, "Initializing query understanding service...")
        query_understanding_service = retrieval_runtime.provide_query_understanding_service(
            config=config,
            llm_client=llm_client,
            retrieval_profile=retrieval_runtime_profile,
            policy_bundle=shared.policy_bundle,
        )

        emit_progress(progress, "Initializing hybrid retrieval module...")
        traditional_retrieval = retrieval_runtime.provide_traditional_retrieval(
            config=config,
            milvus_module=shared.index_module,
            data_module=shared.data_module,
            llm_client=llm_client,
            neo4j_manager=shared.graph_manager,
            retrieval_profile=retrieval_runtime_profile,
            policy_bundle=shared.policy_bundle,
        )

        emit_progress(progress, "Initializing graph retrieval module...")
        graph_rag_retrieval = retrieval_runtime.provide_graph_rag_retrieval(
            config=config,
            llm_client=llm_client,
            neo4j_manager=shared.graph_manager,
            retrieval_profile=retrieval_runtime_profile,
            policy_bundle=shared.policy_bundle,
        )

        emit_progress(progress, "Initializing routing workflow...")
        query_router = retrieval_runtime.provide_routing_workflow(
            config=config,
            traditional_retrieval=traditional_retrieval,
            graph_rag_retrieval=graph_rag_retrieval,
            llm_client=llm_client,
            retrieval_profile=retrieval_runtime_profile,
            query_understanding_service=query_understanding_service,
            policy_bundle=shared.policy_bundle,
        )

        answer_workflow = self.services.provide_answer_workflow(
            config=config,
            query_router=query_router,
            generation_module=generation_service,
            query_tracer=shared.tracer,
            retrieval_profile=retrieval_runtime_profile,
            policy_bundle=shared.policy_bundle,
        )
        return _ServingWorkflowModules(
            generation_service=generation_service,
            retrieval_runtime_profile=retrieval_runtime_profile,
            query_understanding_service=query_understanding_service,
            traditional_retrieval=traditional_retrieval,
            graph_rag_retrieval=graph_rag_retrieval,
            query_router=query_router,
            answer_workflow=answer_workflow,
        )

    @staticmethod
    def _artifact_manifest(
        config: GraphRAGConfig,
        shared_runtime: BuildRuntime | None,
    ) -> ArtifactManifest:
        if shared_runtime:
            return shared_runtime.artifact_manifest
        return ArtifactManifest.missing(manifest_path=config.storage.artifact_manifest_path)

    @staticmethod
    def _build_runtime(
        shared: _ServingSharedModules,
        workflow: _ServingWorkflowModules,
        *,
        artifact_manifest: ArtifactManifest,
    ) -> ServingRuntime:
        return ServingRuntime(
            config=shared.config,
            query_tracer=shared.tracer,
            neo4j_manager=shared.graph_manager,
            data_module=shared.data_module,
            index_module=shared.index_module,
            generation_module=workflow.generation_service,
            retrieval_runtime_profile=workflow.retrieval_runtime_profile,
            query_understanding_service=workflow.query_understanding_service,
            traditional_retrieval=workflow.traditional_retrieval,
            graph_rag_retrieval=workflow.graph_rag_retrieval,
            query_router=workflow.query_router,
            answer_workflow=workflow.answer_workflow,
            artifact_manifest=artifact_manifest,
            retrieval_engines_initialized=False,
        )


__all__ = ["ServingRuntimeFactory"]
