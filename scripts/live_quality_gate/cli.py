"""Command-line interface for the live AI quality gate."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from scripts.gates import json_safe

from .models import DEFAULT_POLICY_PATH
from .reporter import DEFAULT_OUTPUT_DIR
from .service import LiveQualityGateConfigurationError, run_live_quality_gate


def main() -> int:
    """Run the live quality gate CLI."""

    _configure_utf8_stdio()
    parser = argparse.ArgumentParser(description="Run the live AI quality gate.")
    parser.add_argument("--policy", default=DEFAULT_POLICY_PATH)
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--json", action="store_true", dest="emit_json")
    parser.add_argument("--deterministic-only", action="store_true")
    args = parser.parse_args()

    try:
        report = run_live_quality_gate(
            policy_path=args.policy,
            output_dir=args.output_dir,
            deterministic_only=args.deterministic_only,
        )
    except LiveQualityGateConfigurationError:
        _print_safe_error(
            {
                "passed": False,
                "failure_type": "configuration-error",
                "code": "LIVE_QUALITY_CONFIGURATION_INVALID",
            }
        )
        return 2
    except Exception:
        _print_safe_error(
            {
                "passed": False,
                "failure_type": "gate-error",
                "code": "LIVE_QUALITY_EXECUTION_FAILED",
            }
        )
        return 2

    if args.emit_json:
        print(json.dumps(json_safe(report), ensure_ascii=False, sort_keys=True, allow_nan=False))
    else:
        _print_text_summary(report, output_dir=args.output_dir)

    return 0 if report.get("passed") is True else 1


def _configure_utf8_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8", errors="backslashreplace")


def _print_safe_error(payload: dict[str, object]) -> None:
    print(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, allow_nan=False),
        file=sys.stderr,
    )


def _print_text_summary(report: dict[str, object], *, output_dir: object) -> None:
    status = "passed" if report.get("passed") is True else "failed"
    print(f"Live quality gate {status}.")

    artifacts = report.get("artifacts")
    if isinstance(artifacts, dict):
        report_path = artifacts.get("report_json")
        summary_path = artifacts.get("summary_md")
        if report_path:
            print(f"Report: {Path(output_dir) / str(report_path)}")
        if summary_path:
            print(f"Summary: {Path(output_dir) / str(summary_path)}")


if __name__ == "__main__":
    raise SystemExit(main())
