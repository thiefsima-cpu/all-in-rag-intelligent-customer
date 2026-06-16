from __future__ import annotations

import unittest

from scripts.smoke_generation_plans import DEFAULT_CORPUS_PATH, run_smoke


class GenerationPlanSmokeTests(unittest.TestCase):
    def test_offline_generation_plan_smoke_corpus_passes(self) -> None:
        self.assertTrue(DEFAULT_CORPUS_PATH.exists())

        report = run_smoke(DEFAULT_CORPUS_PATH)

        self.assertEqual(report["case_count"], report["passed_count"])
        self.assertFalse(report["failures"])


if __name__ == "__main__":
    unittest.main()
