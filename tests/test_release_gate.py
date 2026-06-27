from __future__ import annotations

import copy
import os
import tempfile
import unittest

from scripts.release_gate import (
    DEFAULT_POLICY_PATH,
    INCLUDE_QUALITY_EVAL_ENV,
    _environment_flag,
    activate_optional_stages,
    evaluate_gate,
    load_policy,
    run_suites,
    write_report,
)


def _suite_report(case_count: int) -> dict:
    return {
        "case_count": case_count,
        "passed_count": case_count,
        "results": [],
        "failures": [],
    }


def _real_route_metrics(value: float = 1.0) -> dict:
    return {
        "plan_contract_pass_rate": value,
        "request_contract_pass_rate": value,
        "trace_contract_pass_rate": value,
        "graph_contract_pass_rate": value,
        "evidence_contract_pass_rate": value,
        "offline_planner_guard_pass_rate": value,
    }


def _real_route_suite_report(case_count: int, metric_value: float = 1.0) -> dict:
    report = _suite_report(case_count)
    report["metrics"] = _real_route_metrics(metric_value)
    return report


class ReleaseGateTests(unittest.TestCase):
    def test_environment_flag_accepts_explicit_boolean_spellings(self) -> None:
        for value in ("1", "true", "TRUE", "yes", "on"):
            with self.subTest(value=value):
                self.assertTrue(
                    _environment_flag(
                        INCLUDE_QUALITY_EVAL_ENV,
                        {INCLUDE_QUALITY_EVAL_ENV: value},
                    )
                )
        for value in ("0", "false", "FALSE", "no", "off"):
            with self.subTest(value=value):
                self.assertFalse(
                    _environment_flag(
                        INCLUDE_QUALITY_EVAL_ENV,
                        {INCLUDE_QUALITY_EVAL_ENV: value},
                    )
                )
        self.assertFalse(_environment_flag(INCLUDE_QUALITY_EVAL_ENV, {}))
        self.assertFalse(
            _environment_flag(
                INCLUDE_QUALITY_EVAL_ENV,
                {
                    key: value
                    for key, value in os.environ.items()
                    if key != INCLUDE_QUALITY_EVAL_ENV
                },
            )
        )

    def test_environment_flag_rejects_ambiguous_values(self) -> None:
        with self.assertRaisesRegex(ValueError, INCLUDE_QUALITY_EVAL_ENV):
            _environment_flag(
                INCLUDE_QUALITY_EVAL_ENV,
                {INCLUDE_QUALITY_EVAL_ENV: "sometimes"},
            )

    def test_activate_quality_stage_copies_and_merges_policy(self) -> None:
        policy = load_policy(DEFAULT_POLICY_PATH)
        original = copy.deepcopy(policy)

        active = activate_optional_stages(policy, ["quality_eval"])

        self.assertEqual(policy, original)
        self.assertEqual(active["required_suites"][-1], "quality_eval")
        self.assertEqual(active["suite_minimum_cases"]["quality_eval"], 6)
        self.assertEqual(active["suite_minimum_pass_rate"]["quality_eval"], 1.0)
        self.assertEqual(
            active["metric_thresholds"]["quality_eval.metrics.recall_at_k"],
            {"minimum": 0.8},
        )

    def test_activate_quality_stage_requires_policy_configuration(self) -> None:
        policy = load_policy(DEFAULT_POLICY_PATH)
        policy.pop("optional_stages")

        with self.assertRaisesRegex(ValueError, "quality_eval"):
            activate_optional_stages(policy, ["quality_eval"])

    def test_activate_optional_stages_leaves_unselected_legacy_policy_unchanged(
        self,
    ) -> None:
        policy = load_policy(DEFAULT_POLICY_PATH)
        policy.pop("optional_stages")

        self.assertEqual(activate_optional_stages(policy, []), policy)

    def test_activate_quality_stage_rejects_collisions_and_malformed_runner(
        self,
    ) -> None:
        duplicate_suite = load_policy(DEFAULT_POLICY_PATH)
        duplicate_suite["optional_stages"]["quality_eval"]["suite"] = "route_semantics"
        with self.assertRaisesRegex(ValueError, "already required"):
            activate_optional_stages(duplicate_suite, ["quality_eval"])

        duplicate_metric = load_policy(DEFAULT_POLICY_PATH)
        duplicate_metric["optional_stages"]["quality_eval"]["metric_thresholds"] = {
            "answer_pipeline_real_route.metrics.plan_contract_pass_rate": {"minimum": 1.0}
        }
        with self.assertRaisesRegex(ValueError, "duplicates metric thresholds"):
            activate_optional_stages(duplicate_metric, ["quality_eval"])

        malformed_runner = load_policy(DEFAULT_POLICY_PATH)
        malformed_runner["optional_stages"]["quality_eval"]["runner"] = {"top_k": 0}
        with self.assertRaisesRegex(ValueError, "runner"):
            activate_optional_stages(malformed_runner, ["quality_eval"])

    def test_default_offline_release_gate_passes(self) -> None:
        policy = load_policy(DEFAULT_POLICY_PATH)
        suite_names = list(policy["required_suites"])

        report = evaluate_gate(policy, run_suites(suite_names))

        self.assertTrue(report["passed"])
        self.assertEqual(report["metrics"]["case_count"], 39)
        self.assertEqual(report["metrics"]["passed_count"], 39)
        self.assertEqual(report["metrics"]["route_category_count"], 9)
        self.assertFalse(report["failed_checks"])

    def test_default_policy_configures_quality_eval_as_optional(self) -> None:
        policy = load_policy(DEFAULT_POLICY_PATH)

        self.assertNotIn("quality_eval", policy["required_suites"])
        stage = policy["optional_stages"]["quality_eval"]
        self.assertEqual(stage["suite"], "quality_eval")
        self.assertEqual(
            stage["runner"],
            {"profile": "eval_quality", "top_k": 6, "generate": True},
        )
        self.assertEqual(stage["suite_minimum_cases"], 6)
        self.assertEqual(stage["suite_minimum_pass_rate"], 1.0)
        self.assertEqual(
            stage["metric_thresholds"],
            {
                "quality_eval.metrics.recall_at_k": {"minimum": 0.8},
                "quality_eval.metrics.faithfulness": {"minimum": 0.8},
                "quality_eval.metrics.citation_accuracy": {"minimum": 0.8},
                "quality_eval.metrics.p95_latency_ms": {"maximum": 2000.0},
                "quality_eval.metrics.estimated_cost_usd": {"maximum": 1.0},
            },
        )

    def test_gate_fails_when_route_coverage_regresses(self) -> None:
        policy = load_policy(DEFAULT_POLICY_PATH)
        suite_reports = {
            "route_semantics": {
                **_suite_report(24),
                "category_counts": {"single_recipe": 24},
            },
            "answer_pipeline": _suite_report(3),
            "answer_pipeline_real_route": _real_route_suite_report(3),
            "generation_plans": _suite_report(3),
            "generation_prompts": _suite_report(6),
        }

        report = evaluate_gate(policy, suite_reports)

        self.assertFalse(report["passed"])
        failed_names = {item["name"] for item in report["failed_checks"]}
        self.assertIn("minimum_route_category_count", failed_names)
        self.assertIn("required_route_categories", failed_names)

    def test_gate_report_writes_json_and_markdown(self) -> None:
        policy = load_policy(DEFAULT_POLICY_PATH)
        suite_reports = {
            "route_semantics": {
                **_suite_report(24),
                "category_counts": {
                    category: 1 for category in policy["required_route_categories"]
                },
            },
            "answer_pipeline": _suite_report(3),
            "answer_pipeline_real_route": _real_route_suite_report(3),
            "generation_plans": _suite_report(3),
            "generation_prompts": _suite_report(6),
        }
        report = evaluate_gate(
            policy,
            suite_reports,
            generated_at="2026-06-11T00:00:00+00:00",
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            report_path, summary_path = write_report(report, temp_dir)

            self.assertTrue(report_path.exists())
            self.assertTrue(summary_path.exists())
            self.assertIn(
                '"passed": true',
                report_path.read_text(encoding="utf-8"),
            )
            self.assertIn(
                "status: PASS",
                summary_path.read_text(encoding="utf-8"),
            )

    def test_gate_fails_when_real_route_contract_metric_regresses(self) -> None:
        policy = load_policy(DEFAULT_POLICY_PATH)
        suite_reports = {
            "route_semantics": {
                **_suite_report(24),
                "category_counts": {
                    category: 1 for category in policy["required_route_categories"]
                },
            },
            "answer_pipeline": _suite_report(3),
            "answer_pipeline_real_route": _real_route_suite_report(3, metric_value=0.5),
            "generation_plans": _suite_report(3),
            "generation_prompts": _suite_report(6),
        }

        report = evaluate_gate(policy, suite_reports)

        self.assertFalse(report["passed"])
        failed_names = {item["name"] for item in report["failed_checks"]}
        self.assertIn(
            "metric_minimum:answer_pipeline_real_route.metrics.plan_contract_pass_rate",
            failed_names,
        )

    def test_gate_fails_when_real_route_contract_metric_is_missing(self) -> None:
        policy = load_policy(DEFAULT_POLICY_PATH)
        suite_reports = {
            "route_semantics": {
                **_suite_report(24),
                "category_counts": {
                    category: 1 for category in policy["required_route_categories"]
                },
            },
            "answer_pipeline": _suite_report(3),
            "answer_pipeline_real_route": _suite_report(3),
            "generation_plans": _suite_report(3),
            "generation_prompts": _suite_report(6),
        }

        report = evaluate_gate(policy, suite_reports)

        self.assertFalse(report["passed"])
        failed_names = {item["name"] for item in report["failed_checks"]}
        self.assertIn(
            "metric_available:answer_pipeline_real_route.metrics.plan_contract_pass_rate",
            failed_names,
        )

    def test_gate_supports_quality_metric_thresholds(self) -> None:
        policy = {
            **load_policy(DEFAULT_POLICY_PATH),
            "metric_thresholds": {
                "answer_pipeline.metrics.faithfulness": {"minimum": 0.8},
                "answer_pipeline.metrics.p95_latency_ms": {"maximum": 500.0},
            },
        }
        suite_reports = run_suites(list(policy["required_suites"]))
        suite_reports["answer_pipeline"]["metrics"] = {
            "faithfulness": 0.9,
            "p95_latency_ms": 250.0,
        }

        report = evaluate_gate(policy, suite_reports)

        self.assertTrue(report["passed"])
        quality_checks = [item for item in report["checks"] if item["name"].startswith("metric_")]
        self.assertEqual(len(quality_checks), 2)


if __name__ == "__main__":
    unittest.main()
