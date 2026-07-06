"""Build-pipeline modules."""

from .contracts import (
    DocumentArtifactBuilderPort,
    SemanticGraphSchemaSyncPort,
    SemanticGraphSchemaSyncResult,
)
from .document_artifacts import (
    DocumentArtifactBuildService,
    DocumentIndexCache,
    build_or_load_documents,
)
from .graph_preparation import GraphDataPreparationModule, GraphNode, GraphRelation
from .knowledge_base_workflow import KnowledgeBaseBuildWorkflow
from .manifest_lifecycle import KnowledgeBaseManifestLifecycle
from .schema_sync import SemanticGraphSchemaSyncService
from .stats_presenter import KnowledgeBaseStatsPresenter

__all__ = [
    "DocumentArtifactBuildService",
    "DocumentArtifactBuilderPort",
    "DocumentIndexCache",
    "GraphDataPreparationModule",
    "GraphNode",
    "GraphRelation",
    "KnowledgeBaseBuildWorkflow",
    "KnowledgeBaseManifestLifecycle",
    "KnowledgeBaseStatsPresenter",
    "SemanticGraphSchemaSyncPort",
    "SemanticGraphSchemaSyncResult",
    "SemanticGraphSchemaSyncService",
    "build_or_load_documents",
]
