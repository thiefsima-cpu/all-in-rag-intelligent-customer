"""Offline knowledge-base build workflow."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from ..kernel.artifacts import (
    ARTIFACT_STAGE_REBUILDING,
    ArtifactManifest,
    DocumentArtifactResult,
)
from ..runtime.artifact_adapters import DefaultRuntimeArtifactAccess
from ..runtime.artifact_ports import ArtifactManifestStorePort, RuntimeArtifactAccessPort
from ..runtime.artifacts import ArtifactManifestStore
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


@dataclass
class _KnowledgeBaseBuildState:
    active_manifest: ArtifactManifest
    build_target: dict[str, str] = field(default_factory=dict)
    publish_rollback_target: str = ""
    published: bool = False


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
        request_id: str = "",
        build_job_id: str = "",
    ) -> ArtifactManifest:
        self._emit(progress, "\nChecking knowledge base state...")
        state = _KnowledgeBaseBuildState(active_manifest=self.artifact_manifest)
        self._configure_active_collection(state.active_manifest)
        try:
            reused = self._try_reuse_existing_collection(
                state.active_manifest,
                progress=progress,
                force_rebuild=force_rebuild,
            )
            if reused is not None:
                return reused
            return self._build_new_collection(state, progress=progress, request_id=request_id)
        except Exception as exc:
            self._handle_build_failure(
                state,
                exc,
                request_id=request_id,
                build_job_id=build_job_id,
            )
            raise

    def _try_reuse_existing_collection(
        self,
        active_manifest: ArtifactManifest,
        *,
        progress: ProgressCallback,
        force_rebuild: bool,
    ) -> ArtifactManifest | None:
        if force_rebuild or not self.runtime_artifact_access.has_vector_collection(
            self.index_module
        ):
            return None
        self._emit(
            progress,
            "[OK] Existing vector collection found. Checking artifact signatures...",
        )
        document_result = self._load_graph_and_documents(progress)
        if not self._can_reuse_existing_vector_collection(
            document_result.manifest,
            progress=progress,
        ):
            self._emit(
                progress,
                "[WARN] Existing vector collection is stale for current artifacts. Rebuilding...",
            )
            return None
        self._emit(
            progress,
            "[OK] Existing vector collection matches current artifacts. Attempting load...",
        )
        if not self.runtime_artifact_access.load_vector_collection(self.index_module):
            self._emit(progress, "[WARN] Existing knowledge base load failed. Rebuilding...")
            return None
        self._emit(progress, "[OK] Knowledge base loaded successfully.")
        self._mark_reused_collection_ready(document_result, active_manifest, progress)
        return self.artifact_manifest

    def _load_graph_and_documents(
        self,
        progress: ProgressCallback,
    ) -> DocumentArtifactResult:
        self._emit(progress, "Loading graph data...")
        self.runtime_artifact_access.load_graph_data(self.data_module)
        self._emit(progress, "Loading or building documents and chunks...")
        return self.document_artifact_builder.build_or_load(self.data_module)

    def _mark_reused_collection_ready(
        self,
        document_result: DocumentArtifactResult,
        active_manifest: ArtifactManifest,
        progress: ProgressCallback,
    ) -> None:
        schema_sync_result = self._sync_semantic_graph_schema(progress)
        self.manifest_lifecycle.mark_ready(
            self._reuse_manifest(document_result.manifest, active_manifest=active_manifest),
            vector_rows=self.stats_presenter.vector_row_count(),
            build_metadata=self._build_metadata(document_result, schema_sync_result),
            index_version=active_manifest.index_version,
        )

    def _build_new_collection(
        self,
        state: _KnowledgeBaseBuildState,
        *,
        progress: ProgressCallback,
        request_id: str,
    ) -> ArtifactManifest:
        self._emit(progress, "No usable vector collection found. Building a new knowledge base...")
        self._emit(progress, "Loading graph data from Neo4j...")
        self.runtime_artifact_access.load_graph_data(self.data_module)
        self._emit(progress, "Building documents and chunks...")
        document_result = self.document_artifact_builder.build_or_load(self.data_module)
        schema_sync_result = self._sync_semantic_graph_schema(progress)
        state.build_target = self._prepare_vector_build(state.active_manifest)
        candidate_manifest = self._candidate_manifest(document_result, state)
        self.manifest_lifecycle.mark_building(candidate_manifest)
        self._emit(progress, "Building Milvus vector index...")
        if not self._build_vector_index(
            document_result.chunks,
            collection_name=state.build_target["collection_name"],
        ):
            raise RuntimeError("Vector index build failed")
        state.publish_rollback_target = self._publish_vector_index(
            state.build_target["collection_name"]
        )
        state.published = True
        self.manifest_lifecycle.mark_ready(
            candidate_manifest,
            vector_rows=self.stats_presenter.vector_row_count(),
            build_metadata=self._build_metadata(document_result, schema_sync_result),
        )
        self._show_stats_after_publish(progress, request_id=request_id)
        self._emit(progress, "[OK] Knowledge base build completed.")
        return self.artifact_manifest

    @staticmethod
    def _candidate_manifest(
        document_result: DocumentArtifactResult,
        state: _KnowledgeBaseBuildState,
    ) -> ArtifactManifest:
        return document_result.manifest.evolve(
            collection_name=state.build_target["collection_name"],
            collection_base_name=state.build_target["collection_base_name"],
            collection_slot=state.build_target["collection_slot"],
            previous_collection_name=(
                state.active_manifest.collection_name if state.active_manifest.is_ready else ""
            ),
        )

    def _show_stats_after_publish(self, progress: ProgressCallback, *, request_id: str) -> None:
        try:
            self.stats_presenter.show(progress)
        except Exception as stats_exc:
            log_failure(
                logger,
                logging.WARNING,
                "build_stats_report_failed",
                code="BUILD_STATS_REPORT_FAILED",
                error=stats_exc,
                request_id=request_id,
            )
            self._emit(progress, "[WARN] Knowledge base stats unavailable after publish.")

    def _handle_build_failure(
        self,
        state: _KnowledgeBaseBuildState,
        exc: Exception,
        *,
        request_id: str,
        build_job_id: str,
    ) -> None:
        if state.published:
            self._rollback_vector_publish(state.publish_rollback_target)
        if state.build_target:
            self._discard_vector_build(state.build_target["collection_name"])
        self._configure_active_collection(state.active_manifest)
        self.manifest_lifecycle.mark_failed(
            exc,
            request_id=request_id,
            build_job_id=build_job_id,
        )
        log_failure(
            logger,
            logging.ERROR,
            "build_failed",
            code="BUILD_FAILED",
            error=exc,
            request_id=request_id,
        )

    def rebuild(
        self,
        progress: ProgressCallback = None,
        *,
        request_id: str = "",
        build_job_id: str = "",
    ) -> ArtifactManifest:
        self.manifest_lifecycle.reset(stage=ARTIFACT_STAGE_REBUILDING)
        self._emit(
            progress,
            "Building the inactive Milvus collection; the active collection remains available.",
        )
        return self.build(
            progress=progress,
            force_rebuild=True,
            request_id=request_id,
            build_job_id=build_job_id,
        )

    def show_stats(self, progress: ProgressCallback = None) -> None:
        self.stats_presenter.show(progress)

    @staticmethod
    def _emit(progress: ProgressCallback, message: str) -> None:
        if progress:
            progress(message)


__all__ = ["KnowledgeBaseBuildWorkflow"]
