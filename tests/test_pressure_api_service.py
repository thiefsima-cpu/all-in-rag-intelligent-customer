from __future__ import annotations

import io
import json
import subprocess
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from scripts.pressure_api_service import (
    DEFAULT_PRESSURE_SCENARIO,
    ModelMetrics,
    PressureCheck,
    PressureMetrics,
    PressureReport,
    PressureScenario,
    PressureThresholds,
    RetrievalMetrics,
    SseMetrics,
    TraceMetrics,
    _parse_args,
    build_pressure_report,
    default_pressure_scenario,
    default_pressure_thresholds,
    main,
    run_pressure_test,
)


def _metrics(
    *,
    requests: int = 10,
    completed_requests: int = 10,
    rejected_requests: int = 0,
    p95_latency_ms: float = 100.0,
    throughput_rps: float = 20.0,
    trace_dropped_events: int = 0,
    trace_failed_events: int = 0,
    retrieval_degraded_rate: float = 0.0,
    degraded_source_counts: dict[str, int] | None = None,
) -> PressureMetrics:
    return PressureMetrics(
        requests=requests,
        workers=2,
        completed_requests=completed_requests,
        rejected_requests=rejected_requests,
        total_duration_ms=500.0,
        throughput_rps=throughput_rps,
        avg_latency_ms=80.0,
        p95_latency_ms=p95_latency_ms,
        trace=TraceMetrics(
            dropped_events=trace_dropped_events,
            queued_events=0,
            written_events=completed_requests,
            failed_events=trace_failed_events,
            closed=True,
            max_queue_size=32,
            async_enabled=True,
        ),
        sse=SseMetrics(),
        model=ModelMetrics(
            p95_latency_ms=25.0,
            input_tokens=100,
            output_tokens=50,
            estimated_cost_usd=0.001,
            degraded_rate=0.0,
        ),
        retrieval=RetrievalMetrics(
            degraded_count=round(completed_requests * retrieval_degraded_rate),
            degraded_rate=retrieval_degraded_rate,
            degraded_source_counts=degraded_source_counts or {},
            max_single_source_degraded_rate=retrieval_degraded_rate,
        ),
    )


class PressureApiServiceTests(unittest.TestCase):
    def test_threshold_equality_passes_for_maximum_and_minimum_limits(self) -> None:
        report = build_pressure_report(
            scenario=PressureScenario(
                name="boundary",
                requests=10,
                workers=2,
                answer_delay_ms=20.0,
                trace_delay_ms=0.0,
                trace_queue_size=32,
                max_concurrent_answers=4,
                answer_acquire_timeout_seconds=0.25,
            ),
            metrics=_metrics(
                requests=10,
                completed_requests=10,
                rejected_requests=0,
                p95_latency_ms=250.0,
                throughput_rps=10.0,
            ),
            thresholds=PressureThresholds(
                max_rejection_rate=0.0,
                max_p95_latency_ms=250.0,
                min_completed_requests=10,
                min_throughput_rps=10.0,
                max_trace_dropped_events=0,
                max_trace_failed_events=0,
                max_retrieval_degraded_rate=0.0,
            ),
        )

        payload = report.to_dict()
        self.assertEqual(payload["status"], "pass")
        self.assertTrue(all(check["status"] == "pass" for check in payload["checks"]))

    def test_threshold_failures_identify_the_failed_check_names(self) -> None:
        report = build_pressure_report(
            scenario=PressureScenario(
                name="failure",
                requests=10,
                workers=2,
                answer_delay_ms=20.0,
                trace_delay_ms=0.0,
                trace_queue_size=32,
                max_concurrent_answers=4,
                answer_acquire_timeout_seconds=0.25,
            ),
            metrics=_metrics(
                requests=10,
                completed_requests=8,
                rejected_requests=2,
                p95_latency_ms=400.0,
                trace_dropped_events=1,
            ),
            thresholds=PressureThresholds(
                max_rejection_rate=0.0,
                max_p95_latency_ms=250.0,
                min_completed_requests=10,
                max_trace_dropped_events=0,
            ),
        )

        payload = report.to_dict()
        failed_names = {check["name"] for check in payload["checks"] if check["status"] == "fail"}
        self.assertEqual(payload["status"], "fail")
        self.assertIn("rejection_rate", failed_names)
        self.assertIn("p95_latency_ms", failed_names)
        self.assertIn("completed_requests", failed_names)
        self.assertIn("trace_dropped_events", failed_names)

    def test_warning_thresholds_produce_warn_without_failures(self) -> None:
        report = build_pressure_report(
            scenario=PressureScenario(
                name="retrieval-warning",
                requests=100,
                workers=4,
                answer_delay_ms=20.0,
                trace_delay_ms=0.0,
                trace_queue_size=32,
                max_concurrent_answers=4,
                answer_acquire_timeout_seconds=0.25,
            ),
            metrics=_metrics(
                requests=100,
                completed_requests=100,
                retrieval_degraded_rate=0.02,
                degraded_source_counts={"vector": 2},
            ),
            thresholds=PressureThresholds(
                warn_retrieval_degraded_rate=0.01,
                max_retrieval_degraded_rate=0.05,
                max_single_source_degraded_rate=0.03,
            ),
        )

        payload = report.to_dict()
        self.assertEqual(payload["status"], "warn")
        self.assertIn(
            {
                "name": "retrieval_degraded_rate",
                "status": "warn",
                "actual": 0.02,
                "operator": "<=",
                "limit": 0.01,
                "message": "Retrieval degraded rate exceeded the warning budget.",
            },
            payload["checks"],
        )

    def test_report_status_prefers_fail_over_warn_over_pass(self) -> None:
        report = build_pressure_report(
            scenario=PressureScenario(
                name="fail-wins",
                requests=100,
                workers=4,
                answer_delay_ms=20.0,
                trace_delay_ms=0.0,
                trace_queue_size=32,
                max_concurrent_answers=4,
                answer_acquire_timeout_seconds=0.25,
            ),
            metrics=_metrics(
                requests=100,
                completed_requests=100,
                p95_latency_ms=500.0,
                retrieval_degraded_rate=0.02,
                degraded_source_counts={"vector": 2},
            ),
            thresholds=PressureThresholds(
                max_p95_latency_ms=250.0,
                warn_retrieval_degraded_rate=0.01,
                max_retrieval_degraded_rate=0.05,
            ),
        )

        self.assertEqual(report.to_dict()["status"], "fail")

    def test_report_exit_code_is_nonzero_only_for_fail(self) -> None:
        scenario = default_pressure_scenario(requests=1, workers=1)
        metrics = _metrics(requests=1, completed_requests=1)
        thresholds = default_pressure_thresholds(scenario)

        for status, expected in (("pass", 0), ("warn", 0), ("fail", 1)):
            with self.subTest(status=status):
                report = PressureReport(
                    scenario=scenario,
                    metrics=metrics,
                    thresholds=thresholds,
                    checks=[
                        PressureCheck(
                            name="exit_contract",
                            status=status,
                            actual=True,
                            operator="is",
                            limit=True,
                            message="Exercise the process exit contract.",
                        )
                    ],
                )
                self.assertEqual(report.status, status)
                self.assertEqual(report.exit_code, expected)

    def test_report_json_contract_uses_structured_sections(self) -> None:
        report = build_pressure_report(
            scenario=PressureScenario(
                name="json-contract",
                requests=10,
                workers=2,
                answer_delay_ms=20.0,
                trace_delay_ms=0.0,
                trace_queue_size=32,
                max_concurrent_answers=4,
                answer_acquire_timeout_seconds=0.25,
            ),
            metrics=_metrics(),
            thresholds=PressureThresholds(max_rejection_rate=0.0),
        )

        payload = report.to_dict()
        self.assertEqual(payload["schema_version"], 1)
        self.assertEqual(
            set(payload),
            {"schema_version", "scenario", "status", "metrics", "thresholds", "checks"},
        )
        self.assertIn("trace", payload["metrics"])
        self.assertIn("model", payload["metrics"])
        self.assertIn("retrieval", payload["metrics"])
        self.assertNotIn("trace_stats", payload)
        self.assertNotIn("requests", payload)

    def test_saturation_run_reports_admission_rejections_and_balanced_accounting(
        self,
    ) -> None:
        report = run_pressure_test(
            scenario_name="api_concurrency_saturation",
            requests=12,
            workers=4,
            answer_delay_ms=50.0,
            trace_delay_ms=10.0,
            trace_queue_size=1,
            max_concurrent_answers=1,
            answer_acquire_timeout_seconds=0.01,
        )

        payload = report.to_dict()
        metrics = payload["metrics"]
        self.assertEqual(payload["scenario"]["name"], "api_concurrency_saturation")
        self.assertGreater(metrics["completed_requests"], 0)
        self.assertGreater(metrics["rejected_requests"], 0)
        self.assertEqual(
            metrics["completed_requests"] + metrics["rejected_requests"],
            payload["scenario"]["requests"],
        )
        self.assertIn(payload["status"], {"pass", "warn", "fail"})
        self.assertTrue(any(check["name"] == "request_accounting" for check in payload["checks"]))

    def test_default_run_returns_new_report_contract(self) -> None:
        report = run_pressure_test(
            requests=8,
            workers=2,
            answer_delay_ms=5.0,
            trace_delay_ms=0.0,
            trace_queue_size=8,
            max_concurrent_answers=2,
            answer_acquire_timeout_seconds=0.25,
        )

        payload = report.to_dict()
        self.assertEqual(payload["schema_version"], 1)
        self.assertEqual(payload["scenario"]["name"], "api_concurrency_baseline")
        self.assertEqual(payload["metrics"]["requests"], 8)
        self.assertEqual(payload["metrics"]["rejected_requests"], 0)
        self.assertIn(payload["status"], {"pass", "warn", "fail"})
        self.assertIn("max_rejection_rate", payload["thresholds"])

    def test_default_scenario_has_one_cross_platform_baseline(self) -> None:
        scenario = default_pressure_scenario()

        self.assertEqual(scenario, DEFAULT_PRESSURE_SCENARIO)
        self.assertEqual(scenario.requests, 200)
        self.assertEqual(scenario.workers, scenario.max_concurrent_answers)
        self.assertEqual(scenario.workers, 4)
        self.assertEqual(scenario.answer_delay_ms, 20.0)
        self.assertEqual(scenario.trace_delay_ms, 0.0)
        self.assertEqual(scenario.trace_queue_size, 32)
        self.assertEqual(scenario.answer_acquire_timeout_seconds, 0.25)

    def test_cli_parser_reads_defaults_from_canonical_scenario(self) -> None:
        args = _parse_args([])

        self.assertEqual(args.scenario_name, DEFAULT_PRESSURE_SCENARIO.name)
        self.assertEqual(args.requests, DEFAULT_PRESSURE_SCENARIO.requests)
        self.assertEqual(args.workers, DEFAULT_PRESSURE_SCENARIO.workers)
        self.assertEqual(args.answer_delay_ms, DEFAULT_PRESSURE_SCENARIO.answer_delay_ms)
        self.assertEqual(args.trace_delay_ms, DEFAULT_PRESSURE_SCENARIO.trace_delay_ms)
        self.assertEqual(args.trace_queue_size, DEFAULT_PRESSURE_SCENARIO.trace_queue_size)
        self.assertEqual(
            args.max_concurrent_answers,
            DEFAULT_PRESSURE_SCENARIO.max_concurrent_answers,
        )
        self.assertEqual(
            args.answer_acquire_timeout_seconds,
            DEFAULT_PRESSURE_SCENARIO.answer_acquire_timeout_seconds,
        )

    def test_main_returns_one_and_preserves_json_for_failed_report(self) -> None:
        output = io.StringIO()
        with redirect_stdout(output):
            exit_code = main(
                [
                    "--json",
                    "--scenario-name",
                    "model_call_budget",
                    "--requests",
                    "1",
                    "--workers",
                    "1",
                    "--answer-delay-ms",
                    "0",
                    "--trace-delay-ms",
                    "0",
                    "--synthetic-model-latency-ms",
                    "1001",
                ]
            )

        self.assertEqual(exit_code, 1)
        self.assertEqual(json.loads(output.getvalue())["status"], "fail")

    def test_main_returns_zero_after_human_pass_report(self) -> None:
        output = io.StringIO()
        with redirect_stdout(output):
            exit_code = main(
                [
                    "--scenario-name",
                    "model_call_budget",
                    "--requests",
                    "1",
                    "--workers",
                    "1",
                    "--answer-delay-ms",
                    "0",
                    "--trace-delay-ms",
                    "0",
                ]
            )

        self.assertEqual(exit_code, 0)
        self.assertIn("Status: pass", output.getvalue())

    def test_script_process_exits_one_and_emits_failed_json(self) -> None:
        project_root = Path(__file__).resolve().parents[1]
        completed = subprocess.run(
            [
                sys.executable,
                str(project_root / "scripts" / "pressure_api_service.py"),
                "--json",
                "--scenario-name",
                "model_call_budget",
                "--requests",
                "1",
                "--workers",
                "1",
                "--answer-delay-ms",
                "0",
                "--trace-delay-ms",
                "0",
                "--synthetic-model-latency-ms",
                "1001",
            ],
            cwd=project_root,
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(completed.returncode, 1, completed.stderr)
        self.assertEqual(json.loads(completed.stdout)["status"], "fail")

    def test_default_run_is_a_healthy_repeatable_baseline(self) -> None:
        payload = run_pressure_test().to_dict()

        self.assertEqual(payload["status"], "pass")
        self.assertEqual(payload["scenario"], DEFAULT_PRESSURE_SCENARIO.to_dict())
        self.assertEqual(payload["metrics"]["completed_requests"], 200)
        self.assertEqual(payload["metrics"]["rejected_requests"], 0)
        self.assertEqual(payload["metrics"]["trace"]["dropped_events"], 0)
        accounting = next(
            check for check in payload["checks"] if check["name"] == "request_accounting"
        )
        self.assertEqual(accounting["status"], "pass")
        self.assertIs(accounting["actual"], True)

    def test_retrieval_degraded_budget_can_warn_without_live_dependencies(self) -> None:
        report = run_pressure_test(
            scenario_name="retrieval_degraded_budget",
            requests=120,
            workers=2,
            answer_delay_ms=1.0,
            trace_delay_ms=0.0,
            trace_queue_size=8,
            max_concurrent_answers=2,
            answer_acquire_timeout_seconds=0.25,
            retrieval_degraded_every=40,
            retrieval_degraded_source="vector",
        )

        payload = report.to_dict()
        self.assertEqual(payload["scenario"]["name"], "retrieval_degraded_budget")
        self.assertEqual(payload["metrics"]["retrieval"]["degraded_count"], 3)
        self.assertEqual(
            payload["metrics"]["retrieval"]["degraded_source_counts"],
            {"vector": 3},
        )
        self.assertEqual(payload["status"], "warn")

    def test_retrieval_degraded_budget_fails_when_single_source_limit_is_exceeded(self) -> None:
        report = run_pressure_test(
            scenario_name="retrieval_degraded_budget",
            requests=100,
            workers=2,
            answer_delay_ms=1.0,
            trace_delay_ms=0.0,
            trace_queue_size=8,
            max_concurrent_answers=2,
            answer_acquire_timeout_seconds=0.25,
            retrieval_degraded_every=20,
            retrieval_degraded_source="vector",
        )

        payload = report.to_dict()
        failed_names = {check["name"] for check in payload["checks"] if check["status"] == "fail"}
        self.assertEqual(payload["scenario"]["name"], "retrieval_degraded_budget")
        self.assertEqual(payload["metrics"]["retrieval"]["degraded_count"], 5)
        self.assertEqual(payload["status"], "fail")
        self.assertIn("single_source_retrieval_degraded_rate", failed_names)

    def test_model_call_budget_reports_synthetic_latency_tokens_and_cost(self) -> None:
        report = run_pressure_test(
            scenario_name="model_call_budget",
            requests=4,
            workers=2,
            answer_delay_ms=1.0,
            trace_delay_ms=0.0,
            trace_queue_size=8,
            max_concurrent_answers=2,
            answer_acquire_timeout_seconds=0.25,
            synthetic_model_latency_ms=35.0,
            synthetic_input_tokens_per_request=100,
            synthetic_output_tokens_per_request=50,
            input_cost_per_million_tokens=2.0,
            output_cost_per_million_tokens=4.0,
        )

        payload = report.to_dict()
        self.assertEqual(payload["scenario"]["name"], "model_call_budget")
        self.assertEqual(payload["metrics"]["model"]["p95_latency_ms"], 35.0)
        self.assertEqual(payload["metrics"]["model"]["input_tokens"], 400)
        self.assertEqual(payload["metrics"]["model"]["output_tokens"], 200)
        self.assertEqual(payload["metrics"]["model"]["estimated_cost_usd"], 0.0016)
        self.assertEqual(payload["status"], "pass")

    def test_model_call_budget_fails_when_synthetic_budget_exceeds_fixed_thresholds(self) -> None:
        report = run_pressure_test(
            scenario_name="model_call_budget",
            requests=1,
            workers=1,
            answer_delay_ms=1.0,
            trace_delay_ms=0.0,
            trace_queue_size=8,
            max_concurrent_answers=2,
            answer_acquire_timeout_seconds=0.25,
            synthetic_model_latency_ms=999999.0,
            synthetic_input_tokens_per_request=999999,
            synthetic_output_tokens_per_request=999999,
            input_cost_per_million_tokens=2.0,
            output_cost_per_million_tokens=4.0,
        )

        payload = report.to_dict()
        failed_names = {check["name"] for check in payload["checks"] if check["status"] == "fail"}
        self.assertEqual(payload["scenario"]["name"], "model_call_budget")
        self.assertEqual(payload["status"], "fail")
        self.assertIn("model_p95_latency_ms", failed_names)
        self.assertIn("tokens_per_request", failed_names)
        self.assertIn("estimated_cost_usd", failed_names)

    def test_sse_runner_capacity_records_terminal_events_without_http(self) -> None:
        report = run_pressure_test(
            scenario_name="sse_runner_capacity",
            requests=6,
            workers=3,
            answer_delay_ms=50.0,
            trace_delay_ms=0.0,
            trace_queue_size=8,
            max_concurrent_answers=1,
            answer_acquire_timeout_seconds=0.01,
        )

        payload = report.to_dict()
        sse = payload["metrics"]["sse"]
        self.assertEqual(payload["scenario"]["name"], "sse_runner_capacity")
        self.assertEqual(sse["attempted_streams"], 6)
        self.assertEqual(sse["done_events"], 6)
        self.assertEqual(sse["done_event_rate"], 1.0)
        self.assertGreaterEqual(sse["rate_limited_error_events"], 1)
        self.assertEqual(sse["unfinished_streams"], 0)
        self.assertTrue(any(check["name"] == "done_event_rate" for check in payload["checks"]))


if __name__ == "__main__":
    unittest.main()
