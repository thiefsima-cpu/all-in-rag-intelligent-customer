from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from rag_modules.configuration.testing import build_test_config
from rag_modules.interfaces.api.services import GraphRAGServingApiService
from rag_modules.runtime.artifacts import (
    ARTIFACT_STAGE_READY,
    ArtifactManifest,
    ArtifactManifestStore,
)
from rag_modules.runtime.artifacts.registry import ArtifactRegistry


class _ServingSystem:
    def __init__(self, config, manifest_store) -> None:
        self.config = config
        self.manifest_store = manifest_store
        self.artifact_manifest = manifest_store.load()
        self.system_ready = True
        self.refresh_calls = 0

    def is_build_initialized(self) -> bool:
        return False

    def is_serving_initialized(self) -> bool:
        return True

    def refresh_serving_runtime(self, progress=None, *, force: bool = True):
        del progress, force
        self.refresh_calls += 1
        self.artifact_manifest = self.manifest_store.load()

    def close(self) -> None:
        return None


class ArtifactRegistryHotRefreshTests(unittest.TestCase):
    def test_registry_lists_immutable_versions_and_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config = build_test_config(
                {"storage": {"artifact_manifest_path": str(Path(temp_dir) / "manifest.json")}}
            )
            store = ArtifactManifestStore(config)
            first = store.save(
                ArtifactManifest(stage=ARTIFACT_STAGE_READY, collection_name="recipes__blue")
            )
            second = store.save(first.evolve(collection_name="recipes__green"))
            candidate = store.save_candidate(
                second.evolve(stage="building", collection_name="recipes__blue")
            )
            registry = ArtifactRegistry(store)

            snapshot = registry.snapshot()

            self.assertEqual(snapshot.active.manifest_version, second.manifest_version)
            self.assertEqual(snapshot.candidate.manifest_version, candidate.manifest_version)
            self.assertEqual(snapshot.versions, (1, 2))
            self.assertEqual(
                [manifest.collection_name for manifest in registry.list()],
                ["recipes__green", "recipes__blue"],
            )

    def test_serving_service_refreshes_when_active_manifest_advances(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config = build_test_config(
                {
                    "storage": {"artifact_manifest_path": str(Path(temp_dir) / "manifest.json")},
                    "api": {"serving_hot_refresh_interval_seconds": 0.1},
                }
            )
            store = ArtifactManifestStore(config)
            first = store.save(
                ArtifactManifest(stage=ARTIFACT_STAGE_READY, collection_name="recipes__blue")
            )
            system = _ServingSystem(config, store)
            service = GraphRAGServingApiService(
                system=system,
                artifact_registry=ArtifactRegistry(store),
            )
            second = store.save(first.evolve(collection_name="recipes__green"))

            refreshed = service._refresh_serving_runtime_if_stale(force_check=True)

            self.assertTrue(refreshed)
            self.assertEqual(system.refresh_calls, 1)
            self.assertEqual(
                system.artifact_manifest.manifest_version,
                second.manifest_version,
            )


if __name__ == "__main__":
    unittest.main()
