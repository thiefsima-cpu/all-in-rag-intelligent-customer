"""Policy evaluation for deterministic offline suite reports."""

from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any

from rag_modules.query_policy import get_query_policy
from scripts.gates import GateFailureType

_FAILURE_TYPE_ORDER = {
    failure_type.value: index for index, failure_type in enumerate(GateFailureType)
}


def _query_policy_metadata() -> dict[str, str]:
    return get_query_policy().metadata.to_dict()


def _report_failure_type(report: dict[str, Any]) -> GateFailureType | None:
    value = report.get("failure_type")
    if isinstance(value, GateFailureType):
        return value
    if value:
        try:
            return GateFailureType(str(value))
        except ValueError:
            return GateFailureType.GATE_ERROR
    if report.get("suite_error"):
        return GateFailureType.GATE_ERROR
    return None


def _suite_metrics(report: dict[str, Any]) -> dict[str, Any]:
    case_count = max(0, int(report.get("case_count") or 0))
    passed_count = min(case_count, max(0, int(report.get("passed_count") or 0)))
    failure_type = _report_failure_type(report)
    return {
        "case_count": case_count,
        "passed_count": passed_count,
        "failed_count": case_count - passed_count,
        "pass_rate": passed_count / case_count if case_count else 0.0,
        "suite_error": str(report.get("suite_error") or ""),
        "failure_type": failure_type.value if failure_type is not None else "",
    }


def _check(
    checks: list[dict[str, Any]],
    *,
    name: str,
    passed: bool,
    expected: Any,
    actual: Any,
    failure_type: GateFailureType,
) -> None:
    checks.append(
        {
            "name": name,
            "passed": bool(passed),
            "expected": expected,
            "actual": actual,
            "failure_type": "" if passed else failure_type.value,
        }
    )


def _suite_failure_type(
    suite_reports: dict[str, dict[str, Any]], suite_name: str
) -> GateFailureType | None:
    if suite_name not in suite_reports:
        return GateFailureType.GATE_ERROR
    return _report_failure_type(suite_reports.get(suite_name) or {})


def _required_suite_metrics(
    suite_reports: dict[str, dict[str, Any]], suite_name: str
) -> dict[str, Any]:
    metrics = _suite_metrics(suite_reports.get(suite_name) or {})
    if suite_name not in suite_reports:
        metrics["failure_type"] = GateFailureType.GATE_ERROR.value
    return metrics


def _resolve_metric(suite_reports: dict[str, dict[str, Any]], path: str) -> Any:
    parts = [part for part in str(path or "").split(".") if part]
    if len(parts) < 2:
        return None
    current: Any = suite_reports.get(parts[0])
    for part in parts[1:]:
        if not isinstance(current, dict):
            return None
        current = current.get(part)
    return current


def _metric_blocking_failure_type(
    suite_reports: dict[str, dict[str, Any]], path: str
) -> GateFailureType | None:
    suite_name = str(path or "").split(".", 1)[0]
    return _suite_failure_type(suite_reports, suite_name) if suite_name else None


def _evaluate_metric_thresholds(
    checks: list[dict[str, Any]],
    *,
    policy: dict[str, Any],
    suite_reports: dict[str, dict[str, Any]],
) -> None:
    for metric_path, threshold in dict(policy.get("metric_thresholds") or {}).items():
        limits = dict(threshold or {})
        actual = _resolve_metric(suite_reports, str(metric_path))
        if actual is None:
            blocking_failure_type = _metric_blocking_failure_type(suite_reports, str(metric_path))
            _check(
                checks,
                name=f"metric_available:{metric_path}",
                passed=False,
                expected="numeric_metric",
                actual=(
                    f"blocked_by:{blocking_failure_type.value}"
                    if blocking_failure_type is not None
                    else None
                ),
                failure_type=blocking_failure_type or GateFailureType.QUALITY_REGRESSION,
            )
            continue
        try:
            numeric_actual = float(actual)
        except (TypeError, ValueError):
            _check(
                checks,
                name=f"metric_numeric:{metric_path}",
                passed=False,
                expected="numeric_metric",
                actual=actual,
                failure_type=GateFailureType.QUALITY_REGRESSION,
            )
            continue
        if isinstance(actual, bool) or not math.isfinite(numeric_actual):
            _check(
                checks,
                name=f"metric_numeric:{metric_path}",
                passed=False,
                expected="finite_numeric_metric",
                actual=actual,
                failure_type=GateFailureType.QUALITY_REGRESSION,
            )
            continue
        if "minimum" in limits:
            minimum = float(limits["minimum"])
            _check(
                checks,
                name=f"metric_minimum:{metric_path}",
                passed=numeric_actual >= minimum,
                expected=f">={minimum}",
                actual=numeric_actual,
                failure_type=GateFailureType.QUALITY_REGRESSION,
            )
        if "maximum" in limits:
            maximum = float(limits["maximum"])
            _check(
                checks,
                name=f"metric_maximum:{metric_path}",
                passed=numeric_actual <= maximum,
                expected=f"<={maximum}",
                actual=numeric_actual,
                failure_type=GateFailureType.QUALITY_REGRESSION,
            )


def _evaluate_quality_dimension_minimums(
    checks: list[dict[str, Any]],
    *,
    policy: dict[str, Any],
    suite_reports: dict[str, dict[str, Any]],
) -> None:
    dimension_minimums = dict(policy.get("quality_dimension_minimum_cases") or {})
    if not dimension_minimums:
        return
    quality_metrics = dict((suite_reports.get("quality_eval") or {}).get("metrics") or {})
    raw_counts = quality_metrics.get("dimension_counts")
    dimension_counts = raw_counts if isinstance(raw_counts, dict) else {}
    failure_type = (
        _suite_failure_type(suite_reports, "quality_eval") or GateFailureType.QUALITY_REGRESSION
    )
    for dimension, raw_minimum in sorted(dimension_minimums.items()):
        dimension_name = str(dimension)
        minimum = max(0, int(raw_minimum))
        raw_actual = dimension_counts.get(dimension_name)
        actual: int | float | None = None
        passed = False
        if raw_actual is not None and not isinstance(raw_actual, bool):
            try:
                numeric_actual = float(raw_actual)
            except (TypeError, ValueError):
                pass
            else:
                if math.isfinite(numeric_actual):
                    actual = int(numeric_actual) if numeric_actual.is_integer() else numeric_actual
                    passed = numeric_actual >= 0 and numeric_actual >= minimum
        _check(
            checks,
            name=f"quality_dimension:{dimension_name}",
            passed=passed,
            expected=f">={minimum}",
            actual=actual,
            failure_type=failure_type,
        )


def _failure_type_counts(failed_checks: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for check in failed_checks:
        failure_type = str(check.get("failure_type") or "").strip()
        if failure_type:
            counts[failure_type] = counts.get(failure_type, 0) + 1
    return dict(
        sorted(
            counts.items(),
            key=lambda item: (_FAILURE_TYPE_ORDER.get(item[0], 99), item[0]),
        )
    )


def _aggregate_failure_type(
    suite_metrics: dict[str, dict[str, Any]],
) -> GateFailureType:
    failure_types = {item.get("failure_type") for item in suite_metrics.values()}
    if GateFailureType.DEPENDENCY_UNAVAILABLE.value in failure_types:
        return GateFailureType.DEPENDENCY_UNAVAILABLE
    if GateFailureType.GATE_ERROR.value in failure_types:
        return GateFailureType.GATE_ERROR
    return GateFailureType.QUALITY_REGRESSION


def evaluate_gate(
    policy: dict[str, Any],
    suite_reports: dict[str, dict[str, Any]],
    *,
    generated_at: str | None = None,
) -> dict[str, Any]:
    required_suites = [
        str(item) for item in (policy.get("required_suites") or []) if str(item).strip()
    ]
    minimum_cases = {
        str(key): max(0, int(value))
        for key, value in dict(policy.get("suite_minimum_cases") or {}).items()
    }
    minimum_pass_rates = {
        str(key): float(value)
        for key, value in dict(policy.get("suite_minimum_pass_rate") or {}).items()
    }
    suite_metrics = {
        suite_name: _required_suite_metrics(suite_reports, suite_name)
        for suite_name in required_suites
    }
    checks: list[dict[str, Any]] = []

    for suite_name in required_suites:
        metrics = suite_metrics[suite_name]
        suite_failure_type = _suite_failure_type(suite_reports, suite_name)
        _check(
            checks,
            name=f"suite_available:{suite_name}",
            passed=suite_name in suite_reports and not metrics["suite_error"],
            expected="available_without_error",
            actual=metrics["suite_error"]
            or ("available" if suite_name in suite_reports else "missing"),
            failure_type=suite_failure_type or GateFailureType.GATE_ERROR,
        )
        required_case_count = minimum_cases.get(suite_name, 0)
        _check(
            checks,
            name=f"suite_case_count:{suite_name}",
            passed=metrics["case_count"] >= required_case_count,
            expected=f">={required_case_count}",
            actual=metrics["case_count"],
            failure_type=suite_failure_type or GateFailureType.QUALITY_REGRESSION,
        )
        required_pass_rate = minimum_pass_rates.get(suite_name, 1.0)
        _check(
            checks,
            name=f"suite_pass_rate:{suite_name}",
            passed=metrics["pass_rate"] >= required_pass_rate,
            expected=f">={required_pass_rate}",
            actual=metrics["pass_rate"],
            failure_type=suite_failure_type or GateFailureType.QUALITY_REGRESSION,
        )

    total_cases = sum(item["case_count"] for item in suite_metrics.values())
    total_passed = sum(item["passed_count"] for item in suite_metrics.values())
    overall_pass_rate = total_passed / total_cases if total_cases else 0.0
    aggregate_failure_type = _aggregate_failure_type(suite_metrics)
    minimum_total_cases = max(0, int(policy.get("minimum_total_cases") or 0))
    _check(
        checks,
        name="minimum_total_cases",
        passed=total_cases >= minimum_total_cases,
        expected=f">={minimum_total_cases}",
        actual=total_cases,
        failure_type=aggregate_failure_type,
    )
    minimum_overall_pass_rate = float(policy.get("minimum_overall_pass_rate", 1.0))
    _check(
        checks,
        name="minimum_overall_pass_rate",
        passed=overall_pass_rate >= minimum_overall_pass_rate,
        expected=f">={minimum_overall_pass_rate}",
        actual=overall_pass_rate,
        failure_type=aggregate_failure_type,
    )

    route_report = suite_reports.get("route_semantics") or {}
    route_categories = dict(route_report.get("category_counts") or {})
    route_failure_type = (
        _suite_failure_type(suite_reports, "route_semantics") or GateFailureType.QUALITY_REGRESSION
    )
    minimum_route_category_count = max(0, int(policy.get("minimum_route_category_count") or 0))
    _check(
        checks,
        name="minimum_route_category_count",
        passed=len(route_categories) >= minimum_route_category_count,
        expected=f">={minimum_route_category_count}",
        actual=len(route_categories),
        failure_type=route_failure_type,
    )
    required_route_categories = {
        str(item) for item in (policy.get("required_route_categories") or []) if str(item).strip()
    }
    missing_route_categories = sorted(required_route_categories.difference(route_categories))
    _check(
        checks,
        name="required_route_categories",
        passed=not missing_route_categories,
        expected=sorted(required_route_categories),
        actual={"present": sorted(route_categories), "missing": missing_route_categories},
        failure_type=route_failure_type,
    )
    _evaluate_quality_dimension_minimums(checks, policy=policy, suite_reports=suite_reports)
    _evaluate_metric_thresholds(checks, policy=policy, suite_reports=suite_reports)

    failed_checks = [item for item in checks if not item["passed"]]
    failure_type_counts = _failure_type_counts(failed_checks)
    return {
        "generated_at": generated_at or datetime.now(timezone.utc).isoformat(),
        "passed": not failed_checks,
        "query_policy": _query_policy_metadata(),
        "metrics": {
            "suite_count": len(required_suites),
            "case_count": total_cases,
            "passed_count": total_passed,
            "failed_count": total_cases - total_passed,
            "pass_rate": overall_pass_rate,
            "route_category_count": len(route_categories),
            "failure_type_counts": failure_type_counts,
        },
        "failure_types": list(failure_type_counts),
        "suite_metrics": suite_metrics,
        "checks": checks,
        "failed_checks": failed_checks,
        "suite_reports": {
            suite_name: suite_reports.get(suite_name) or {} for suite_name in required_suites
        },
    }
