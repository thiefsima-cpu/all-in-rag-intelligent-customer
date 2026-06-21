"""Application service providers."""

from __future__ import annotations

from ...build_pipeline.contracts import (
    DocumentArtifactBuilderPort,
    SemanticGraphSchemaSyncPort,
)
from ...configuration.models import GraphRAGConfig
from ...generation.service import GenerationWorkflowService
from ...routing import RoutingWorkflowProtocol
from ...runtime.artifact_ports import (
    ArtifactManifestStorePort,
    RuntimeArtifactAccessPort,
)
from ...runtime.stats_ports import RuntimeStatsAccessPort
from ..runtime_contracts import (
    GraphDataModulePort,
    Neo4jManagerPort,
    QueryTracerPort,
    VectorIndexModulePort,
)
from ..services import QuestionAnswerService
from ..services.answer_workflow import AnswerWorkflow
from ..services.knowledge_base_service import KnowledgeBaseService


class DefaultApplicationServiceComponentProvider:
    """Default application use-case service providers."""

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

    def provide_question_answer_service(
        self,
        *,
        config: GraphRAGConfig,
        query_router: RoutingWorkflowProtocol,
        generation_module: GenerationWorkflowService,
        query_tracer: QueryTracerPort,
        answer_workflow: AnswerWorkflow,
    ) -> QuestionAnswerService:
        return QuestionAnswerService(
            config=config,
            query_router=query_router,
            generation_module=generation_module,
            query_tracer=query_tracer,
            answer_workflow=answer_workflow,
        )
