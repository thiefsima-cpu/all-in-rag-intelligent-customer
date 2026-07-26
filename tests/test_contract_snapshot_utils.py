from __future__ import annotations

import unittest

from rag_modules.contracts import QuerySemanticRuntimeSettings
from rag_modules.contracts.runtime import GenerationSnapshot, GraphRetrievalSnapshot, RouteSnapshot
from tests.configuration_test_helpers import build_test_config


class RuntimeSnapshotUtilsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.semantic_settings = QuerySemanticRuntimeSettings.from_config(build_test_config())

    def test_route_snapshot_copy_returns_detached_instance(self) -> None:
        original = RouteSnapshot(query="q", strategy="combined")

        copied = original.copy(semantic_settings=self.semantic_settings)

        self.assertEqual(copied, original)
        self.assertIsNot(copied, original)

    def test_route_snapshot_has_content_tracks_meaningful_fields(self) -> None:
        self.assertFalse(RouteSnapshot().has_content())
        self.assertTrue(RouteSnapshot(strategy="combined").has_content())

    def test_graph_mapping_deserializes_at_boundary(self) -> None:
        snapshot = GraphRetrievalSnapshot.from_dict(
            {"query": "q", "doc_count": 2, "path_count": 1},
            semantic_settings=self.semantic_settings,
        )

        self.assertEqual(snapshot.doc_count, 2)

    def test_graph_snapshot_copy_returns_detached_instance(self) -> None:
        original = GraphRetrievalSnapshot(query="q", doc_count=2)

        copied = original.copy(semantic_settings=self.semantic_settings)

        self.assertEqual(copied, original)
        self.assertIsNot(copied, original)

    def test_graph_snapshot_has_content_tracks_meaningful_fields(self) -> None:
        self.assertFalse(GraphRetrievalSnapshot().has_content())
        self.assertTrue(GraphRetrievalSnapshot(doc_count=1).has_content())

    def test_generation_snapshot_copy_returns_detached_instance(self) -> None:
        original = GenerationSnapshot(mode="direct", total_evidence_items=2)

        copied = original.copy()

        self.assertEqual(copied, original)
        self.assertIsNot(copied, original)


if __name__ == "__main__":
    unittest.main()
