"""Offline knowledge-base build workflow."""

from __future__ import annotations

import logging

from ..runtime.artifact_adapters import DefaultRuntimeArtifactAccess
from ..runtime.artifact_ports import ArtifactManifestStorePort, RuntimeArtifactAccessPort
from ..runtime.artifacts import ARTIFACT_STAGE_REBUILDING, ArtifactManifest, ArtifactManifestStore
from ..runtime.stats_adapters import DefaultRuntimeStatsAccess
from ..runtime.stats_ports import RuntimeStatsAccessPort
from ..safe_logging import log_failure
from .contracts import (
    DocumentArtifactBuilderPort,
    SemanticGraphSchemaSyncPort,
)
from .document_artifacts import DocumentArtifactBuildService
from .manifest_lifecycle import KnowledgeBaseManifestLifecycle
from .schema_sync import SemanticGraphSchemaSyncService
from .stats_presenter import KnowledgeBaseStatsPresenter, ProgressCallback
from .vector_publish import _KnowledgeBaseVectorPublishMixin
from .vector_reuse import _KnowledgeBaseVectorReuseMixin
from .workflow_schema_sync import _KnowledgeBaseSchemaSyncMixin

logger = logging.getLogger(__name__)


class KnowledgeBaseBuildWorkflow(
    _KnowledgeBaseSchemaSyncMixin,
    _KnowledgeBaseVectorPublishMixin,
    _KnowledgeBaseVectorReuseMixin,
):
    """Execute build and rebuild flows over build-runtime collaborators."""

    def __init__(
        self,
        *,
        config,
        neo4j_manager,
        data_module,
        index_module,
        query_router=None,
        manifest_store: ArtifactManifestStorePort | None = None,
        runtime_artifact_access: RuntimeArtifactAccessPort | None = None,
        runtime_stats_access: RuntimeStatsAccessPort | None = None,
        document_artifact_builder: DocumentArtifactBuilderPort | None = None,
        semantic_graph_schema_sync: SemanticGraphSchemaSyncPort | None = None,
    ) -> None:
        self.config = config
        self.neo4j_manager = neo4j_manager
        self.data_module = data_module
        self.index_module = index_module
        self.query_router = query_router
        self.manifest_store = manifest_store or ArtifactManifestStore(config)
        self.runtime_artifact_access = runtime_artifact_access or DefaultRuntimeArtifactAccess()
        self.runtime_stats_access = runtime_stats_access or DefaultRuntimeStatsAccess()
        self.document_artifact_builder = document_artifact_builder or DocumentArtifactBuildService(
            config
        )
        self.semantic_graph_schema_sync = (
            semantic_graph_schema_sync
            or SemanticGraphSchemaSyncService(config, neo4j_manager=neo4j_manager)
        )
        self.manifest_lifecycle = KnowledgeBaseManifestLifecycle(self.manifest_store)
        self.stats_presenter = KnowledgeBaseStatsPresenter(
            runtime_stats_access=self.runtime_stats_access,
            data_module=self.data_module,
            index_module=self.index_module,
            query_router=self.query_router,
        )

    @property
    def artifacts_ready(self) -> bool:
        return self.artifact_manifest.is_ready

    @property
    def system_ready(self) -> bool:
        return self.artifacts_ready

    @property
    def artifact_manifest(self) -> ArtifactManifest:
        return self.manifest_lifecycle.artifact_manifest

    @artifact_manifest.setter
    def artifact_manifest(self, manifest: ArtifactManifest) -> None:
        self.manifest_lifecycle.artifact_manifest = manifest

    def build(
        self,
        progress: ProgressCallback = None,
        *,
        force_rebuild: bool = False,
    ) -> ArtifactManifest:
        self._emit(progress, "\nChecking knowledge base state...")
        active_manifest = self.artifact_manifest
        build_target: dict[str, str] = {}
        publish_rollback_target = ""
        published = False
        self._configure_active_collection(active_manifest)
        try:
            if not force_rebuild and self.runtime_artifact_access.has_vector_collection(
                self.index_module
            ):
                self._emit(
                    progress,
                    "[OK] Existing vector collection found. Checking artifact signatures...",
                )
                self._emit(progress, "Loading graph data...")
                self.runtime_artifact_access.load_graph_data(self.data_module)
                self._emit(progress, "Loading or building documents and chunks...")
                document_result = self.document_artifact_builder.build_or_load(self.data_module)
                if self._can_reuse_existing_vector_collection(
                    document_result.manifest,
                    progress=progress,
                ):
                    self._emit(
                        progress,
                        "[OK] Existing vector collection matches current artifacts. Attempting load...",
                    )
                    if self.runtime_artifact_access.load_vector_collection(self.index_module):
                        self._emit(progress, "[OK] Knowledge base loaded successfully.")
                        schema_sync_result = self._sync_semantic_graph_schema(progress)
                        self.manifest_lifecycle.mark_ready(
                            self._reuse_manifest(
                                document_result.manifest,
                                active_manifest=active_manifest,
                            ),
                            vector_rows=self.stats_presenter.vector_row_count(),
                            build_metadata=self._build_metadata(
                                document_result, schema_sync_result
                            ),
                            index_version=active_manifest.index_version,
                        )
                        return self.artifact_manifest
                    self._emit(
                        progress, "[WARN] Existing knowledge base load failed. Rebuilding..."
                    )
                else:
                    self._emit(
                        progress,
                        "[WARN] Existing vector collection is stale for current artifacts. Rebuilding...",
                    )

            self._emit(
                progress, "No usable vector collection found. Building a new knowledge base..."
            )
            self._emit(progress, "Loading graph data from Neo4j...")
            self.runtime_artifact_access.load_graph_data(self.data_module)
            self._emit(progress, "Building documents and chunks...")
            document_result = self.document_artifact_builder.build_or_load(self.data_module)
            chunks = document_result.chunks
            schema_sync_result = self._sync_semantic_graph_schema(progress)
            build_target = self._prepare_vector_build(active_manifest)
            candidate_manifest = document_result.manifest.evolve(
                collection_name=build_target["collection_name"],
                collection_base_name=build_target["collection_base_name"],
                collection_slot=build_target["collection_slot"],
                previous_collection_name=(
                    active_manifest.collection_name if active_manifest.is_ready else ""
                ),
            )
            self.manifest_lifecycle.mark_building(candidate_manifest)
            self._emit(progress, "Building Milvus vector index...")
            if not self._build_vector_index(
                chunks,
                collection_name=build_target["collection_name"],
            ):
                raise RuntimeError("Vector index build failed")
            publish_rollback_target = self._publish_vector_index(build_target["collection_name"])
            published = True
            self.manifest_lifecycle.mark_ready(
                candidate_manifest,
                vector_rows=self.stats_presenter.vector_row_count(),
                build_metadata=self._build_metadata(document_result, schema_sync_result),
            )
            self.stats_presenter.show(progress)
            self._emit(progress, "[OK] Knowledge base build completed.")
            return self.artifact_manifest
        except Exception as exc:
            if published:
                self._rollback_vector_publish(publish_rollback_target)
            if build_target:
                self._discard_vector_build(build_target["collection_name"])
            self._configure_active_collection(active_manifest)
            self.manifest_lifecycle.mark_failed(exc)
            log_failure(
                logger,
                logging.ERROR,
                "build_failed",
                code="BUILD_FAILED",
                error=exc,
            )
            raise

    def rebuild(self, progress: ProgressCallback = None) -> ArtifactManifest:
        self.manifest_lifecycle.reset(stage=ARTIFACT_STAGE_REBUILDING)
        self._emit(
            progress,
            "Building the inactive Milvus collection; the active collection remains available.",
        )
        return self.build(progress=progress, force_rebuild=True)

    def show_stats(self, progress: ProgressCallback = None) -> None:
        self.stats_presenter.show(progress)

    @staticmethod
    def _emit(progress: ProgressCallback, message: str) -> None:
        if progress:
            progress(message)


__all__ = ["KnowledgeBaseBuildWorkflow"]
