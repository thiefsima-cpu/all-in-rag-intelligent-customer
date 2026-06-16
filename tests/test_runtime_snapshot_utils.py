from __future__ import annotations

import unittest

from rag_modules.runtime import GenerationSnapshot, GraphRetrievalSnapshot, RouteSnapshot
from rag_modules.runtime.snapshot_utils import (
    clone_generation_snapshot,
    clone_graph_snapshot,
    clone_route_snapshot,
)


class RuntimeSnapshotUtilsTests(unittest.TestCase):
    def test_clone_route_snapshot_returns_detached_copy(self) -> None:
        original = RouteSnapshot(query="q", strategy="combined")

        cloned = clone_route_snapshot(original)

        self.assertEqual(cloned.query, "q")
        self.assertEqual(cloned.strategy, "combined")
        self.assertIsNot(cloned, original)

    def test_route_snapshot_has_content_tracks_meaningful_fields(self) -> None:
        self.assertFalse(RouteSnapshot().has_content())
        self.assertTrue(RouteSnapshot(strategy="combined").has_content())

    def test_clone_graph_snapshot_accepts_mapping_payload(self) -> None:
        cloned = clone_graph_snapshot({"query": "q", "doc_count": 2, "path_count": 1})

        self.assertEqual(cloned.query, "q")
        self.assertEqual(cloned.doc_count, 2)
        self.assertEqual(cloned.path_count, 1)

    def test_graph_snapshot_has_content_tracks_meaningful_fields(self) -> None:
        self.assertFalse(GraphRetrievalSnapshot().has_content())
        self.assertTrue(GraphRetrievalSnapshot(doc_count=1).has_content())

    def test_clone_generation_snapshot_defaults_when_missing(self) -> None:
        cloned = clone_generation_snapshot(None)

        self.assertEqual(cloned, GenerationSnapshot())

    def test_clone_generation_snapshot_returns_detached_copy(self) -> None:
        original = GenerationSnapshot(mode="direct", total_evidence_items=2)

        cloned = clone_generation_snapshot(original)

        self.assertEqual(cloned.mode, "direct")
        self.assertEqual(cloned.total_evidence_items, 2)
        self.assertIsNot(cloned, original)


if __name__ == "__main__":
    unittest.main()
