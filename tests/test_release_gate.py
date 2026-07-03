from __future__ import annotations

import io
import json
import re
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.gates import GateFailureType
from scripts.offline_gate import (
    DEFAULT_POLICY_PATH,
    evaluate_gate,
    load_policy,
    required_quality_stage,
    run_quality_eval,
    run_release_gate,
    run_suites,
    write_report,
)
from scripts.offline_gate.policy import QualityRunnerSettings
from scripts.offline_gate.runners import OfflineSuiteFailure
from scripts.release_gate import main


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
        "case_count": 18,
        "pass_rate": 1.0,
        "recall_at_k": 0.8,
        "faithfulness": 0.8,
        "citation_accuracy": 0.8,
        "response_mode_accuracy": 1.0,
        "abstention_accuracy": 1.0,
        "response_mode_counts": {
            "clarification": 2,
            "constraint_conflict": 2,
            "grounded_answer": 12,
            "no_evidence": 2,
        },
        "dimension_counts": {
            "ambiguity": 2,
            "colloquial_zh": 4,
            "constraint_conflict": 2,
            "long_query": 4,
            "multi_hop": 3,
            "no_evidence": 2,
        },
        "fallback_rate": 0.0,
        "fallback_case_count": 0,
        "fallback_reasons": {},
        "retrieval_degradation_rate": 0.0,
        "retrieval_degraded_case_count": 0,
        "degraded_sources": [],
        "degraded_source_counts": {},
        "p95_latency_ms": 2000.0,
        "estimated_cost_usd": 1.0,
    }


def _quality_suite_report() -> dict:
    return {
        "case_count": 18,
        "passed_count": 18,
        "metrics": _quality_metrics(),
        "results": [{"query": str(index), "passed": True} for index in range(18)],
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
    def test_default_offline_release_gate_passes(self) -> None:
        policy = load_policy(DEFAULT_POLICY_PATH)
        report = evaluate_gate(policy, _passing_reports_for_policy(policy))

        self.assertTrue(report["passed"])
        self.assertEqual(report["metrics"]["case_count"], 57)
        self.assertEqual(report["metrics"]["passed_count"], 57)
        self.assertEqual(report["metrics"]["route_category_count"], 9)
        self.assertFalse(report["failed_checks"])

    def test_real_route_suite_does_not_hide_planner_attribute_errors(self) -> None:
        with patch("rag_modules.query_understanding.planning.service.log_failure") as log_failure:
            reports = run_suites(["answer_pipeline_real_route"])

        self.assertFalse(reports["answer_pipeline_real_route"]["failures"])
        log_failure.assert_not_called()

    def test_default_policy_requires_quality_eval(self) -> None:
        policy = load_policy(DEFAULT_POLICY_PATH)

        self.assertIn("quality_eval", policy["required_suites"])
        self.assertEqual(policy["minimum_total_cases"], 57)
        self.assertEqual(policy["suite_minimum_cases"]["quality_eval"], 18)
        self.assertEqual(policy["suite_minimum_pass_rate"]["quality_eval"], 1.0)
        self.assertEqual(
            policy["quality_dimension_minimum_cases"],
            {
                "ambiguity": 2,
                "colloquial_zh": 2,
                "constraint_conflict": 2,
                "long_query": 2,
                "multi_hop": 2,
                "no_evidence": 2,
            },
        )
        self.assertEqual(
            policy["suite_runners"]["quality_eval"],
            {"profile": "eval_quality", "top_k": 6, "generate": True},
        )
        self.assertEqual(
            policy["metric_thresholds"]["quality_eval.metrics.response_mode_accuracy"],
            {"minimum": 1.0},
        )
        self.assertEqual(
            policy["metric_thresholds"]["quality_eval.metrics.abstention_accuracy"],
            {"minimum": 1.0},
        )
        self.assertEqual(
            policy["metric_thresholds"]["quality_eval.metrics.citation_accuracy"],
            {"minimum": 0.8},
        )
        self.assertEqual(
            policy["metric_thresholds"]["quality_eval.metrics.fallback_rate"],
            {"maximum": 0.0},
        )
        self.assertEqual(
            policy["metric_thresholds"]["quality_eval.metrics.retrieval_degradation_rate"],
            {"maximum": 0.0},
        )

    def test_quality_runner_normalizes_structured_eval_report(self) -> None:
        eval_report = {
            "metrics": _quality_metrics(),
            "results": [{"query": str(index), "passed": True} for index in range(18)],
            "failures": [],
            "profile": {"name": "eval_quality"},
        }
        settings = required_quality_stage(load_policy(DEFAULT_POLICY_PATH))

        with patch(
            "scripts.eval_reporting.evaluate_offline_quality_queries",
            return_value=eval_report,
        ) as evaluate:
            report = run_quality_eval(settings)

        evaluate.assert_called_once_with(
            top_k=6,
            generate=True,
            profile="eval_quality",
        )
        self.assertEqual(report["case_count"], 18)
        self.assertEqual(report["passed_count"], 18)
        self.assertEqual(report["metrics"]["recall_at_k"], 0.8)
        self.assertEqual(report["profile"], {"name": "eval_quality"})

    def test_required_quality_stage_reads_suite_runner(self) -> None:
        policy = load_policy(DEFAULT_POLICY_PATH)

        settings = required_quality_stage(policy)

        self.assertEqual(
            settings,
            QualityRunnerSettings(profile="eval_quality", top_k=6, generate=True),
        )

    def test_required_quality_stage_rejects_missing_suite_runner(self) -> None:
        policy = load_policy(DEFAULT_POLICY_PATH)
        del policy["suite_runners"]["quality_eval"]

        with self.assertRaisesRegex(
            ValueError,
            "Required release-gate suite has no runner: quality_eval",
        ):
            required_quality_stage(policy)

    def test_required_quality_stage_rejects_malformed_suite_runner(self) -> None:
        invalid_runner_values = (
            {"profile": "", "top_k": 6, "generate": True},
            {"profile": "eval_quality", "top_k": 0, "generate": True},
            {"profile": "eval_quality", "top_k": True, "generate": True},
            {"profile": "eval_quality", "top_k": 6, "generate": "yes"},
        )
        for runner in invalid_runner_values:
            with self.subTest(runner=runner):
                policy = load_policy(DEFAULT_POLICY_PATH)
                policy["suite_runners"]["quality_eval"] = runner

                with self.assertRaisesRegex(
                    ValueError,
                    "Required release-gate suite has invalid runner settings: quality_eval",
                ):
                    required_quality_stage(policy)

    def test_run_release_gate_registers_required_quality_runner(self) -> None:
        policy = load_policy(DEFAULT_POLICY_PATH)
        suite_reports = _passing_reports_for_policy(policy)

        with tempfile.TemporaryDirectory() as temp_dir:
            with patch(
                "scripts.offline_gate.service.run_suites", return_value=suite_reports
            ) as run:
                report = run_release_gate(output_dir=temp_dir)

        suite_names = run.call_args.args[0]
        self.assertIn("quality_eval", suite_names)
        self.assertIn("quality_eval", run.call_args.kwargs["runners"])
        self.assertTrue(report["quality_eval_required"])
        self.assertEqual(
            set(report),
            {
                "generated_at",
                "passed",
                "query_policy",
                "metrics",
                "failure_types",
                "suite_metrics",
                "checks",
                "failed_checks",
                "suite_reports",
                "quality_eval_required",
                "policy_path",
                "report_path",
                "summary_path",
            },
        )
        self.assertEqual(report["metrics"]["suite_count"], 6)
        self.assertEqual(report["metrics"]["case_count"], 57)
        self.assertEqual(report["query_policy"]["policy_version"], "c9-default-policy-v1")
        self.assertEqual(report["query_policy"]["prompt_version"], "c9-default-prompts-v1")
        self.assertTrue(report["passed"])

    def test_quality_runner_failure_becomes_failed_suite_report(self) -> None:
        def fail_quality_eval() -> dict:
            raise RuntimeError("quality backend unavailable")

        reports = run_suites(
            ["quality_eval"],
            runners={"quality_eval": fail_quality_eval},
        )

        self.assertEqual(reports["quality_eval"]["failure_type"], "gate-error")
        self.assertNotIn("quality backend unavailable", json.dumps(reports["quality_eval"]))

    def test_run_suites_preserves_explicit_dependency_failure_type(self) -> None:
        def fail_quality_eval() -> dict:
            raise OfflineSuiteFailure(GateFailureType.DEPENDENCY_UNAVAILABLE)

        reports = run_suites(
            ["quality_eval"],
            runners={"quality_eval": fail_quality_eval},
        )

        self.assertEqual(reports["quality_eval"]["failure_type"], "dependency-unavailable")
        self.assertIn(
            "dependency-unavailable",
            {failure["failure_type"] for failure in reports["quality_eval"]["failures"]},
        )

    def test_run_release_gate_policy_error_includes_policy_path(self) -> None:
        policy = load_policy(DEFAULT_POLICY_PATH)
        policy["suite_runners"]["quality_eval"] = {}

        with tempfile.TemporaryDirectory() as temp_dir:
            policy_path = Path(temp_dir) / "release_gate.json"
            policy_path.write_text(json.dumps(policy), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, re.escape(str(policy_path.resolve()))):
                run_release_gate(
                    policy_path=policy_path,
                    output_dir=temp_dir,
                )

    def test_run_release_gate_rejects_malformed_threshold_rule_before_suites(self) -> None:
        policy = load_policy(DEFAULT_POLICY_PATH)
        policy["metric_thresholds"]["quality_eval.metrics.recall_at_k"] = []

        with tempfile.TemporaryDirectory() as temp_dir:
            policy_path = Path(temp_dir) / "release_gate.json"
            policy_path.write_text(json.dumps(policy), encoding="utf-8")
            with (
                patch("scripts.offline_gate.service.run_suites") as run,
                self.assertRaisesRegex(ValueError, re.escape(str(policy_path.resolve()))),
            ):
                run_release_gate(
                    policy_path=policy_path,
                    output_dir=temp_dir,
                )

        run.assert_not_called()

    def test_run_release_gate_wraps_malformed_top_k_with_policy_path(self) -> None:
        policy = load_policy(DEFAULT_POLICY_PATH)
        policy["suite_runners"]["quality_eval"]["top_k"] = {"value": 6}

        with tempfile.TemporaryDirectory() as temp_dir:
            policy_path = Path(temp_dir) / "release_gate.json"
            policy_path.write_text(json.dumps(policy), encoding="utf-8")
            with (
                patch("scripts.offline_gate.service.run_suites") as run,
                self.assertRaisesRegex(ValueError, re.escape(str(policy_path.resolve()))),
            ):
                run_release_gate(
                    policy_path=policy_path,
                    output_dir=temp_dir,
                )

        run.assert_not_called()

    def test_quality_thresholds_pass_at_boundaries_and_fail_outside_them(self) -> None:
        policy = load_policy(DEFAULT_POLICY_PATH)
        boundary_report = evaluate_gate(policy, _passing_reports_for_policy(policy))
        self.assertTrue(boundary_report["passed"])

        failing_values = {
            "recall_at_k": 0.79,
            "faithfulness": 0.79,
            "citation_accuracy": 0.79,
            "response_mode_accuracy": 0.99,
            "abstention_accuracy": 0.99,
            "fallback_rate": 0.01,
            "retrieval_degradation_rate": 0.01,
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

    def test_gate_fails_when_quality_dimension_coverage_regresses(self) -> None:
        policy = load_policy(DEFAULT_POLICY_PATH)
        reports = _passing_reports_for_policy(policy)
        reports["quality_eval"]["metrics"]["dimension_counts"]["no_evidence"] = 1

        report = evaluate_gate(policy, reports)

        self.assertFalse(report["passed"])
        failed = {item["name"]: item for item in report["failed_checks"]}
        self.assertEqual(failed["quality_dimension:no_evidence"]["expected"], ">=2")
        self.assertEqual(failed["quality_dimension:no_evidence"]["actual"], 1)

    def test_gate_marks_quality_threshold_failure_as_quality_regression(self) -> None:
        policy = load_policy(DEFAULT_POLICY_PATH)
        reports = _passing_reports_for_policy(policy)
        reports["quality_eval"]["metrics"]["recall_at_k"] = 0.79

        report = evaluate_gate(policy, reports)

        self.assertFalse(report["passed"])
        failed_checks = {item["name"]: item for item in report["failed_checks"]}
        check = failed_checks["metric_minimum:quality_eval.metrics.recall_at_k"]
        self.assertEqual(check["failure_type"], "quality-regression")
        self.assertEqual(report["failure_types"], ["quality-regression"])

    def test_gate_marks_dependency_unavailable_separately_from_quality_regression(self) -> None:
        policy = load_policy(DEFAULT_POLICY_PATH)
        reports = _passing_reports_for_policy(policy)
        reports["quality_eval"] = {
            "case_count": 0,
            "passed_count": 0,
            "results": [],
            "failures": [
                {
                    "suite_error": "ServiceUnavailable: Unable to connect to Neo4j",
                    "failure_type": "dependency-unavailable",
                }
            ],
            "suite_error": "ServiceUnavailable: Unable to connect to Neo4j",
            "failure_type": "dependency-unavailable",
        }

        report = evaluate_gate(policy, reports)

        self.assertFalse(report["passed"])
        self.assertIn("dependency-unavailable", report["failure_types"])
        failed_checks = {item["name"]: item for item in report["failed_checks"]}
        self.assertEqual(
            failed_checks["suite_available:quality_eval"]["failure_type"],
            "dependency-unavailable",
        )
        self.assertEqual(
            failed_checks["metric_available:quality_eval.metrics.recall_at_k"]["failure_type"],
            "dependency-unavailable",
        )
        self.assertNotIn(
            "quality-regression",
            {
                item["failure_type"]
                for item in report["failed_checks"]
                if item["name"].startswith("metric_")
            },
        )

    def test_gate_marks_missing_required_suite_as_gate_error(self) -> None:
        policy = load_policy(DEFAULT_POLICY_PATH)
        reports = _passing_reports_for_policy(policy)
        reports.pop("quality_eval")

        report = evaluate_gate(policy, reports)

        failed_checks = {item["name"]: item for item in report["failed_checks"]}
        self.assertEqual(
            failed_checks["suite_case_count:quality_eval"]["failure_type"],
            "gate-error",
        )
        self.assertEqual(
            failed_checks["metric_available:quality_eval.metrics.recall_at_k"]["failure_type"],
            "gate-error",
        )

    def test_gate_reports_non_numeric_quality_metric_as_failed_check(self) -> None:
        policy = load_policy(DEFAULT_POLICY_PATH)
        reports = _passing_reports_for_policy(policy)
        reports["quality_eval"]["metrics"]["recall_at_k"] = "unknown"

        report = evaluate_gate(policy, reports)

        self.assertFalse(report["passed"])
        self.assertIn(
            "metric_numeric:quality_eval.metrics.recall_at_k",
            {item["name"] for item in report["failed_checks"]},
        )

    def test_gate_reports_non_finite_quality_metric_as_failed_check(self) -> None:
        policy = load_policy(DEFAULT_POLICY_PATH)
        reports = _passing_reports_for_policy(policy)
        reports["quality_eval"]["metrics"]["recall_at_k"] = "Infinity"

        report = evaluate_gate(policy, reports)

        self.assertFalse(report["passed"])
        self.assertIn(
            "metric_numeric:quality_eval.metrics.recall_at_k",
            {item["name"] for item in report["failed_checks"]},
        )

    def test_main_rejects_retired_include_quality_eval_flag(self) -> None:
        with (
            patch.object(
                sys,
                "argv",
                ["release_gate.py", "--include-quality-eval", "--json"],
            ),
            patch(
                "scripts.release_gate.run_release_gate",
                return_value={"passed": True},
            ) as run,
            self.assertRaises(SystemExit) as raised,
        ):
            main()

        self.assertEqual(raised.exception.code, 2)
        run.assert_not_called()

    def test_main_writes_json_and_passes_only_supported_paths(self) -> None:
        report = {"passed": True}
        stdout = io.StringIO()
        with (
            patch.object(
                sys,
                "argv",
                ["release_gate.py", "--policy", "policy.json", "--output-dir", "out", "--json"],
            ),
            patch("scripts.release_gate.run_release_gate", return_value=report) as run,
            patch.object(sys, "stdout", stdout),
        ):
            exit_code = main()

        self.assertEqual(exit_code, 0)
        self.assertEqual(json.loads(stdout.getvalue()), report)
        run.assert_called_once_with(policy_path="policy.json", output_dir="out")

    def test_retired_compatibility_names_are_absent_from_gate_sources(self) -> None:
        source_paths = [Path("scripts/release_gate.py"), *Path("scripts/offline_gate").glob("*.py")]

        combined_source = "\n".join(path.read_text(encoding="utf-8") for path in source_paths)

        for retired_name in (
            "_environment_flag",
            "_legacy_optional_policy",
            "include-quality-eval",
            "include_quality_eval",
            "included_optional_stages",
            "activate_optional_stages",
            "INCLUDE_QUALITY_EVAL_ENV",
            "optional_stages",
            "scripts.release_policy",
            "release_policy",
        ):
            self.assertNotIn(retired_name, combined_source)

    def test_gate_summary_lists_required_quality_metrics(self) -> None:
        policy = load_policy(DEFAULT_POLICY_PATH)
        report = evaluate_gate(policy, _passing_reports_for_policy(policy))
        report["quality_eval_required"] = True

        with tempfile.TemporaryDirectory() as temp_dir:
            _, summary_path = write_report(report, temp_dir)
            summary = summary_path.read_text(encoding="utf-8")

        self.assertIn("quality_eval: required", summary)
        self.assertIn("policy_version: c9-default-policy-v1", summary)
        self.assertIn("prompt_version: c9-default-prompts-v1", summary)
        self.assertIn("citation_accuracy: 0.8000", summary)
        self.assertIn("response_mode_accuracy: 1.0000", summary)
        self.assertIn("abstention_accuracy: 1.0000", summary)
        self.assertIn("fallback_rate: 0.0000", summary)
        self.assertIn("retrieval_degradation_rate: 0.0000", summary)
        self.assertIn("degraded_sources: none", summary)

    def test_gate_summary_lists_failure_types(self) -> None:
        policy = load_policy(DEFAULT_POLICY_PATH)
        reports = _passing_reports_for_policy(policy)
        reports["quality_eval"] = {
            "case_count": 0,
            "passed_count": 0,
            "results": [],
            "failures": [],
            "suite_error": "ServiceUnavailable: Unable to connect to Neo4j",
            "failure_type": "dependency-unavailable",
        }
        report = evaluate_gate(policy, reports)

        with tempfile.TemporaryDirectory() as temp_dir:
            _, summary_path = write_report(report, temp_dir)
            summary = summary_path.read_text(encoding="utf-8")

        self.assertIn("failure_types: dependency-unavailable", summary)
        self.assertIn(
            "`suite_available:quality_eval` type `dependency-unavailable`",
            summary,
        )

    def test_gate_fails_when_route_coverage_regresses(self) -> None:
        policy = load_policy(DEFAULT_POLICY_PATH)
        suite_reports = _passing_reports_for_policy(policy)
        suite_reports["route_semantics"] = {
            **_suite_report(24),
            "category_counts": {"single_recipe": 24},
        }

        report = evaluate_gate(policy, suite_reports)

        self.assertFalse(report["passed"])
        failed_names = {item["name"] for item in report["failed_checks"]}
        self.assertIn("minimum_route_category_count", failed_names)
        self.assertIn("required_route_categories", failed_names)

    def test_gate_report_writes_json_and_markdown(self) -> None:
        policy = load_policy(DEFAULT_POLICY_PATH)
        suite_reports = _passing_reports_for_policy(policy)
        report = evaluate_gate(
            policy,
            suite_reports,
            generated_at="2026-06-11T00:00:00+00:00",
        )
        report["quality_eval_required"] = True

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
        suite_reports = _passing_reports_for_policy(policy)
        suite_reports["answer_pipeline_real_route"] = _real_route_suite_report(3, metric_value=0.5)

        report = evaluate_gate(policy, suite_reports)

        self.assertFalse(report["passed"])
        failed_names = {item["name"] for item in report["failed_checks"]}
        self.assertIn(
            "metric_minimum:answer_pipeline_real_route.metrics.plan_contract_pass_rate",
            failed_names,
        )

    def test_gate_fails_when_real_route_contract_metric_is_missing(self) -> None:
        policy = load_policy(DEFAULT_POLICY_PATH)
        suite_reports = _passing_reports_for_policy(policy)
        suite_reports["answer_pipeline_real_route"] = _suite_report(3)

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
        suite_reports = _passing_reports_for_policy(policy)
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
