from __future__ import annotations

import re
import tomllib
from collections.abc import Mapping
from pathlib import Path

from .models import CoveragePolicy, PackageCoverageRule, RiskModuleCoverageRule


def normalize_policy_path(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError(f"{field_name} must be a non-empty relative POSIX path")
    path = value
    segments = path.split("/")
    if (
        "\\" in path
        or path.startswith("/")
        or re.match(r"^[A-Za-z]:", path)
        or any(token in path for token in ("*", "?", "[", "]"))
    ):
        raise ValueError(f"{field_name} must be a relative POSIX path without globs")
    if any(not segment or segment in {".", ".."} for segment in segments):
        raise ValueError(
            f"{field_name} must be a relative POSIX path without empty or dot segments"
        )
    return path


def _mapping(value: object, field_name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{field_name} must be a mapping")
    return value


def _threshold(mapping: Mapping[str, object], field_name: str) -> float:
    value = mapping.get(field_name)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field_name} must be numeric")
    threshold = float(value)
    if not 0.0 <= threshold <= 100.0:
        raise ValueError(f"{field_name} must be between 0 and 100")
    return threshold


def load_policy(path: Path) -> CoveragePolicy:
    payload = tomllib.loads(path.read_text(encoding="utf-8"))
    coverage = _mapping(payload["tool"]["graph_rag"]["coverage"], "coverage")
    package_payload = _mapping(coverage.get("package"), "package")
    package = PackageCoverageRule(
        path=normalize_policy_path(package_payload.get("path"), "package.path"),
        branch_fail_under=_threshold(package_payload, "branch_fail_under"),
    )
    raw_risk_modules = coverage.get("risk_modules")
    if not isinstance(raw_risk_modules, list) or not raw_risk_modules:
        raise ValueError("risk_modules must be a non-empty array")
    risk_modules: list[RiskModuleCoverageRule] = []
    seen: set[str] = set()
    for index, raw_rule in enumerate(raw_risk_modules):
        rule = _mapping(raw_rule, f"risk_modules[{index}]")
        risk_path = normalize_policy_path(rule.get("path"), f"risk_modules[{index}].path")
        if risk_path in seen:
            raise ValueError(f"duplicate risk module path: {risk_path}")
        seen.add(risk_path)
        risk_modules.append(
            RiskModuleCoverageRule(
                path=risk_path,
                combined_fail_under=_threshold(rule, "combined_fail_under"),
                branch_fail_under=_threshold(rule, "branch_fail_under"),
            )
        )
    return CoveragePolicy(package=package, risk_modules=tuple(risk_modules))
