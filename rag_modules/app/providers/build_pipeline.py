"""Default build-pipeline provider implementations."""

from __future__ import annotations

from ...build_pipeline.contracts import (
    DocumentArtifactBuilderPort,
    SemanticGraphSchemaSyncPort,
)
from ...build_pipeline.document_artifacts import DocumentArtifactBuildService, DocumentIndexCache
from ...build_pipeline.schema_sync import SemanticGraphSchemaSyncService
from ...configuration.models import GraphRAGConfig
from ...runtime.artifact_ports import ArtifactManifestStorePort, DocumentArtifactCachePort
from ..runtime_contracts import Neo4jManagerPort


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


__all__ = ["_DefaultBuildPipelineProvider"]
