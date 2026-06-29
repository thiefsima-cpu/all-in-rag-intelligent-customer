from __future__ import annotations

import copy
import json
import os
import re
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.release_gate import (
    DEFAULT_POLICY_PATH,
    INCLUDE_QUALITY_EVAL_ENV,
    _environment_flag,
    _run_quality_eval,
    activate_optional_stages,
    evaluate_gate,
    load_policy,
    main,
    run_release_gate,
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


def _quality_metrics() -> dict:
    return {
        "case_count": 6,
        "pass_rate": 1.0,
        "recall_at_k": 0.8,
        "faithfulness": 0.8,
        "citation_accuracy": 0.8,
        "p95_latency_ms": 2000.0,
        "estimated_cost_usd": 1.0,
    }


def _quality_suite_report() -> dict:
    return {
        "case_count": 6,
        "passed_count": 6,
        "metrics": _quality_metrics(),
        "results": [{"query": str(index), "passed": True} for index in range(6)],
        "failures": [],
    }


def _passing_reports_for_policy(policy: dict) -> dict:
    return {
        "route_semantics": {
            **_suite_report(24),
            "category_counts": {category: 1 for category in policy["required_route_categories"]},
        },
        "answer_pipeline": _suite_report(3),
        "answer_pipeline_real_route": _real_route_suite_report(3),
        "generation_plans": _suite_report(3),
        "generation_prompts": _suite_report(6),
        "quality_eval": _quality_suite_report(),
    }


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
        malformed_optional_stages = load_policy(DEFAULT_POLICY_PATH)
        malformed_optional_stages["optional_stages"] = []
        with self.assertRaisesRegex(ValueError, "optional_stages"):
            activate_optional_stages(malformed_optional_stages, ["quality_eval"])

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

        malformed_thresholds = load_policy(DEFAULT_POLICY_PATH)
        malformed_thresholds["optional_stages"]["quality_eval"]["metric_thresholds"] = []
        with self.assertRaisesRegex(ValueError, "metric thresholds"):
            activate_optional_stages(malformed_thresholds, ["quality_eval"])

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

    def test_real_route_suite_does_not_hide_planner_attribute_errors(self) -> None:
        with patch("rag_modules.query_understanding.planning.service.log_failure") as log_failure:
            reports = run_suites(["answer_pipeline_real_route"])

        self.assertFalse(reports["answer_pipeline_real_route"]["failures"])
        log_failure.assert_not_called()

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

    def test_quality_runner_normalizes_structured_eval_report(self) -> None:
        eval_report = {
            "metrics": _quality_metrics(),
            "results": [{"query": str(index), "passed": True} for index in range(6)],
            "failures": [],
            "profile": {"name": "eval_quality"},
        }
        stage = load_policy(DEFAULT_POLICY_PATH)["optional_stages"]["quality_eval"]

        with patch("scripts.eval_queries.evaluate_queries", return_value=eval_report) as evaluate:
            report = _run_quality_eval(stage)

        evaluate.assert_called_once_with(
            top_k=6,
            generate=True,
            profile="eval_quality",
        )
        self.assertEqual(report["case_count"], 6)
        self.assertEqual(report["passed_count"], 6)
        self.assertEqual(report["metrics"]["recall_at_k"], 0.8)
        self.assertEqual(report["profile"], {"name": "eval_quality"})

    def test_run_release_gate_includes_quality_suite_only_when_requested(self) -> None:
        policy = load_policy(DEFAULT_POLICY_PATH)
        suite_reports = _passing_reports_for_policy(policy)

        with tempfile.TemporaryDirectory() as temp_dir:
            with patch("scripts.release_gate.run_suites", return_value=suite_reports) as run:
                report = run_release_gate(
                    output_dir=temp_dir,
                    include_quality_eval=True,
                )

        suite_names = run.call_args.args[0]
        self.assertIn("quality_eval", suite_names)
        self.assertIn("quality_eval", run.call_args.kwargs["runners"])
        self.assertEqual(report["included_optional_stages"], ["quality_eval"])
        self.assertEqual(report["metrics"]["suite_count"], 6)
        self.assertEqual(report["metrics"]["case_count"], 45)
        self.assertTrue(report["passed"])

    def test_run_release_gate_default_does_not_register_quality_runner(self) -> None:
        policy = load_policy(DEFAULT_POLICY_PATH)
        suite_reports = _passing_reports_for_policy(policy)
        suite_reports.pop("quality_eval")

        with tempfile.TemporaryDirectory() as temp_dir:
            with patch("scripts.release_gate.run_suites", return_value=suite_reports) as run:
                report = run_release_gate(output_dir=temp_dir)

        self.assertNotIn("quality_eval", run.call_args.args[0])
        self.assertNotIn("quality_eval", run.call_args.kwargs["runners"])
        self.assertEqual(report["included_optional_stages"], [])
        self.assertEqual(report["metrics"]["case_count"], 39)

    def test_quality_runner_failure_becomes_failed_suite_report(self) -> None:
        def fail_quality_eval() -> dict:
            raise RuntimeError("quality backend unavailable")

        reports = run_suites(
            ["quality_eval"],
            runners={"quality_eval": fail_quality_eval},
        )

        self.assertIn(
            "RuntimeError: quality backend unavailable",
            reports["quality_eval"]["suite_error"],
        )

    def test_run_release_gate_policy_error_includes_policy_path(self) -> None:
        policy = load_policy(DEFAULT_POLICY_PATH)
        policy["optional_stages"]["quality_eval"]["runner"] = {}

        with tempfile.TemporaryDirectory() as temp_dir:
            policy_path = Path(temp_dir) / "release_gate.json"
            policy_path.write_text(json.dumps(policy), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, re.escape(str(policy_path.resolve()))):
                run_release_gate(
                    policy_path=policy_path,
                    output_dir=temp_dir,
                    include_quality_eval=True,
                )

    def test_run_release_gate_rejects_malformed_threshold_rule_before_suites(self) -> None:
        policy = load_policy(DEFAULT_POLICY_PATH)
        policy["optional_stages"]["quality_eval"]["metric_thresholds"] = {
            "quality_eval.metrics.recall_at_k": []
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            policy_path = Path(temp_dir) / "release_gate.json"
            policy_path.write_text(json.dumps(policy), encoding="utf-8")
            with (
                patch("scripts.release_gate.run_suites") as run,
                self.assertRaisesRegex(ValueError, re.escape(str(policy_path.resolve()))),
            ):
                run_release_gate(
                    policy_path=policy_path,
                    output_dir=temp_dir,
                    include_quality_eval=True,
                )

        run.assert_not_called()

    def test_run_release_gate_wraps_malformed_top_k_with_policy_path(self) -> None:
        policy = load_policy(DEFAULT_POLICY_PATH)
        policy["optional_stages"]["quality_eval"]["runner"]["top_k"] = {"value": 6}

        with tempfile.TemporaryDirectory() as temp_dir:
            policy_path = Path(temp_dir) / "release_gate.json"
            policy_path.write_text(json.dumps(policy), encoding="utf-8")
            with (
                patch("scripts.release_gate.run_suites") as run,
                self.assertRaisesRegex(ValueError, re.escape(str(policy_path.resolve()))),
            ):
                run_release_gate(
                    policy_path=policy_path,
                    output_dir=temp_dir,
                    include_quality_eval=True,
                )

        run.assert_not_called()

    def test_quality_thresholds_pass_at_boundaries_and_fail_outside_them(self) -> None:
        policy = activate_optional_stages(load_policy(DEFAULT_POLICY_PATH), ["quality_eval"])
        boundary_report = evaluate_gate(policy, _passing_reports_for_policy(policy))
        self.assertTrue(boundary_report["passed"])

        failing_values = {
            "recall_at_k": 0.79,
            "faithfulness": 0.79,
            "citation_accuracy": 0.79,
            "p95_latency_ms": 2000.1,
            "estimated_cost_usd": 1.01,
        }
        for metric_name, failing_value in failing_values.items():
            with self.subTest(metric=metric_name):
                reports = _passing_reports_for_policy(policy)
                reports["quality_eval"]["metrics"][metric_name] = failing_value
                report = evaluate_gate(policy, reports)
                self.assertFalse(report["passed"])
                self.assertTrue(
                    any(metric_name in check["name"] for check in report["failed_checks"])
                )

    def test_gate_reports_non_numeric_quality_metric_as_failed_check(self) -> None:
        policy = activate_optional_stages(load_policy(DEFAULT_POLICY_PATH), ["quality_eval"])
        reports = _passing_reports_for_policy(policy)
        reports["quality_eval"]["metrics"]["recall_at_k"] = "unknown"

        report = evaluate_gate(policy, reports)

        self.assertFalse(report["passed"])
        self.assertIn(
            "metric_numeric:quality_eval.metrics.recall_at_k",
            {item["name"] for item in report["failed_checks"]},
        )

    def test_gate_reports_non_finite_quality_metric_as_failed_check(self) -> None:
        policy = activate_optional_stages(load_policy(DEFAULT_POLICY_PATH), ["quality_eval"])
        reports = _passing_reports_for_policy(policy)
        reports["quality_eval"]["metrics"]["recall_at_k"] = "Infinity"

        report = evaluate_gate(policy, reports)

        self.assertFalse(report["passed"])
        self.assertIn(
            "metric_numeric:quality_eval.metrics.recall_at_k",
            {item["name"] for item in report["failed_checks"]},
        )

    def test_main_enables_quality_eval_from_environment(self) -> None:
        with (
            patch.dict(os.environ, {INCLUDE_QUALITY_EVAL_ENV: "true"}, clear=True),
            patch.object(sys, "argv", ["release_gate.py", "--json"]),
            patch(
                "scripts.release_gate.run_release_gate",
                return_value={"passed": True},
            ) as run,
        ):
            exit_code = main()

        self.assertEqual(exit_code, 0)
        self.assertTrue(run.call_args.kwargs["include_quality_eval"])

    def test_main_cli_flag_enables_quality_eval(self) -> None:
        with (
            patch.dict(os.environ, {}, clear=True),
            patch.object(
                sys,
                "argv",
                ["release_gate.py", "--include-quality-eval", "--json"],
            ),
            patch(
                "scripts.release_gate.run_release_gate",
                return_value={"passed": True},
            ) as run,
        ):
            exit_code = main()

        self.assertEqual(exit_code, 0)
        self.assertTrue(run.call_args.kwargs["include_quality_eval"])

    def test_main_rejects_invalid_quality_environment_value(self) -> None:
        with (
            patch.dict(os.environ, {INCLUDE_QUALITY_EVAL_ENV: "sometimes"}, clear=True),
            patch.object(sys, "argv", ["release_gate.py", "--json"]),
            patch("scripts.release_gate.run_release_gate") as run,
            self.assertRaises(SystemExit) as raised,
        ):
            main()

        self.assertEqual(raised.exception.code, 2)
        run.assert_not_called()

    def test_gate_summary_lists_included_optional_stages(self) -> None:
        policy = activate_optional_stages(load_policy(DEFAULT_POLICY_PATH), ["quality_eval"])
        report = evaluate_gate(policy, _passing_reports_for_policy(policy))
        report["included_optional_stages"] = ["quality_eval"]

        with tempfile.TemporaryDirectory() as temp_dir:
            _, summary_path = write_report(report, temp_dir)
            summary = summary_path.read_text(encoding="utf-8")

        self.assertIn("optional_stages: quality_eval", summary)
        self.assertIn("| quality_eval | 6 | 6 | 1.0000 |", summary)

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
