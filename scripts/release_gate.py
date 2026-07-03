"""Command-line entry point for the offline release gate."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from scripts.release_policy import (
    DEFAULT_OUTPUT_DIR,
    DEFAULT_POLICY_PATH,
    FAILURE_TYPE_DEPENDENCY_UNAVAILABLE,
    FAILURE_TYPE_METRIC_REGRESSION,
    FAILURE_TYPE_SUITE_ERROR,
    FAILURE_TYPE_SUITE_REGRESSION,
    INCLUDE_QUALITY_EVAL_ENV,
    QUALITY_EVAL_STAGE,
    SUITE_RUNNERS,
    SuiteRunner,
    _environment_flag,
    _run_quality_eval,
    activate_optional_stages,
    evaluate_gate,
    load_policy,
    run_release_gate,
    run_suites,
    write_report,
)


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")

    parser = argparse.ArgumentParser()
    parser.add_argument("--policy", default=str(DEFAULT_POLICY_PATH))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--json", action="store_true")
    parser.add_argument(
        "--include-quality-eval",
        action="store_true",
        help=(
            "Compatibility flag for legacy policies that still define quality_eval "
            "as an optional stage. The default policy requires quality_eval."
        ),
    )
    args = parser.parse_args()

    try:
        environment_requested = _environment_flag(INCLUDE_QUALITY_EVAL_ENV)
    except ValueError as exc:
        parser.error(str(exc))

    report = run_release_gate(
        policy_path=args.policy,
        output_dir=args.output_dir,
        include_quality_eval=args.include_quality_eval or environment_requested,
    )
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        metrics = report["metrics"]
        status = "PASS" if report["passed"] else "FAIL"
        print(
            f"[{status}] offline release gate "
            f"cases={metrics['passed_count']}/{metrics['case_count']} "
            f"pass_rate={metrics['pass_rate']:.4f} "
            f"route_categories={metrics['route_category_count']}"
        )
        for suite_name, suite in report["suite_metrics"].items():
            print(
                f"  {suite_name}: "
                f"{suite['passed_count']}/{suite['case_count']} "
                f"pass_rate={suite['pass_rate']:.4f}"
            )
        for check in report["failed_checks"]:
            print(
                f"  failed_check={check['name']} "
                f"expected={check['expected']} actual={check['actual']}"
            )
        print(f"report={report['report_path']}")
        print(f"summary={report['summary_path']}")
    return 0 if report["passed"] else 1


__all__ = [
    "DEFAULT_OUTPUT_DIR",
    "DEFAULT_POLICY_PATH",
    "FAILURE_TYPE_DEPENDENCY_UNAVAILABLE",
    "FAILURE_TYPE_METRIC_REGRESSION",
    "FAILURE_TYPE_SUITE_ERROR",
    "FAILURE_TYPE_SUITE_REGRESSION",
    "INCLUDE_QUALITY_EVAL_ENV",
    "QUALITY_EVAL_STAGE",
    "SUITE_RUNNERS",
    "SuiteRunner",
    "_environment_flag",
    "_run_quality_eval",
    "activate_optional_stages",
    "evaluate_gate",
    "load_policy",
    "main",
    "run_release_gate",
    "run_suites",
    "write_report",
]


if __name__ == "__main__":
    raise SystemExit(main())
