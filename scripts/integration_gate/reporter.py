"""Allowlisted reports for the real-dependency integration gate."""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from scripts.gates import GateCheckResult, GateCheckStatus, GateEvaluation, json_safe

from .models import ROOT_DIR, IntegrationGatePolicy, IntegrationGateSettings, LiveCaseRunResult

DEFAULT_OUTPUT_DIR = ROOT_DIR / "eval" / "reports" / "integration_gate"
_CHECK_FIELDS = (
    "name",
    "status",
    "passed",
    "failure_type",
    "code",
    "expected",
    "actual",
    "duration_ms",
)
_REDACTED = "[redacted]"
_STABLE_LABEL_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,128}$")
_SENSITIVE_TEXT_RE = re.compile(
    r"password|secret|token|bearer|authorization|exception|response\s+body|https?://|\?",
    re.IGNORECASE,
)


def build_integration_report(
    *,
    policy: IntegrationGatePolicy,
    settings: IntegrationGateSettings,
    evaluation: GateEvaluation,
    case_results: tuple[LiveCaseRunResult, ...],
) -> dict[str, Any]:
    """Build a report containing only stable, non-secret integration gate fields."""

    observations = tuple(result.observation for result in case_results if result.observation)
    checks = tuple(evaluation.checks)
    metrics = {
        "check_count": len(checks),
        "failed_count": sum(check.status is GateCheckStatus.FAILED for check in checks),
        "blocked_count": sum(check.status is GateCheckStatus.BLOCKED for check in checks),
        "case_count": len(policy.live_cases),
        "executed_case_count": len(case_results),
        "observation_count": len(observations),
        "failure_type_counts": json_safe(evaluation.failure_type_counts),
        "total_estimated_cost_usd": round(
            sum(observation.estimated_cost_usd for observation in observations),
            6,
        ),
        "max_latency_ms": round(
            max((observation.latency_ms for observation in observations), default=0.0),
            3,
        ),
    }

    return {
        "schema_version": 1,
        "generated_at": datetime.now(UTC).isoformat(),
        "passed": evaluation.passed,
        "target": json_safe(settings.safe_target_identity()),
        "metrics": metrics,
        "checks": [_safe_check(check) for check in checks],
        "cases": [_safe_case_result(result) for result in case_results],
    }


def write_integration_report(
    report: dict[str, Any],
    output_dir: str | Path = DEFAULT_OUTPUT_DIR,
) -> tuple[Path, Path]:
    """Write JSON and Markdown integration gate reports."""

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    report_path = output_path / "report.json"
    summary_path = output_path / "summary.md"

    report_path.write_text(
        json.dumps(json_safe(report), ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    summary_path.write_text(_render_markdown_summary(report), encoding="utf-8")
    return report_path, summary_path


def _safe_check(check: GateCheckResult) -> dict[str, Any]:
    check_payload = check.to_dict()
    return {field: _json_allowlisted_value(check_payload.get(field)) for field in _CHECK_FIELDS}


def _safe_case_result(result: LiveCaseRunResult) -> dict[str, Any]:
    observation = result.observation
    return {
        "case_id": _json_allowlisted_value(result.case_id),
        "executed": True,
        "has_observation": observation is not None,
        "evidence_count": observation.evidence_count if observation is not None else 0,
        "latency_ms": round(observation.latency_ms, 3) if observation is not None else 0.0,
        "total_tokens": observation.total_tokens if observation is not None else 0,
        "estimated_cost_usd": round(
            observation.estimated_cost_usd if observation is not None else 0.0,
            6,
        ),
        "check_codes": [
            _json_allowlisted_value(check.code) for check in result.checks if check.code
        ],
    }


def _json_allowlisted_value(value: Any) -> Any:
    safe_value = json_safe(value)
    if safe_value is None or isinstance(safe_value, int | float | bool):
        return safe_value

    if isinstance(safe_value, str):
        return _safe_string_value(safe_value)

    if isinstance(safe_value, list):
        return [_json_allowlisted_value(item) for item in safe_value]

    if isinstance(safe_value, dict):
        return {
            _safe_string_value(str(key)): _json_allowlisted_value(item)
            for key, item in safe_value.items()
        }

    return None


def _safe_string_value(value: str) -> str:
    if _SENSITIVE_TEXT_RE.search(value):
        return _REDACTED

    if _STABLE_LABEL_RE.fullmatch(value):
        return value

    return _REDACTED


def _render_markdown_summary(report: dict[str, Any]) -> str:
    lines = [
        "# Real-Dependency Integration Gate",
        "",
        f"Status: {'PASS' if report.get('passed') else 'FAIL'}",
        "",
        "## Target",
        "",
    ]
    target = report.get("target", {})
    if isinstance(target, dict):
        for name in sorted(target):
            lines.append(f"- {name}: `{target[name]}`")
    lines.extend(["", "## Metrics", ""])

    metrics = report.get("metrics", {})
    if isinstance(metrics, dict):
        for name, value in metrics.items():
            if name == "failure_type_counts":
                continue
            lines.append(f"- {name}: `{_markdown_value(value)}`")

        failure_counts = metrics.get("failure_type_counts", {})
        lines.extend(["", "### Failure Type Counts", ""])
        if isinstance(failure_counts, dict) and failure_counts:
            for name, value in failure_counts.items():
                lines.append(f"- {name}: `{value}`")
        else:
            lines.append("- none: `0`")

    failed_checks = [
        check
        for check in report.get("checks", [])
        if isinstance(check, dict) and check.get("status") != GateCheckStatus.PASSED.value
    ]
    lines.extend(
        [
            "",
            "## Failed Checks",
            "",
            "| name | code | expected | actual |",
            "| --- | --- | --- | --- |",
        ]
    )
    if failed_checks:
        for check in failed_checks:
            lines.append(
                "| "
                f"{_markdown_cell(check.get('name'))} | "
                f"{_markdown_cell(check.get('code'))} | "
                f"{_markdown_cell(check.get('expected'))} | "
                f"{_markdown_cell(check.get('actual'))} |"
            )
    else:
        lines.append("| none |  |  |  |")

    lines.extend(
        [
            "",
            "## Cases",
            "",
            (
                "| case_id | executed | has_observation | evidence_count | latency_ms | "
                "total_tokens | estimated_cost_usd | check_codes |"
            ),
            "| --- | --- | --- | --- | --- | --- | --- | --- |",
        ]
    )
    cases = [case for case in report.get("cases", []) if isinstance(case, dict)]
    if cases:
        for case in cases:
            lines.append(
                "| "
                f"{_markdown_cell(case.get('case_id'))} | "
                f"{_markdown_cell(case.get('executed'))} | "
                f"{_markdown_cell(case.get('has_observation'))} | "
                f"{_markdown_cell(case.get('evidence_count'))} | "
                f"{_markdown_cell(case.get('latency_ms'))} | "
                f"{_markdown_cell(case.get('total_tokens'))} | "
                f"{_markdown_cell(case.get('estimated_cost_usd'))} | "
                f"{_markdown_cell(case.get('check_codes'))} |"
            )
    else:
        lines.append("| none |  |  |  |  |  |  |  |")

    lines.append("")
    return "\n".join(lines)


def _markdown_value(value: Any) -> str:
    if isinstance(value, str | int | float | bool) or value is None:
        return str(value)
    return json.dumps(json_safe(value), ensure_ascii=False, sort_keys=True, allow_nan=False)


def _markdown_cell(value: Any) -> str:
    text = _markdown_value(value)
    return text.replace("|", "\\|").replace("\n", " ")
