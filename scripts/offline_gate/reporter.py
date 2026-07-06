"""JSON and Markdown reporting for the offline release gate."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT_DIR = ROOT_DIR / "eval" / "reports" / "release_gate"


def _summary_metric_value(value: Any) -> str:
    if isinstance(value, float):
        return f"{value:.4f}"
    if isinstance(value, int) and not isinstance(value, bool):
        return str(value)
    if isinstance(value, list):
        values = [str(item).strip() for item in value if str(item).strip()]
        return ", ".join(values) if values else "none"
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False, sort_keys=True) if value else "none"
    if value is None:
        return "none"
    return str(value)


def _summary_lines(report: dict[str, Any]) -> list[str]:
    metrics = report.get("metrics") or {}
    status = "PASS" if report.get("passed") else "FAIL"
    query_policy = dict(report.get("query_policy") or {})
    failure_types = [str(item) for item in (report.get("failure_types") or []) if str(item)]
    failure_type_label = ", ".join(failure_types) if failure_types else "none"
    lines = [
        "# Offline Evaluation Release Gate",
        "",
        f"- status: {status}",
        f"- generated_at: {report.get('generated_at', '')}",
        f"- policy_version: {query_policy.get('policy_version', '')}",
        f"- prompt_version: {query_policy.get('prompt_version', '')}",
        "- quality_eval: required",
        f"- failure_types: {failure_type_label}",
        f"- suites: {metrics.get('suite_count', 0)}",
        f"- cases: {metrics.get('passed_count', 0)}/{metrics.get('case_count', 0)}",
        f"- pass_rate: {metrics.get('pass_rate', 0.0):.4f}",
        f"- route_categories: {metrics.get('route_category_count', 0)}",
        "",
        "## Suites",
        "",
        "| Suite | Passed | Cases | Pass rate |",
        "| --- | ---: | ---: | ---: |",
    ]
    for suite_name, suite in (report.get("suite_metrics") or {}).items():
        lines.append(
            f"| {suite_name} | {suite.get('passed_count', 0)} | "
            f"{suite.get('case_count', 0)} | {suite.get('pass_rate', 0.0):.4f} |"
        )
    quality_report = dict((report.get("suite_reports") or {}).get("quality_eval") or {})
    quality_metrics = dict(quality_report.get("metrics") or {})
    if quality_metrics:
        lines.extend(
            [
                "",
                "## Quality Metrics",
                "",
                f"- citation_accuracy: {_summary_metric_value(quality_metrics.get('citation_accuracy'))}",
                "- response_mode_accuracy: "
                f"{_summary_metric_value(quality_metrics.get('response_mode_accuracy'))}",
                "- abstention_accuracy: "
                f"{_summary_metric_value(quality_metrics.get('abstention_accuracy'))}",
                f"- fallback_rate: {_summary_metric_value(quality_metrics.get('fallback_rate'))}",
                "- retrieval_degradation_rate: "
                f"{_summary_metric_value(quality_metrics.get('retrieval_degradation_rate'))}",
                f"- degraded_sources: {_summary_metric_value(quality_metrics.get('degraded_sources'))}",
            ]
        )
    failed_checks = report.get("failed_checks") or []
    if failed_checks:
        lines.extend(["", "## Failed Checks", ""])
        for item in failed_checks:
            failure_type = str(item.get("failure_type") or "unclassified")
            lines.append(
                f"- `{item.get('name', '')}` type `{failure_type}` expected "
                f"`{item.get('expected')}`; actual `{item.get('actual')}`"
            )
    return lines


def write_report(
    report: dict[str, Any],
    output_dir: str | Path = DEFAULT_OUTPUT_DIR,
) -> tuple[Path, Path]:
    resolved_output_dir = Path(output_dir).resolve()
    resolved_output_dir.mkdir(parents=True, exist_ok=True)
    report_path = resolved_output_dir / "report.json"
    summary_path = resolved_output_dir / "summary.md"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    summary_path.write_text("\n".join(_summary_lines(report)) + "\n", encoding="utf-8")
    return report_path, summary_path
