from __future__ import annotations

import unittest

from scripts.smoke_answer_pipeline_real_route import DEFAULT_CORPUS_PATH, run_smoke


class AnswerPipelineRealRouteSmokeTests(unittest.TestCase):
    def test_real_route_answer_pipeline_smoke_corpus_passes(self) -> None:
        self.assertTrue(DEFAULT_CORPUS_PATH.exists())

        report = run_smoke(DEFAULT_CORPUS_PATH)

        self.assertEqual(report["case_count"], report["passed_count"])
        self.assertFalse(report["failures"])
        self.assertEqual(
            report["metrics"],
            {
                "plan_contract_pass_rate": 1.0,
                "request_contract_pass_rate": 1.0,
                "trace_contract_pass_rate": 1.0,
                "graph_contract_pass_rate": 1.0,
                "evidence_contract_pass_rate": 1.0,
                "offline_planner_guard_pass_rate": 1.0,
            },
        )
        for result in report["results"]:
            self.assertTrue(result["contract_checks"])
            self.assertTrue(
                all(check["passed"] for check in result["contract_checks"].values()),
                result["contract_checks"],
            )


if __name__ == "__main__":
    unittest.main()
