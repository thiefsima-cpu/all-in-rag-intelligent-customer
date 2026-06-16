from __future__ import annotations

import unittest

from scripts.smoke_route_queries import DEFAULT_CORPUS_PATH, run_smoke


class RouteSmokeQueriesTests(unittest.TestCase):
    def test_offline_route_smoke_corpus_passes(self) -> None:
        self.assertTrue(DEFAULT_CORPUS_PATH.exists())

        report = run_smoke(DEFAULT_CORPUS_PATH)

        self.assertGreaterEqual(report["case_count"], 24)
        self.assertEqual(report["case_count"], report["passed_count"])
        self.assertGreaterEqual(report["category_count"], 9)
        self.assertEqual(
            set(report["category_counts"]),
            {
                "single_recipe",
                "recommendation",
                "constrained_recommendation",
                "classification",
                "multi_hop_relation",
                "path_finding",
                "subgraph",
                "clustering",
                "combined",
            },
        )
        self.assertFalse(report["failures"])


if __name__ == "__main__":
    unittest.main()
