from __future__ import annotations

import unittest

from rag_modules.artifacts import (
    ARTIFACT_STAGE_BUILDING,
    ARTIFACT_STAGE_DOCUMENTS_READY,
    ARTIFACT_STAGE_FAILED,
    ARTIFACT_STAGE_MANIFEST_UNREADABLE,
    ARTIFACT_STAGE_READY,
    ARTIFACT_STAGE_REBUILDING,
    ARTIFACT_STAGE_STALE,
    ArtifactManifest,
)
from rag_modules.build_pipeline.manifest_lifecycle import KnowledgeBaseManifestLifecycle


class _FakeManifestStore:
    def __init__(self, manifest: ArtifactManifest) -> None:
        self.manifest = manifest
        self.load_calls = 0
        self.saved: list[ArtifactManifest] = []

    def load(self) -> ArtifactManifest:
        self.load_calls += 1
        return self.manifest

    def save(self, manifest: ArtifactManifest) -> ArtifactManifest:
        self.manifest = manifest
        self.saved.append(manifest)
        return manifest


class KnowledgeBaseManifestLifecycleTests(unittest.TestCase):
    def test_artifact_manifest_stage_helpers_track_lifecycle_buckets(self) -> None:
        missing = ArtifactManifest.missing(manifest_path="manifest.json")
        ready = missing.evolve(stage=ARTIFACT_STAGE_READY)
        rebuilding = missing.evolve(stage=ARTIFACT_STAGE_REBUILDING)
        stale = missing.evolve(stage=ARTIFACT_STAGE_STALE)
        unreadable = missing.evolve(stage=ARTIFACT_STAGE_MANIFEST_UNREADABLE)

        self.assertTrue(missing.is_missing)
        self.assertTrue(missing.is_invalid)
        self.assertFalse(missing.is_ready)
        self.assertTrue(ready.is_ready)
        self.assertFalse(ready.is_invalid)
        self.assertTrue(rebuilding.is_in_progress)
        self.assertFalse(rebuilding.is_invalid)
        self.assertTrue(stale.is_stale)
        self.assertTrue(stale.is_invalid)
        self.assertTrue(unreadable.is_failed)

    def test_mark_ready_persists_ready_manifest(self) -> None:
        store = _FakeManifestStore(ArtifactManifest.missing(manifest_path="manifest.json"))
        lifecycle = KnowledgeBaseManifestLifecycle(store)
        base_manifest = store.manifest.evolve(
            stage=ARTIFACT_STAGE_DOCUMENTS_READY,
            total_documents=2,
            total_chunks=4,
            cache_hit=True,
        )

        manifest = lifecycle.mark_ready(
            base_manifest,
            vector_rows=4,
            build_metadata={"document_cache_hit": True},
        )

        self.assertEqual(store.load_calls, 1)
        self.assertEqual(manifest.stage, ARTIFACT_STAGE_READY)
        self.assertEqual(manifest.vector_rows, 4)
        self.assertEqual(manifest.build_metadata["document_cache_hit"], True)
        self.assertEqual(lifecycle.artifact_manifest.stage, ARTIFACT_STAGE_READY)

    def test_mark_failed_persists_failure_state(self) -> None:
        store = _FakeManifestStore(
            ArtifactManifest.missing(manifest_path="manifest.json").evolve(stage=ARTIFACT_STAGE_BUILDING)
        )
        lifecycle = KnowledgeBaseManifestLifecycle(store)

        manifest = lifecycle.mark_failed(RuntimeError("boom"))

        self.assertEqual(manifest.stage, ARTIFACT_STAGE_FAILED)
        self.assertEqual(manifest.last_error, "boom")
        self.assertEqual(store.saved[-1].stage, ARTIFACT_STAGE_FAILED)

    def test_reset_clears_error_and_cache_hit(self) -> None:
        store = _FakeManifestStore(
            ArtifactManifest.missing(manifest_path="manifest.json").evolve(
                stage=ARTIFACT_STAGE_FAILED,
                cache_hit=True,
                last_error="boom",
            )
        )
        lifecycle = KnowledgeBaseManifestLifecycle(store)

        manifest = lifecycle.reset(stage=ARTIFACT_STAGE_REBUILDING)

        self.assertEqual(manifest.stage, ARTIFACT_STAGE_REBUILDING)
        self.assertFalse(manifest.cache_hit)
        self.assertEqual(manifest.last_error, "")


if __name__ == "__main__":
    unittest.main()
