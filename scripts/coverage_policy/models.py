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
