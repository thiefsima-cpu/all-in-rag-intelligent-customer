"""Offline knowledge-base build workflow."""

from __future__ import annotations

import logging

from ..artifacts import ARTIFACT_STAGE_REBUILDING, ArtifactManifest, ArtifactManifestStore
from ..runtime.artifact_adapters import DefaultRuntimeArtifactAccess
from ..runtime.artifact_ports import ArtifactManifestStorePort, RuntimeArtifactAccessPort
from ..runtime.artifact_validation import vector_artifact_mismatch_reason
from ..runtime.stats_adapters import DefaultRuntimeStatsAccess
from ..runtime.stats_ports import RuntimeStatsAccessPort
from .contracts import (
    DocumentArtifactBuilderPort,
    SemanticGraphSchemaSyncPort,
    SemanticGraphSchemaSyncResult,
)
from .document_artifacts import DocumentArtifactBuildService
from .manifest_lifecycle import KnowledgeBaseManifestLifecycle
from .schema_sync import SemanticGraphSchemaSyncService
from .stats_presenter import KnowledgeBaseStatsPresenter, ProgressCallback

logger = logging.getLogger(__name__)


class KnowledgeBaseBuildWorkflow:
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
            logger.exception("Knowledge base build failed")
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

    def _sync_semantic_graph_schema(
        self,
        progress: ProgressCallback = None,
    ) -> SemanticGraphSchemaSyncResult:
        if not self.config.graph.enable_semantic_graph_schema:
            return SemanticGraphSchemaSyncResult(enabled=False)
        self._emit(progress, "Syncing semantic graph schema...")
        try:
            result = self.semantic_graph_schema_sync.sync_from_documents(
                self.data_module.documents or []
            )
            self._emit(
                progress,
                "[OK] Semantic graph schema synced: "
                f"recipes={result.recipes}, "
                f"semantic_nodes={result.nodes}, "
                f"semantic_relationships={result.relationships}",
            )
            return result
        except Exception as exc:
            logger.warning("Semantic graph schema sync failed: %s", exc)
            self._emit(
                progress, f"[WARN] Semantic graph schema sync failed. Continuing startup: {exc}"
            )
            return SemanticGraphSchemaSyncResult(enabled=True, error=str(exc))

    def _build_metadata(
        self, document_result, schema_sync_result: SemanticGraphSchemaSyncResult
    ) -> dict:
        return {
            "config_profile": {
                "name": getattr(self.config, "profile_name", ""),
                "path": getattr(self.config, "profile_path", ""),
                "hash": getattr(self.config, "profile_hash", ""),
            },
            "document_cache_hit": document_result.cache_hit,
            "semantic_graph_schema": schema_sync_result.to_metadata(),
        }

    def _can_reuse_existing_vector_collection(
        self,
        document_manifest: ArtifactManifest,
        *,
        progress: ProgressCallback = None,
    ) -> bool:
        mismatch_reason = vector_artifact_mismatch_reason(
            persisted_manifest=self.artifact_manifest,
            current_manifest=document_manifest,
        )
        if mismatch_reason:
            self._emit(progress, f"[WARN] {mismatch_reason}")
            return False
        return True

    def _configure_active_collection(self, manifest: ArtifactManifest) -> None:
        configure = getattr(
            self.runtime_artifact_access,
            "configure_vector_collection",
            None,
        )
        if callable(configure):
            configure(self.index_module, manifest)
            return
        collection_name = str(manifest.collection_name or "")
        if collection_name and hasattr(self.index_module, "collection_name"):
            self.index_module.collection_name = collection_name

    def _prepare_vector_build(
        self,
        active_manifest: ArtifactManifest,
    ) -> dict[str, str]:
        prepare = getattr(
            self.runtime_artifact_access,
            "prepare_vector_index_build",
            None,
        )
        if callable(prepare):
            target = dict(
                prepare(
                    self.index_module,
                    active_manifest.collection_name if active_manifest.is_ready else "",
                )
                or {}
            )
        else:
            target = {}
        base_name = str(
            target.get("collection_base_name")
            or getattr(self.config.storage, "milvus_collection_name", "")
            or getattr(self.index_module, "collection_name", "")
        )
        collection_name = str(
            target.get("collection_name")
            or getattr(self.index_module, "collection_name", "")
            or base_name
        )
        return {
            "collection_name": collection_name,
            "collection_base_name": base_name,
            "collection_slot": str(target.get("collection_slot") or ""),
        }

    def _build_vector_index(self, chunks, *, collection_name: str) -> bool:
        try:
            return bool(
                self.runtime_artifact_access.build_vector_index(
                    self.index_module,
                    chunks,
                    collection_name=collection_name,
                )
            )
        except TypeError:
            return bool(
                self.runtime_artifact_access.build_vector_index(
                    self.index_module,
                    chunks,
                )
            )

    def _publish_vector_index(self, collection_name: str) -> str:
        publish = getattr(
            self.runtime_artifact_access,
            "publish_vector_index",
            None,
        )
        if not callable(publish):
            return ""
        return str(publish(self.index_module, collection_name) or "")

    def _rollback_vector_publish(self, previous_collection_name: str) -> None:
        rollback = getattr(
            self.runtime_artifact_access,
            "rollback_vector_index_publish",
            None,
        )
        if callable(rollback):
            rollback(self.index_module, previous_collection_name)

    def _discard_vector_build(self, collection_name: str) -> None:
        discard = getattr(
            self.runtime_artifact_access,
            "discard_vector_index",
            None,
        )
        if callable(discard):
            discard(self.index_module, collection_name)

    @staticmethod
    def _reuse_manifest(
        document_manifest: ArtifactManifest,
        *,
        active_manifest: ArtifactManifest,
    ) -> ArtifactManifest:
        return document_manifest.evolve(
            collection_name=active_manifest.collection_name or document_manifest.collection_name,
            collection_base_name=active_manifest.collection_base_name
            or document_manifest.collection_base_name
            or document_manifest.collection_name,
            collection_slot=active_manifest.collection_slot,
            previous_collection_name=active_manifest.previous_collection_name,
            index_version=active_manifest.index_version,
            published_at=active_manifest.published_at,
        )

    @staticmethod
    def _emit(progress: ProgressCallback, message: str) -> None:
        if progress:
            progress(message)


__all__ = ["KnowledgeBaseBuildWorkflow"]
