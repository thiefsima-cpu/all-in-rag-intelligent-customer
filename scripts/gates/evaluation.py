from __future__ import annotations

import math
from collections import Counter
from collections.abc import Iterable
from numbers import Real

from .models import GateCheckResult, GateCheckStatus, GateEvaluation, GateFailureType


def numeric_threshold_check(
    name: str,
    actual: object,
    minimum: Real | None = None,
    maximum: Real | None = None,
    failure_type: GateFailureType = GateFailureType.BUDGET_REGRESSION,
) -> GateCheckResult:
    expected = {"minimum": minimum, "maximum": maximum}

    if isinstance(actual, bool) or not isinstance(actual, Real):
        return GateCheckResult.fail_check(
            name,
            failure_type=failure_type,
            code="METRIC_NOT_NUMERIC",
            expected=expected,
            actual=actual,
        )

    if not math.isfinite(actual):
        return GateCheckResult.fail_check(
            name,
            failure_type=failure_type,
            code="METRIC_NOT_FINITE",
            expected=expected,
            actual=actual,
        )

    if minimum is not None and actual < minimum:
        return GateCheckResult.fail_check(
            name,
            failure_type=failure_type,
            code="METRIC_BELOW_MINIMUM",
            expected=expected,
            actual=actual,
        )

    if maximum is not None and actual > maximum:
        return GateCheckResult.fail_check(
            name,
            failure_type=failure_type,
            code="METRIC_ABOVE_MAXIMUM",
            expected=expected,
            actual=actual,
        )

    return GateCheckResult.pass_check(
        name,
        code="METRIC_WITHIN_THRESHOLD",
        expected=expected,
        actual=actual,
    )


def aggregate_checks(checks: Iterable[GateCheckResult]) -> GateEvaluation:
    materialized_checks = tuple(checks)
    failure_type_counts = Counter(
        check.failure_type.value
        for check in materialized_checks
        if check.status is GateCheckStatus.FAILED and check.failure_type is not None
    )
    return GateEvaluation(
        checks=materialized_checks,
        passed=all(check.status is GateCheckStatus.PASSED for check in materialized_checks),
        failure_type_counts=dict(sorted(failure_type_counts.items())),
    )
