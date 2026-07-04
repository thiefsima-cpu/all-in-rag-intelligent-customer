"""Command-line interface for the real-dependency integration gate."""

from __future__ import annotations

import argparse
import json
import sys

from scripts.gates import json_safe

from .models import DEFAULT_POLICY_PATH
from .reporter import DEFAULT_OUTPUT_DIR
from .service import IntegrationGateConfigurationError, run_integration_gate


def main() -> int:
    """Run the integration gate CLI."""

    _configure_utf8_stdio()
    parser = argparse.ArgumentParser(description="Run the real-dependency integration gate.")
    parser.add_argument("--policy", default=DEFAULT_POLICY_PATH)
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--json", action="store_true", dest="emit_json")
    args = parser.parse_args()

    try:
        report = run_integration_gate(policy_path=args.policy, output_dir=args.output_dir)
    except IntegrationGateConfigurationError:
        payload = {
            "passed": False,
            "failure_type": "gate-error",
            "code": "INTEGRATION_GATE_CONFIGURATION_INVALID",
        }
        print(
            json.dumps(payload, ensure_ascii=False, sort_keys=True, allow_nan=False),
            file=sys.stderr,
        )
        return 2

    if args.emit_json:
        print(json.dumps(json_safe(report), ensure_ascii=False, sort_keys=True, allow_nan=False))
    else:
        _print_text_summary(report)

    return 0 if report.get("passed") is True else 1


def _configure_utf8_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8", errors="backslashreplace")


def _print_text_summary(report: dict[str, object]) -> None:
    status = "passed" if report.get("passed") is True else "failed"
    print(f"Integration gate {status}.")

    artifacts = report.get("artifacts")
    if isinstance(artifacts, dict):
        report_path = artifacts.get("report_json")
        summary_path = artifacts.get("summary_md")
        if report_path:
            print(f"Report: {report_path}")
        if summary_path:
            print(f"Summary: {summary_path}")


if __name__ == "__main__":
    raise SystemExit(main())
