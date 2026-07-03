"""Command-line entry point for the offline release gate."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from scripts.offline_gate import (
    DEFAULT_OUTPUT_DIR,
    DEFAULT_POLICY_PATH,
    run_release_gate,
)


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")

    parser = argparse.ArgumentParser()
    parser.add_argument("--policy", default=str(DEFAULT_POLICY_PATH))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    report = run_release_gate(policy_path=args.policy, output_dir=args.output_dir)
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


if __name__ == "__main__":
    raise SystemExit(main())
