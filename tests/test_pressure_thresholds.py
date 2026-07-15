from __future__ import annotations

import unittest

from scripts.pressure.metrics import (
    ModelMetrics,
    PressureMetrics,
    RetrievalMetrics,
    SseExecutorMetrics,
    SseMetrics,
    TraceMetrics,
)
from scripts.pressure.reporter import PressureReport, build_pressure_report
from scripts.pressure.scenario import PressureScenario, default_pressure_scenario
from scripts.pressure.thresholds import (
    PressureCheck,
    PressureThresholds,
    default_pressure_thresholds,
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
    sse: SseMetrics | None = None,
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
        sse=sse or SseMetrics(),
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


class PressureThresholdTests(unittest.TestCase):
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

    def test_sse_executor_checks_fail_for_capacity_accounting_and_idle_violations(
        self,
    ) -> None:
        scenario = PressureScenario(
            name="sse_runner_capacity",
            requests=3,
            workers=3,
            answer_delay_ms=20.0,
            trace_delay_ms=0.0,
            trace_queue_size=8,
            max_concurrent_answers=1,
            answer_acquire_timeout_seconds=0.01,
            stream_executor_max_workers=1,
            stream_executor_max_outstanding=2,
            stream_event_queue_max_size=4,
        )
        metrics = _metrics(
            requests=3,
            completed_requests=0,
            sse=SseMetrics(
                attempted_streams=3,
                done_events=3,
                error_events=1,
                rate_limited_error_events=1,
                executor=SseExecutorMetrics(
                    max_workers=1,
                    max_outstanding=2,
                    active=1,
                    queued=0,
                    peak_active=2,
                    peak_queued=2,
                    peak_outstanding=3,
                    rejected=2,
                ),
            ),
        )

        report = build_pressure_report(
            scenario=scenario,
            metrics=metrics,
            thresholds=default_pressure_thresholds(scenario),
        )
        failed_names = {
            check["name"] for check in report.to_dict()["checks"] if check["status"] == "fail"
        }

        self.assertTrue(
            {
                "sse_executor_peak_active",
                "sse_executor_peak_outstanding",
                "sse_executor_rejection_accounting",
                "sse_executor_idle",
            }.issubset(failed_names)
        )


if __name__ == "__main__":
    unittest.main()
