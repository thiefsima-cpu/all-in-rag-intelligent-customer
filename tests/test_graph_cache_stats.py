from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from rag_modules.artifacts import ArtifactManifest, ArtifactManifestStore
from rag_modules.graph.cache import GraphCacheStats, GraphCacheStatsStore


class GraphCacheStatsTests(unittest.TestCase):
    def _build_config(self, root: Path) -> SimpleNamespace:
        storage_dir = root / "storage" / "indexes"
        return SimpleNamespace(
            storage=SimpleNamespace(
                index_cache_dir=str(storage_dir),
                artifact_manifest_path=str(storage_dir / "artifact_manifest.json"),
            )
        )

    def test_stats_store_round_trips_and_reads_manifest_signature(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            config = self._build_config(root)
            manifest_store = ArtifactManifestStore(config)
            manifest_store.save(
                ArtifactManifest(
                    stage="ready",
                    graph_signature="graph-signature-123",
                )
            )

            store = GraphCacheStatsStore(config)
            stats = GraphCacheStats(
                graph_signature="graph-signature-123",
                entity_count=3,
                relation_type_count=2,
                entities=[
                    {"name": "水煮肉片", "label": "Recipe"},
                    {"name": "花椒", "label": "Ingredient"},
                ],
                relation_frequencies={"HAS_FLAVOR": 5, "REQUIRES": 8},
                page_size=250,
                source="paged_scan",
            )
            store.save(stats)
            loaded = store.load()

            self.assertIsNotNone(loaded)
            assert loaded is not None
            self.assertEqual(store.expected_graph_signature(), "graph-signature-123")
            self.assertEqual(loaded.graph_signature, "graph-signature-123")
            self.assertEqual(loaded.entity_count, 3)
            self.assertEqual(loaded.relation_frequencies["HAS_FLAVOR"], 5)


if __name__ == "__main__":
    unittest.main()
