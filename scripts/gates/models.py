from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class GateCheckStatus(StrEnum):
    PASSED = "passed"
    FAILED = "failed"
    BLOCKED = "blocked"


class GateFailureType(StrEnum):
    CONFIGURATION_ERROR = "configuration-error"
    DEPENDENCY_UNAVAILABLE = "dependency-unavailable"
    JUDGE_UNAVAILABLE = "judge-unavailable"
    CONTRACT_REGRESSION = "contract-regression"
    QUALITY_REGRESSION = "quality-regression"
    COVERAGE_REGRESSION = "coverage-regression"
    BUDGET_REGRESSION = "budget-regression"
    GATE_ERROR = "gate-error"


@dataclass(frozen=True)
class GateCheckResult:
    name: str
    status: GateCheckStatus
    failure_type: GateFailureType | None = None
    code: str = ""
    expected: Any = None
    actual: Any = None
    duration_ms: float = 0.0

    @property
    def passed(self) -> bool:
        return self.status is GateCheckStatus.PASSED

    @classmethod
    def pass_check(
        cls,
        name: str,
        *,
        code: str = "",
        expected: Any = None,
        actual: Any = None,
        duration_ms: float = 0.0,
    ) -> GateCheckResult:
        return cls(
            name=name,
            status=GateCheckStatus.PASSED,
            failure_type=None,
            code=code,
            expected=expected,
            actual=actual,
            duration_ms=duration_ms,
        )

    @classmethod
    def fail_check(
        cls,
        name: str,
        *,
        failure_type: GateFailureType,
        code: str,
        expected: Any = None,
        actual: Any = None,
        duration_ms: float = 0.0,
    ) -> GateCheckResult:
        return cls(
            name=name,
            status=GateCheckStatus.FAILED,
            failure_type=failure_type,
            code=code,
            expected=expected,
            actual=actual,
            duration_ms=duration_ms,
        )

    @classmethod
    def block_check(
        cls,
        name: str,
        *,
        code: str,
    ) -> GateCheckResult:
        return cls(
            name=name,
            status=GateCheckStatus.BLOCKED,
            code=code,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status.value,
            "passed": self.passed,
            "failure_type": self.failure_type.value if self.failure_type is not None else None,
            "code": self.code,
            "expected": self.expected,
            "actual": self.actual,
            "duration_ms": round(self.duration_ms, 3),
        }


@dataclass(frozen=True)
class GateEvaluation:
    checks: tuple[GateCheckResult, ...]
    passed: bool
    failure_type_counts: dict[str, int]
