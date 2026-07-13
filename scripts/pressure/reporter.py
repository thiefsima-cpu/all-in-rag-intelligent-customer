from __future__ import annotations

import json
from dataclasses import dataclass

from .metrics import PressureMetrics
from .scenario import PressureScenario
from .thresholds import (
    PressureCheck,
    PressureStatus,
    PressureThresholds,
    _evaluate_pressure_checks,
)


@dataclass(frozen=True)
class PressureReport:
    scenario: PressureScenario
    metrics: PressureMetrics
    thresholds: PressureThresholds
    checks: list[PressureCheck]
    schema_version: int = 1

    @property
    def status(self) -> PressureStatus:
        statuses = [check.status for check in self.checks]
        if "fail" in statuses:
            return "fail"
        if "warn" in statuses:
            return "warn"
        return "pass"

    @property
    def exit_code(self) -> int:
        return 1 if self.status == "fail" else 0

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "scenario": self.scenario.to_dict(),
            "status": self.status,
            "metrics": self.metrics.to_dict(),
            "thresholds": self.thresholds.to_dict(),
            "checks": [check.to_dict() for check in self.checks],
        }


def build_pressure_report(
    *,
    scenario: PressureScenario,
    metrics: PressureMetrics,
    thresholds: PressureThresholds,
) -> PressureReport:
    return PressureReport(
        scenario=scenario,
        metrics=metrics,
        thresholds=thresholds,
        checks=_evaluate_pressure_checks(metrics, thresholds),
    )


def print_human_report(report: PressureReport) -> None:
    payload = report.to_dict()
    scenario = payload["scenario"]
    metrics = payload["metrics"]
    thresholds = payload["thresholds"]
    checks = payload["checks"]
    print("Pressure report")
    print("---------------")
    print(f"Scenario: {scenario['name']}")
    print(f"Status: {payload['status']}")
    print(f"Requests: {scenario['requests']}")
    print(f"Workers: {scenario['workers']}")
    print(f"Completed requests: {metrics['completed_requests']}")
    print(f"Rejected requests: {metrics['rejected_requests']}")
    print(f"Rejection rate: {metrics['rejection_rate']}")
    print(f"Throughput (req/s): {metrics['throughput_rps']}")
    print(f"Average latency (ms): {metrics['avg_latency_ms']}")
    print(f"P95 latency (ms): {metrics['p95_latency_ms']}")
    print(f"Thresholds: {json.dumps(thresholds, ensure_ascii=False, sort_keys=True)}")
    print("Checks:")
    for check in checks:
        print(
            f"- {check['status']} {check['name']}: "
            f"{check['actual']} {check['operator']} {check['limit']} "
            f"({check['message']})"
        )


def print_json_report(report: PressureReport) -> None:
    print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
