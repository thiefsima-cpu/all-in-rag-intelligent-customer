"""Serving-runtime readiness preparation and artifact loading."""

from __future__ import annotations

from ...artifacts import ARTIFACT_STAGE_STALE, ArtifactManifest
from ...langchain_document_adapter import to_langchain_text_documents
from ...runtime.artifact_ports import (
    ArtifactManifestStorePort,
    DocumentArtifactCachePort,
    RuntimeArtifactAccessPort,
)
from ...runtime.artifact_validation import vector_artifact_mismatch_reason
from ..runtime_state import BuildRuntime, ServingRuntime
from .shared import ProgressCallback, emit_progress


class ServingRuntimePreparer:
    """Prepare an assembled serving runtime to answer questions."""

    def __init__(
        self,
        *,
        provider=None,
        manifest_store: ArtifactManifestStorePort | None = None,
        document_artifact_cache: DocumentArtifactCachePort | None = None,
        runtime_artifact_access: RuntimeArtifactAccessPort | None = None,
    ) -> None:
        self.provider = provider
        self.infrastructure = getattr(provider, "infrastructure", None)
        self.manifest_store = manifest_store
        self.document_artifact_cache = document_artifact_cache
        self.runtime_artifact_access = runtime_artifact_access

    def prepare(
        self,
        runtime: ServingRuntime,
        *,
        chunks=None,
        artifact_manifest=None,
        progress: ProgressCallback = None,
        force: bool = False,
    ) -> ServingRuntime:
        previous_manifest_version = int(
            getattr(runtime.artifact_manifest, "manifest_version", 0) or 0
        )
        if artifact_manifest is not None:
            runtime.artifact_manifest = artifact_manifest
        elif force or not runtime.artifact_manifest.is_ready:
            runtime.artifact_manifest = self.load_persisted_manifest(runtime.config)

        manifest_changed = (
            int(runtime.artifact_manifest.manifest_version or 0)
            != previous_manifest_version
        )
        if chunks is not None:
            resolved_chunks = chunks
        elif force and manifest_changed:
            resolved_chunks = []
        else:
            resolved_chunks = getattr(runtime.data_module, "chunks", None) or []
        chunks = resolved_chunks
        if (
            runtime.retrieval_engines_initialized
            and runtime.artifact_manifest.is_ready
            and not force
        ):
            return runtime
        if runtime.artifact_manifest.is_ready and not chunks:
            chunks = self.load_cached_document_artifacts(runtime, progress=progress)
        if not runtime.artifact_manifest.is_ready or not chunks:
            runtime.retrieval_engines_initialized = False
            emit_progress(
                progress,
                "[WARN] Serving runtime is assembled but retrieval artifacts are not loaded yet.",
            )
            return runtime

        if not self.ensure_vector_collection_loaded(runtime, progress=progress):
            runtime.retrieval_engines_initialized = False
            return runtime

        emit_progress(progress, "Initializing retrieval engines...")
        try:
            runtime.traditional_retrieval.initialize(to_langchain_text_documents(chunks))
            runtime.graph_rag_retrieval.initialize()
        except Exception as exc:
            runtime.retrieval_engines_initialized = False
            emit_progress(
                progress,
                f"[ERROR] Retrieval engine initialization failed: {exc}",
            )
            raise RuntimeError(
                f"Serving runtime retrieval initialization failed: {exc}"
            ) from exc
        runtime.retrieval_engines_initialized = True
        emit_progress(progress, "[OK] Serving runtime is ready.")
        return runtime

    def prepare_with_shared_runtime(
        self,
        runtime: ServingRuntime,
        *,
        shared_runtime: BuildRuntime | None = None,
        progress: ProgressCallback = None,
        force: bool = False,
    ) -> ServingRuntime:
        if shared_runtime and shared_runtime.artifacts_ready:
            return self.prepare(
                runtime,
                chunks=shared_runtime.data_module.chunks if shared_runtime.data_module else None,
                artifact_manifest=shared_runtime.artifact_manifest,
                progress=progress,
                force=force,
            )
        return self.prepare(
            runtime,
            progress=progress,
            force=force,
        )

    def _resolve_manifest_store(self, config) -> ArtifactManifestStorePort:
        if self.manifest_store is not None:
            return self.manifest_store
        infrastructure = self.infrastructure
        if infrastructure is None:
            raise ValueError(
                "ServingRuntimePreparer requires an infrastructure provider or manifest store."
            )
        return infrastructure.provide_artifact_manifest_store(config)

    def _resolve_document_artifact_cache(
        self,
        config,
        *,
        manifest_store: ArtifactManifestStorePort | None = None,
    ) -> DocumentArtifactCachePort:
        if self.document_artifact_cache is not None:
            return self.document_artifact_cache
        infrastructure = self.infrastructure
        if infrastructure is None:
            raise ValueError(
                "ServingRuntimePreparer requires an infrastructure provider "
                "or document artifact cache."
            )
        return infrastructure.provide_document_artifact_cache(
            config,
            manifest_store=manifest_store,
        )

    def _resolve_runtime_artifact_access(
        self,
        config,
    ) -> RuntimeArtifactAccessPort:
        if self.runtime_artifact_access is not None:
            return self.runtime_artifact_access
        infrastructure = self.infrastructure
        if infrastructure is None:
            raise ValueError(
                "ServingRuntimePreparer requires an infrastructure provider "
                "or runtime artifact access adapter."
            )
        return infrastructure.provide_runtime_artifact_access(config)

    def load_persisted_manifest(self, config) -> ArtifactManifest:
        return self._resolve_manifest_store(config).load()

    def load_cached_document_artifacts(
        self,
        runtime: ServingRuntime,
        *,
        progress: ProgressCallback = None,
    ):
        emit_progress(progress, "Loading graph data for serving artifact cache...")
        runtime_artifact_access = self._resolve_runtime_artifact_access(runtime.config)
        runtime_artifact_access.load_graph_data(runtime.data_module)
        manifest_store = self._resolve_manifest_store(runtime.config)
        document_cache = self._resolve_document_artifact_cache(
            runtime.config,
            manifest_store=manifest_store,
        )
        document_result = document_cache.load(runtime.data_module)
        if document_result is None:
            emit_progress(
                progress,
                "[WARN] Artifact manifest exists, but cached documents/chunks could not be loaded.",
            )
            return []
        merged_manifest = self._merge_serving_manifest(
            persisted_manifest=runtime.artifact_manifest,
            document_manifest=document_result.manifest,
            progress=progress,
        )
        if merged_manifest is None:
            return []
        runtime.artifact_manifest = merged_manifest
        if not merged_manifest.is_ready:
            return []
        return list(document_result.chunks or [])

    def ensure_vector_collection_loaded(
        self,
        runtime: ServingRuntime,
        *,
        progress: ProgressCallback = None,
    ) -> bool:
        runtime_artifact_access = self._resolve_runtime_artifact_access(runtime.config)
        configure = getattr(
            runtime_artifact_access,
            "configure_vector_collection",
            None,
        )
        if callable(configure):
            configure(runtime.index_module, runtime.artifact_manifest)
        elif runtime.artifact_manifest.collection_name and hasattr(
            runtime.index_module,
            "collection_name",
        ):
            runtime.index_module.collection_name = runtime.artifact_manifest.collection_name
        if not runtime_artifact_access.has_vector_collection(runtime.index_module):
            emit_progress(
                progress,
                "[WARN] Vector collection is missing. Build artifacts before starting serving.",
            )
            return False
        if runtime_artifact_access.load_vector_collection(runtime.index_module):
            return True
        emit_progress(
            progress,
            "[WARN] Vector collection exists but could not be loaded into memory.",
        )
        return False

    @staticmethod
    def _merge_serving_manifest(
        *,
        persisted_manifest: ArtifactManifest,
        document_manifest: ArtifactManifest,
        progress: ProgressCallback = None,
    ) -> ArtifactManifest | None:
        mismatch_reason = vector_artifact_mismatch_reason(
            persisted_manifest=persisted_manifest,
            current_manifest=document_manifest,
        )
        if mismatch_reason:
            emit_progress(progress, f"[WARN] {mismatch_reason}")
            return persisted_manifest.evolve(
                stage=ARTIFACT_STAGE_STALE,
                last_error=mismatch_reason,
            )
        return persisted_manifest.evolve(
            graph_signature=document_manifest.graph_signature,
            document_signature=document_manifest.document_signature,
            embedding_signature=document_manifest.embedding_signature,
            index_signature=document_manifest.index_signature,
            documents_path=document_manifest.documents_path,
            chunks_path=document_manifest.chunks_path,
            total_recipes=document_manifest.total_recipes,
            total_ingredients=document_manifest.total_ingredients,
            total_cooking_steps=document_manifest.total_cooking_steps,
            total_documents=document_manifest.total_documents,
            total_chunks=document_manifest.total_chunks,
            cache_hit=document_manifest.cache_hit,
            build_metadata=document_manifest.build_metadata,
            last_error="",
        )


__all__ = ["ServingRuntimePreparer"]
