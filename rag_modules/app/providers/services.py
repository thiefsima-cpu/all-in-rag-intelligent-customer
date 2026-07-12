"""Default application service provider implementations."""

from __future__ import annotations

from typing import cast

from ...application.answering.answer_copy import AnswerWorkflowCopy
from ...application.answering.answer_pipeline import AnswerPipelineService
from ...application.answering.answer_result_factory import QuestionAnswerResultFactory
from ...application.answering.answer_trace_assembler import AnswerTraceAssembler
from ...application.answering.answer_workflow import AnswerWorkflow
from ...application.knowledge_base import KnowledgeBaseService
from ...application.ports import (
    AnswerTelemetryPort,
    AnswerWorkflowPort,
    KnowledgeBaseServicePort,
    QueryTracerPort,
)
from ...build_pipeline.contracts import (
    DocumentArtifactBuilderPort,
    SemanticGraphSchemaSyncPort,
)
from ...build_pipeline.knowledge_base_workflow import KnowledgeBaseBuildWorkflow
from ...configuration.models import GraphRAGConfig
from ...generation.ports import GenerationWorkflowPort
from ...query_policy import resolve_query_policy_bundle
from ...query_policy.models import QueryPolicyBundle
from ...retrieval.runtime_profile import RetrievalRuntimeProfile
from ...routing import RoutingWorkflowProtocol
from ...runtime.artifact_ports import ArtifactManifestStorePort, RuntimeArtifactAccessPort
from ...runtime.stats_adapters import DefaultRuntimeStatsAccess
from ...runtime.stats_ports import RuntimeStatsAccessPort
from ...telemetry import get_runtime_telemetry
from ..ports import (
    GraphDataModulePort,
    Neo4jManagerPort,
    RuntimeDiagnosticsServicePort,
    RuntimeShutdownServicePort,
    VectorIndexModulePort,
)
from ..services.runtime_diagnostics_service import RuntimeDiagnosticsService
from ..services.runtime_shutdown_service import RuntimeShutdownService


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
        existing: RuntimeDiagnosticsServicePort | None = None,
        runtime_stats_access: RuntimeStatsAccessPort | None = None,
    ) -> RuntimeDiagnosticsServicePort:
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
        existing: RuntimeShutdownServicePort | None = None,
    ) -> RuntimeShutdownServicePort:
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
    ) -> KnowledgeBaseServicePort:
        workflow = KnowledgeBaseBuildWorkflow(
            config=config,
            neo4j_manager=neo4j_manager,
            data_module=data_module,
            index_module=index_module,
            query_router=None,
            manifest_store=manifest_store,
            runtime_artifact_access=runtime_artifact_access,
            runtime_stats_access=runtime_stats_access,
            document_artifact_builder=document_artifact_builder,
            semantic_graph_schema_sync=semantic_graph_schema_sync,
        )
        return KnowledgeBaseService(
            workflow=workflow,
            closeables=(data_module, index_module, neo4j_manager),
        )

    def provide_answer_workflow(
        self,
        *,
        config: GraphRAGConfig,
        query_router: RoutingWorkflowProtocol,
        generation_module: GenerationWorkflowPort,
        query_tracer: QueryTracerPort,
        retrieval_profile: RetrievalRuntimeProfile,
        policy_bundle: QueryPolicyBundle | None = None,
    ) -> AnswerWorkflowPort:
        policy_bundle = policy_bundle or resolve_query_policy_bundle(config)
        answer_workflow_copy = cast(
            AnswerWorkflowCopy,
            policy_bundle.generation.answer_workflow_copy,
        )
        telemetry = get_runtime_telemetry(config)
        telemetry_port = cast(AnswerTelemetryPort, telemetry)
        pipeline = AnswerPipelineService(
            query_router=query_router,
            generation_service=generation_module,
            semantic_settings=retrieval_profile.semantics,
            top_k=config.retrieval.top_k,
            answer_workflow_copy=answer_workflow_copy,
            telemetry=telemetry_port,
        )
        trace_assembler = AnswerTraceAssembler(
            query_tracer=query_tracer,
            semantic_settings=retrieval_profile.semantics,
        )
        result_factory = QuestionAnswerResultFactory(
            answer_workflow_copy=answer_workflow_copy,
        )
        return AnswerWorkflow(
            pipeline=pipeline,
            trace_assembler=trace_assembler,
            result_factory=result_factory,
            telemetry=telemetry_port,
            generation_latency_budget_seconds=(config.generation.generation_latency_budget_seconds),
        )


__all__ = ["_DefaultApplicationServiceProvider"]
