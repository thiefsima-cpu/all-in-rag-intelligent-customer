from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from rag_modules.app.composition.serving_runtime_preparer import ServingRuntimePreparer
from rag_modules.kernel.artifacts import ArtifactManifest, DocumentArtifactResult
from rag_modules.kernel.documents import TextDocument


def _ready_manifest(*, version: int = 1, collection: str = "recipes") -> ArtifactManifest:
    return ArtifactManifest(
        stage="ready",
        manifest_version=version,
        index_signature="sig",
        collection_name=collection,
    )


def _runtime(
    *,
    manifest: ArtifactManifest | None = None,
    chunks: list[TextDocument] | None = None,
    initialized: bool = False,
):
    data_module = SimpleNamespace(chunks=list(chunks or []), load_graph_data=lambda: {})
    return SimpleNamespace(
        config=SimpleNamespace(),
        artifact_manifest=manifest or ArtifactManifest.missing(),
        retrieval_engines_initialized=initialized,
        data_module=data_module,
        index_module=SimpleNamespace(collection_name="base"),
        traditional_retrieval=SimpleNamespace(initialize=lambda docs: None),
        graph_rag_retrieval=SimpleNamespace(initialize=lambda: None),
    )


class _ArtifactAccess:
    def __init__(self, *, has_collection: bool = True, loads: bool = True) -> None:
        self.has_collection = has_collection
        self.loads = loads
        self.configured: list[ArtifactManifest] = []

    def load_graph_data(self, data_module):
        return data_module.load_graph_data()

    def configure_vector_collection(self, index_module, manifest) -> None:
        self.configured.append(manifest)
        index_module.collection_name = manifest.collection_name

    def has_vector_collection(self, index_module) -> bool:
        return self.has_collection

    def load_vector_collection(self, index_module) -> bool:
        return self.loads


def test_prepare_accepts_explicit_artifacts_and_returns_already_initialized_runtime() -> None:
    runtime = _runtime(manifest=_ready_manifest(version=1), initialized=True)
    preparer = ServingRuntimePreparer(runtime_artifact_access=_ArtifactAccess())
    replacement = _ready_manifest(version=2)
    chunks = [TextDocument(content="chunk")]

    assert preparer.prepare(runtime, chunks=chunks, artifact_manifest=replacement) is runtime
    assert runtime.artifact_manifest is replacement


def test_prepare_force_manifest_change_clears_stale_chunks_and_reports_not_ready() -> None:
    runtime = _runtime(manifest=_ready_manifest(version=1), chunks=[TextDocument(content="stale")])
    preparer = ServingRuntimePreparer(runtime_artifact_access=_ArtifactAccess())
    progress: list[str] = []

    with patch.object(preparer, "load_cached_document_artifacts", return_value=[]):
        result = preparer.prepare(
            runtime,
            artifact_manifest=_ready_manifest(version=2),
            progress=progress.append,
            force=True,
        )

    assert result is runtime
    assert runtime.retrieval_engines_initialized is False
    assert any("not loaded" in message for message in progress)


def test_prepare_handles_vector_failure_and_missing_retrieval_engines() -> None:
    chunks = [TextDocument(content="chunk")]
    runtime = _runtime(manifest=_ready_manifest())
    preparer = ServingRuntimePreparer(runtime_artifact_access=_ArtifactAccess(has_collection=False))
    assert preparer.prepare(runtime, chunks=chunks).retrieval_engines_initialized is False

    runtime = _runtime(manifest=_ready_manifest())
    runtime.traditional_retrieval = None
    preparer = ServingRuntimePreparer(runtime_artifact_access=_ArtifactAccess())
    with pytest.raises(ValueError, match="missing retrieval engines"):
        preparer.prepare(runtime, chunks=chunks)


def test_prepare_with_shared_runtime_selects_ready_shared_artifacts_or_fallback() -> None:
    preparer = ServingRuntimePreparer()
    runtime = _runtime()
    shared = SimpleNamespace(
        artifacts_ready=True,
        data_module=SimpleNamespace(chunks=[TextDocument(content="shared")]),
        artifact_manifest=_ready_manifest(),
    )
    with patch.object(preparer, "prepare", return_value=runtime) as prepare:
        assert preparer.prepare_with_shared_runtime(runtime, shared_runtime=shared) is runtime
        assert prepare.call_args.kwargs["chunks"][0].content == "shared"

        shared.artifacts_ready = False
        preparer.prepare_with_shared_runtime(runtime, shared_runtime=shared)
        assert "chunks" not in prepare.call_args.kwargs


def test_dependency_resolvers_use_explicit_dependencies_and_reject_missing_provider() -> None:
    manifest_store = object()
    document_cache = object()
    access = object()
    explicit = ServingRuntimePreparer(
        manifest_store=manifest_store,
        document_artifact_cache=document_cache,
        runtime_artifact_access=access,
    )
    config = SimpleNamespace()
    assert explicit._resolve_manifest_store(config) is manifest_store
    assert explicit._resolve_document_artifact_cache(config) is document_cache
    assert explicit._resolve_runtime_artifact_access(config) is access

    missing = ServingRuntimePreparer()
    with pytest.raises(ValueError, match="manifest store"):
        missing._resolve_manifest_store(config)
    with pytest.raises(ValueError, match="document artifact cache"):
        missing._resolve_document_artifact_cache(config)
    with pytest.raises(ValueError, match="runtime artifact access"):
        missing._resolve_runtime_artifact_access(config)


def test_cached_document_loading_guards_missing_data_cache_and_stale_merge() -> None:
    access = _ArtifactAccess()
    manifest_store = SimpleNamespace(load=lambda: _ready_manifest())
    runtime = _runtime(manifest=_ready_manifest())
    progress: list[str] = []

    preparer = ServingRuntimePreparer(
        manifest_store=manifest_store,
        document_artifact_cache=SimpleNamespace(load=lambda data_module: None),
        runtime_artifact_access=access,
    )
    runtime.data_module = None
    assert preparer.load_cached_document_artifacts(runtime, progress=progress.append) == []

    runtime.data_module = SimpleNamespace(load_graph_data=lambda: {})
    assert preparer.load_cached_document_artifacts(runtime, progress=progress.append) == []

    result = DocumentArtifactResult(
        documents=[],
        chunks=[TextDocument(content="cached")],
        manifest=ArtifactManifest(stage="documents_ready", index_signature="other"),
        cache_hit=True,
    )
    preparer.document_artifact_cache = SimpleNamespace(load=lambda data_module: result)
    assert preparer.load_cached_document_artifacts(runtime) == []
    assert runtime.artifact_manifest.stage == "stale"


def test_vector_loading_covers_missing_index_configure_and_load_failure() -> None:
    runtime = _runtime(manifest=_ready_manifest(collection="physical"))
    access = _ArtifactAccess(loads=False)
    preparer = ServingRuntimePreparer(runtime_artifact_access=access)

    runtime.index_module = None
    assert preparer.ensure_vector_collection_loaded(runtime) is False

    runtime.index_module = SimpleNamespace(collection_name="base")
    assert preparer.ensure_vector_collection_loaded(runtime) is False
    assert runtime.index_module.collection_name == "physical"
    assert access.configured == [runtime.artifact_manifest]
