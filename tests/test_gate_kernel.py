from __future__ import annotations

import json
import math
from dataclasses import FrozenInstanceError, dataclass
from fractions import Fraction
from inspect import Parameter, signature
from pathlib import Path

import numpy as np
import pytest

import scripts.gates as gates
from scripts.gates import (
    GateCheckResult,
    GateCheckStatus,
    GateEvaluation,
    GateFailureType,
    aggregate_checks,
    json_safe,
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
                "passed": True,
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
                "passed": False,
                "failure_type": "quality-regression",
                "code": "QUALITY_TOO_LOW",
                "expected": 0.8,
                "actual": 0.7,
                "duration_ms": 1.235,
            },
        ),
        (
            GateCheckResult.block_check("database", code="DATABASE_UNAVAILABLE"),
            {
                "name": "database",
                "status": "blocked",
                "passed": False,
                "failure_type": None,
                "code": "DATABASE_UNAVAILABLE",
                "expected": None,
                "actual": None,
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


def test_block_check_signature_is_restricted_to_name_and_keyword_only_code() -> None:
    parameters = signature(GateCheckResult.block_check).parameters

    assert list(parameters) == ["name", "code"]
    assert parameters["name"].kind is Parameter.POSITIONAL_OR_KEYWORD
    assert parameters["code"].kind is Parameter.KEYWORD_ONLY
    assert parameters["code"].default is Parameter.empty


def test_gate_check_result_defaults_match_public_contract() -> None:
    result = GateCheckResult(name="default", status=GateCheckStatus.BLOCKED)

    assert result.failure_type is None
    assert result.code == ""
    assert result.expected is None
    assert result.actual is None
    assert result.duration_ms == 0.0


def test_pass_check_accepts_expected_and_actual_without_code() -> None:
    result = GateCheckResult.pass_check("documents", expected=">=1", actual=12)

    assert result.to_dict() == {
        "name": "documents",
        "status": "passed",
        "passed": True,
        "failure_type": None,
        "code": "",
        "expected": ">=1",
        "actual": 12,
        "duration_ms": 0.0,
    }


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


def test_numeric_threshold_check_accepts_finite_arbitrary_precision_integer() -> None:
    actual = 10**1000

    result = numeric_threshold_check("huge-count", actual, minimum=actual, maximum=actual)

    assert result.status is GateCheckStatus.PASSED
    assert result.actual == actual


def test_numeric_threshold_check_rejects_non_finite_numpy_real() -> None:
    result = numeric_threshold_check("numpy-metric", np.float32(np.inf), maximum=1.0)

    assert result.status is GateCheckStatus.FAILED
    assert result.code == "METRIC_NOT_FINITE"


def test_numeric_threshold_check_accepts_finite_arbitrary_precision_non_integral_real() -> None:
    actual = Fraction(10**1000, 3)

    result = numeric_threshold_check("huge-ratio", actual, minimum=actual, maximum=actual)

    assert result.status is GateCheckStatus.PASSED
    assert result.actual == actual


def test_numeric_threshold_check_preserves_custom_failure_type() -> None:
    result = numeric_threshold_check(
        "quality",
        0.5,
        minimum=0.9,
        failure_type=GateFailureType.QUALITY_REGRESSION,
    )

    assert result.status is GateCheckStatus.FAILED
    assert result.failure_type is GateFailureType.QUALITY_REGRESSION


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
    assert list(evaluation.failure_type_counts) == [
        "dependency-unavailable",
        "quality-regression",
    ]


def test_aggregate_checks_with_all_passed_checks_passes_without_failures() -> None:
    evaluation = aggregate_checks(
        [
            GateCheckResult.pass_check("database", code="READY"),
            GateCheckResult.pass_check("quality", code="WITHIN_THRESHOLD"),
        ]
    )

    assert evaluation.passed is True
    assert evaluation.failure_type_counts == {}


def test_aggregate_checks_with_only_blocked_check_has_no_failure_type() -> None:
    evaluation = aggregate_checks([GateCheckResult.block_check("database", code="NOT_READY")])

    assert evaluation.passed is False
    assert evaluation.failure_type_counts == {}


def test_gate_dataclasses_are_frozen() -> None:
    check = GateCheckResult.pass_check("ready", code="OK")
    evaluation = aggregate_checks([check])

    with pytest.raises(FrozenInstanceError):
        check.code = "CHANGED"
    with pytest.raises(FrozenInstanceError):
        evaluation.passed = False


def test_gate_enum_values_and_public_exports_are_exact() -> None:
    assert {status.name: status.value for status in GateCheckStatus} == {
        "PASSED": "passed",
        "FAILED": "failed",
        "BLOCKED": "blocked",
    }
    assert {failure_type.name: failure_type.value for failure_type in GateFailureType} == {
        "CONFIGURATION_ERROR": "configuration-error",
        "DEPENDENCY_UNAVAILABLE": "dependency-unavailable",
        "JUDGE_UNAVAILABLE": "judge-unavailable",
        "CONTRACT_REGRESSION": "contract-regression",
        "QUALITY_REGRESSION": "quality-regression",
        "COVERAGE_REGRESSION": "coverage-regression",
        "BUDGET_REGRESSION": "budget-regression",
        "GATE_ERROR": "gate-error",
    }
    assert gates.__all__ == [
        "aggregate_checks",
        "numeric_threshold_check",
        "GateCheckResult",
        "GateCheckStatus",
        "GateEvaluation",
        "GateFailureType",
        "json_safe",
        "write_json_report",
    ]
    assert {name: getattr(gates, name) for name in gates.__all__} == {
        "aggregate_checks": aggregate_checks,
        "numeric_threshold_check": numeric_threshold_check,
        "GateCheckResult": GateCheckResult,
        "GateCheckStatus": GateCheckStatus,
        "GateEvaluation": GateEvaluation,
        "GateFailureType": GateFailureType,
        "json_safe": json_safe,
        "write_json_report": write_json_report,
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
        "immutable_statuses": frozenset({GateCheckStatus.BLOCKED}),
    }
    original_nested = report["nested"]
    original_checks = list(report["checks"])
    original_statuses = set(report["statuses"])
    original_immutable_statuses = report["immutable_statuses"]
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
    assert payload["immutable_statuses"] == ["blocked"]
    assert output_path.read_bytes().endswith(b"\n")
    assert report["nested"] is original_nested
    assert report["checks"] == original_checks
    assert report["statuses"] == original_statuses
    assert report["immutable_statuses"] is original_immutable_statuses


@pytest.mark.parametrize(
    ("actual", "expected_actual"),
    [
        (np.float32(1.5), 1.5),
        (np.int64(2), 2),
        (Fraction(1, 2), 0.5),
        (Fraction(10**1000, 3), str(Fraction(10**1000, 3))),
    ],
)
def test_write_json_report_serializes_supported_numeric_gate_values_end_to_end(
    tmp_path: Path, actual: object, expected_actual: object
) -> None:
    check = numeric_threshold_check("numeric", actual, minimum=0)
    evaluation = aggregate_checks([check])
    output_path = tmp_path / "numeric.json"

    write_json_report(evaluation, output_path)

    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload["passed"] is True
    assert payload["checks"][0]["actual"] == expected_actual


@pytest.mark.parametrize(
    ("actual", "expected_actual"),
    [(math.nan, "nan"), (math.inf, "inf"), (-math.inf, "-inf"), (np.float32(np.inf), "inf")],
)
def test_write_json_report_normalizes_non_finite_gate_values(
    tmp_path: Path, actual: float, expected_actual: str
) -> None:
    check = numeric_threshold_check("numeric", actual, maximum=1)
    output_path = tmp_path / "non-finite.json"

    write_json_report(aggregate_checks([check]), output_path)

    report_text = output_path.read_text(encoding="utf-8")
    payload = json.loads(report_text)
    assert payload["checks"][0]["code"] == "METRIC_NOT_FINITE"
    assert payload["checks"][0]["actual"] == expected_actual
    assert "NaN" not in report_text
    assert "Infinity" not in report_text


def test_json_safe_stringifies_mapping_keys() -> None:
    source = {("scope", 1): {2: "value"}}

    result = json_safe(source)

    assert result == {"('scope', 1)": {"2": "value"}}
    assert source == {("scope", 1): {2: "value"}}


def test_json_safe_sorts_set_and_frozenset_output() -> None:
    assert json_safe({100, -1, 2}) == [-1, 2, 100]
    assert json_safe(frozenset({"quality", "budget", "contract"})) == [
        "budget",
        "contract",
        "quality",
    ]
