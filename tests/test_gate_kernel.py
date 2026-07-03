from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path

import pytest

from scripts.gates import (
    GateCheckResult,
    GateCheckStatus,
    GateFailureType,
    aggregate_checks,
    numeric_threshold_check,
    write_json_report,
)


@pytest.mark.parametrize(
    ("result", "expected"),
    [
        (
            GateCheckResult.pass_check(
                "latency", code="METRIC_WITHIN_THRESHOLD", expected={"maximum": 10}, actual=9
            ),
            {
                "name": "latency",
                "status": "passed",
                "failure_type": None,
                "code": "METRIC_WITHIN_THRESHOLD",
                "expected": {"maximum": 10},
                "actual": 9,
                "duration_ms": 0.0,
            },
        ),
        (
            GateCheckResult.fail_check(
                "quality",
                failure_type=GateFailureType.QUALITY_REGRESSION,
                code="QUALITY_TOO_LOW",
                expected=0.8,
                actual=0.7,
                duration_ms=1.23456,
            ),
            {
                "name": "quality",
                "status": "failed",
                "failure_type": "quality-regression",
                "code": "QUALITY_TOO_LOW",
                "expected": 0.8,
                "actual": 0.7,
                "duration_ms": 1.235,
            },
        ),
        (
            GateCheckResult.block_check(
                "database", code="DATABASE_UNAVAILABLE", actual="connection refused"
            ),
            {
                "name": "database",
                "status": "blocked",
                "failure_type": None,
                "code": "DATABASE_UNAVAILABLE",
                "expected": None,
                "actual": "connection refused",
                "duration_ms": 0.0,
            },
        ),
    ],
)
def test_gate_check_result_factories_produce_stable_payloads(
    result: GateCheckResult, expected: dict[str, object]
) -> None:
    assert result.to_dict() == expected
    assert result.passed is (result.status is GateCheckStatus.PASSED)


@pytest.mark.parametrize(
    ("actual", "minimum", "maximum"),
    [(1, 1, None), (2.0, None, 2.0), (1.5, 1.5, 1.5)],
)
def test_numeric_threshold_check_accepts_inclusive_boundaries(
    actual: int | float, minimum: int | float | None, maximum: int | float | None
) -> None:
    result = numeric_threshold_check("metric", actual, minimum=minimum, maximum=maximum)

    assert result.status is GateCheckStatus.PASSED
    assert result.code == "METRIC_WITHIN_THRESHOLD"


@pytest.mark.parametrize(
    ("actual", "minimum", "maximum", "code"),
    [
        (0.9, 1.0, None, "METRIC_BELOW_MINIMUM"),
        (2.1, None, 2.0, "METRIC_ABOVE_MAXIMUM"),
    ],
)
def test_numeric_threshold_check_rejects_values_outside_threshold(
    actual: float, minimum: float | None, maximum: float | None, code: str
) -> None:
    result = numeric_threshold_check("metric", actual, minimum=minimum, maximum=maximum)

    assert result.status is GateCheckStatus.FAILED
    assert result.failure_type is GateFailureType.BUDGET_REGRESSION
    assert result.code == code


@pytest.mark.parametrize("actual", [True, False, "1", None, object()])
def test_numeric_threshold_check_rejects_bool_and_non_numeric_values(actual: object) -> None:
    result = numeric_threshold_check("metric", actual, minimum=0)

    assert result.status is GateCheckStatus.FAILED
    assert result.code == "METRIC_NOT_NUMERIC"


@pytest.mark.parametrize("actual", [math.nan, math.inf, -math.inf])
def test_numeric_threshold_check_rejects_non_finite_values(actual: float) -> None:
    result = numeric_threshold_check("metric", actual, maximum=10)

    assert result.status is GateCheckStatus.FAILED
    assert result.code == "METRIC_NOT_FINITE"


def test_aggregate_checks_counts_explicit_failed_types_but_not_blocked_checks() -> None:
    checks = (
        GateCheckResult.pass_check("passing", code="OK"),
        GateCheckResult.fail_check(
            "quality-1",
            failure_type=GateFailureType.QUALITY_REGRESSION,
            code="LOW_QUALITY",
        ),
        GateCheckResult.fail_check(
            "dependency",
            failure_type=GateFailureType.DEPENDENCY_UNAVAILABLE,
            code="MISSING_DEPENDENCY",
        ),
        GateCheckResult.fail_check(
            "quality-2",
            failure_type=GateFailureType.QUALITY_REGRESSION,
            code="LOW_QUALITY",
        ),
        GateCheckResult.block_check("blocked", code="NOT_RUN"),
    )

    evaluation = aggregate_checks(check for check in checks)

    assert evaluation.checks == checks
    assert evaluation.passed is False
    assert evaluation.failure_type_counts == {
        "dependency-unavailable": 1,
        "quality-regression": 2,
    }


@dataclass(frozen=True)
class NestedReport:
    status: GateCheckStatus
    values: tuple[GateFailureType, ...]


def test_write_json_report_recursively_serializes_without_mutating_input(tmp_path: Path) -> None:
    report = {
        "nested": NestedReport(
            status=GateCheckStatus.BLOCKED,
            values=(GateFailureType.GATE_ERROR, GateFailureType.CONTRACT_REGRESSION),
        ),
        "checks": [GateCheckResult.pass_check("ready", code="OK")],
        "statuses": {GateCheckStatus.PASSED, GateCheckStatus.FAILED},
    }
    original_nested = report["nested"]
    original_checks = list(report["checks"])
    original_statuses = set(report["statuses"])
    output_path = tmp_path / "reports" / "gate.json"

    returned_path = write_json_report(report, output_path)

    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert returned_path == output_path
    assert payload["nested"] == {
        "status": "blocked",
        "values": ["gate-error", "contract-regression"],
    }
    assert payload["checks"][0]["status"] == "passed"
    assert set(payload["statuses"]) == {"passed", "failed"}
    assert output_path.read_bytes().endswith(b"\n")
    assert report["nested"] is original_nested
    assert report["checks"] == original_checks
    assert report["statuses"] == original_statuses
