from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PackageCoverageRule:
    path: str
    branch_fail_under: float


@dataclass(frozen=True)
class RiskModuleCoverageRule:
    path: str
    combined_fail_under: float
    branch_fail_under: float


@dataclass(frozen=True)
class CoveragePolicy:
    package: PackageCoverageRule
    risk_modules: tuple[RiskModuleCoverageRule, ...]


@dataclass(frozen=True)
class CoverageCounts:
    covered_lines: int
    num_statements: int
    covered_branches: int
    num_branches: int

    @property
    def combined_percent(self) -> float:
        total = self.num_statements + self.num_branches
        if total == 0:
            raise ValueError("coverage counts contain no statements or branches")
        return 100.0 * (self.covered_lines + self.covered_branches) / total

    @property
    def branch_percent(self) -> float:
        if self.num_branches == 0:
            raise ValueError("coverage counts contain no branch data")
        return 100.0 * self.covered_branches / self.num_branches


@dataclass(frozen=True)
class CoverageRuleResult:
    kind: str
    path: str
    counts: CoverageCounts
    branch_fail_under: float
    combined_fail_under: float | None = None

    @property
    def branch_percent(self) -> float:
        return self.counts.branch_percent

    @property
    def combined_percent(self) -> float:
        return self.counts.combined_percent

    @property
    def passed(self) -> bool:
        combined_passed = (
            self.combined_fail_under is None or self.combined_percent >= self.combined_fail_under
        )
        return combined_passed and self.branch_percent >= self.branch_fail_under


@dataclass(frozen=True)
class CoverageEvaluation:
    results: tuple[CoverageRuleResult, ...]

    @property
    def passed(self) -> bool:
        return all(result.passed for result in self.results)
