"""Knowledge-base lifecycle service."""

from __future__ import annotations

from typing import Callable, Optional

from ...build_pipeline.contracts import DocumentArtifactBuilderPort, SemanticGraphSchemaSyncPort
from ...build_pipeline.knowledge_base_workflow import KnowledgeBaseBuildWorkflow
from ...runtime.artifact_ports import ArtifactManifestStorePort, RuntimeArtifactAccessPort
from ...runtime.artifacts import ArtifactManifest
from ...runtime.stats_ports import RuntimeStatsAccessPort

ProgressCallback = Optional[Callable[[str], None]]


class KnowledgeBaseService:
    """Own the build-side knowledge-base lifecycle and artifact preparation."""

    def __init__(
        self,
        config,
        neo4j_manager,
        data_module,
        index_module,
        traditional_retrieval=None,
        graph_rag_retrieval=None,
        query_router=None,
        manifest_store: ArtifactManifestStorePort | None = None,
        runtime_artifact_access: RuntimeArtifactAccessPort | None = None,
        runtime_stats_access: RuntimeStatsAccessPort | None = None,
        document_artifact_builder: DocumentArtifactBuilderPort | None = None,
        semantic_graph_schema_sync: SemanticGraphSchemaSyncPort | None = None,
    ):
        self.config = config
        self.neo4j_manager = neo4j_manager
        self.data_module = data_module
        self.index_module = index_module
        self.query_router = query_router
        self.workflow = KnowledgeBaseBuildWorkflow(
            config=config,
            neo4j_manager=neo4j_manager,
            data_module=data_module,
            index_module=index_module,
            query_router=query_router,
            manifest_store=manifest_store,
            runtime_artifact_access=runtime_artifact_access,
            runtime_stats_access=runtime_stats_access,
            document_artifact_builder=document_artifact_builder,
            semantic_graph_schema_sync=semantic_graph_schema_sync,
        )

    @property
    def artifacts_ready(self) -> bool:
        return self.workflow.artifacts_ready

    @property
    def system_ready(self) -> bool:
        return self.artifacts_ready

    @property
    def artifact_manifest(self) -> ArtifactManifest:
        return self.workflow.artifact_manifest

    @artifact_manifest.setter
    def artifact_manifest(self, manifest: ArtifactManifest) -> None:
        self.workflow.artifact_manifest = manifest

    def build(self, progress: ProgressCallback = None) -> None:
        self.workflow.build(progress=progress)

    def rebuild(self, progress: ProgressCallback = None) -> None:
        self.workflow.rebuild(progress=progress)

    def show_stats(self, progress: ProgressCallback = None) -> None:
        self.workflow.show_stats(progress)

    def close(self) -> None:
        if self.data_module:
            self.data_module.close()
        if self.index_module:
            self.index_module.close()
        if self.neo4j_manager:
            self.neo4j_manager.close()
