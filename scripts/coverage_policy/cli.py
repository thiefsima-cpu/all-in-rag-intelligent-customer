from __future__ import annotations

import argparse
import json
import sys
import tomllib
from collections.abc import Sequence
from pathlib import Path

from .evaluator import evaluate_policy
from .models import CoverageRuleResult
from .policy import load_policy
from .snapshot import CoverageSnapshot

ROOT_DIR = Path(__file__).resolve().parents[2]
DEFAULT_REPORT_PATH = ROOT_DIR / "coverage.json"
DEFAULT_CONFIG_PATH = ROOT_DIR / "pyproject.toml"


def _format_result(result: CoverageRuleResult) -> str:
    status = "PASS" if result.passed else "FAIL"
    branch = (
        f"branch {result.branch_percent:.2f}% "
        f"({result.counts.covered_branches}/{result.counts.num_branches}); "
        f"required {result.branch_fail_under:.2f}%"
    )
    if result.combined_fail_under is None:
        return f"[{status}] {result.kind} {result.path} {branch}"
    combined = (
        f"combined {result.combined_percent:.2f}% "
        f"({result.counts.covered_lines + result.counts.covered_branches}/"
        f"{result.counts.num_statements + result.counts.num_branches}); "
        f"required {result.combined_fail_under:.2f}%"
    )
    return f"[{status}] {result.kind} {result.path} {combined}; {branch}"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Enforce repository coverage policy.")
    parser.add_argument("--coverage-json", type=Path, default=DEFAULT_REPORT_PATH)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH)
    args = parser.parse_args(argv)
    try:
        policy = load_policy(args.config)
        snapshot = CoverageSnapshot.from_json(args.coverage_json)
        evaluation = evaluate_policy(policy, snapshot)
    except (
        OSError,
        KeyError,
        TypeError,
        ValueError,
        json.JSONDecodeError,
        tomllib.TOMLDecodeError,
    ) as exc:
        print(f"[ERROR] coverage policy: {exc}", file=sys.stderr)
        return 2
    for result in evaluation.results:
        print(_format_result(result))
    return 0 if evaluation.passed else 1
