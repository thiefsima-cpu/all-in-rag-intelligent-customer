"""Enforce package-specific branch coverage from a coverage.py JSON report."""

from __future__ import annotations

import argparse
import json
import sys
import tomllib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
DEFAULT_REPORT_PATH = ROOT_DIR / "coverage.json"
DEFAULT_CONFIG_PATH = ROOT_DIR / "pyproject.toml"


@dataclass(frozen=True)
class BranchCoverageResult:
    covered_branches: int
    num_branches: int

    @property
    def percent(self) -> float:
        return 100.0 * self.covered_branches / self.num_branches


def _required_non_negative_int(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{field_name} must be a non-negative integer")
    return value


def calculate_branch_coverage(
    payload: object,
    *,
    package: str,
) -> BranchCoverageResult:
    if not isinstance(payload, Mapping) or not isinstance(payload.get("files"), Mapping):
        raise ValueError("coverage report must contain a files mapping")
    normalized_prefix = package.replace("\\", "/").strip("/") + "/"
    matching = []
    for filename, file_payload in payload["files"].items():
        normalized_name = str(filename).replace("\\", "/").lstrip("./")
        if normalized_name.startswith(normalized_prefix):
            matching.append(file_payload)
    if not matching:
        raise ValueError(f"coverage report contains no matching files for {package}")

    covered = 0
    total = 0
    for file_payload in matching:
        if not isinstance(file_payload, Mapping) or not isinstance(
            file_payload.get("summary"), Mapping
        ):
            raise ValueError("matching file is missing a summary mapping")
        summary = file_payload["summary"]
        total += _required_non_negative_int(summary.get("num_branches"), "num_branches")
        covered += _required_non_negative_int(summary.get("covered_branches"), "covered_branches")
    if total == 0:
        raise ValueError(f"coverage report contains no branch data for {package}")
    if covered > total:
        raise ValueError("covered_branches cannot exceed num_branches")
    return BranchCoverageResult(covered_branches=covered, num_branches=total)


def load_threshold(path: Path) -> float:
    payload = tomllib.loads(path.read_text(encoding="utf-8"))
    value = payload["tool"]["graph_rag"]["coverage"]["rag_modules_branch_fail_under"]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("rag_modules_branch_fail_under must be numeric")
    threshold = float(value)
    if not 0.0 <= threshold <= 100.0:
        raise ValueError("rag_modules_branch_fail_under must be between 0 and 100")
    return threshold


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--coverage-json", type=Path, default=DEFAULT_REPORT_PATH)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH)
    parser.add_argument("--package", default="rag_modules")
    args = parser.parse_args(argv)
    try:
        payload = json.loads(args.coverage_json.read_text(encoding="utf-8"))
        threshold = load_threshold(args.config)
        result = calculate_branch_coverage(payload, package=args.package)
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        print(f"[ERROR] branch coverage gate: {exc}", file=sys.stderr)
        return 2

    status = "PASS" if result.percent >= threshold else "FAIL"
    print(
        f"[{status}] {args.package} branch coverage "
        f"{result.percent:.2f}% ({result.covered_branches}/{result.num_branches}); "
        f"required {threshold:.2f}%"
    )
    return 0 if status == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
