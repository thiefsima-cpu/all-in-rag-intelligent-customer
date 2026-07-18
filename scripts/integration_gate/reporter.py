"""Allowlisted reports for the real-dependency integration gate."""

from __future__ import annotations

import json
import math
import re
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping

from scripts.gates import (
    GateCheckResult,
    GateCheckStatus,
    GateEvaluation,
    GateFailureType,
    json_safe,
)

from .models import ROOT_DIR, IntegrationCaseSummary, IntegrationGatePolicy, IntegrationGateSettings

DEFAULT_OUTPUT_DIR = ROOT_DIR / "eval" / "reports" / "integration_gate"
_REDACTED = "[redacted]"
_STABLE_LABEL_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,128}$")
_SAFE_EVIDENCE_KEY_SETS = frozenset(
    {
        frozenset({"minimum"}),
        frozenset({"minimum", "maximum"}),
        frozenset({"maximum_ms"}),
        frozenset({"generation_required", "minimum_tokens"}),
        frozenset({"minimum_observations"}),
        frozenset({"observation_count"}),
    }
)
_ARTIFACT_IDENTITIES = {
    "report_json": "report.json",
    "summary_md": "summary.md",
}
_SENSITIVE_TEXT_RE = re.compile(
    r"password|secret|token|bearer|authorization|exception|response\s+body|https?://|\?",
    re.IGNORECASE,
)


def build_integration_report(
    *,
    policy: IntegrationGatePolicy,
    settings: IntegrationGateSettings,
    evaluation: GateEvaluation,
    case_summaries: tuple[IntegrationCaseSummary, ...],
) -> dict[str, Any]:
    """Build a report containing only stable, non-secret integration gate fields."""

    checks = tuple(evaluation.checks)

    return _project_integration_report(
        {
            "generated_at": datetime.now(UTC).isoformat(),
            "target": json_safe(settings.safe_target_identity()),
            "checks": [_safe_check(check) for check in checks],
            "cases": [_safe_case_summary(summary) for summary in case_summaries],
        }
    )


def write_integration_report(
    report: dict[str, Any],
    output_dir: str | Path = DEFAULT_OUTPUT_DIR,
) -> tuple[Path, Path]:
    """Write JSON and Markdown integration gate reports."""

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    report_path = output_path / "report.json"
    summary_path = output_path / "summary.md"

    persisted_report = _project_integration_report(report)
    report_path.write_text(
        json.dumps(persisted_report, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    summary_path.write_bytes(render_integration_summary(persisted_report))
    return report_path, summary_path


def _safe_check(check: GateCheckResult) -> dict[str, Any]:
    check_payload = check.to_dict()
    return {
        "name": _safe_identifier(check_payload["name"]),
        "status": check_payload["status"],
        "passed": check_payload["passed"],
        "failure_type": check_payload["failure_type"],
        "code": _safe_identifier(check_payload["code"]),
        "expected": _safe_evidence_value(check_payload["expected"]),
        "actual": _safe_evidence_value(check_payload["actual"]),
        "duration_ms": check_payload["duration_ms"],
    }


def _safe_case_summary(summary: IntegrationCaseSummary) -> dict[str, Any]:
    observation = summary.observation
    return {
        "case_id": _safe_identifier(summary.case_id),
        "executed": summary.executed,
        "status": summary.status.value,
        "has_observation": observation is not None,
        "evidence_count": observation.evidence_count if observation is not None else 0,
        "latency_ms": round(observation.latency_ms, 3) if observation is not None else 0.0,
        "total_tokens": observation.total_tokens if observation is not None else 0,
        "estimated_cost_usd": round(
            observation.estimated_cost_usd if observation is not None else 0.0,
            6,
        ),
        "check_codes": [_safe_identifier(code) for code in summary.check_codes],
    }


def _safe_evidence_value(value: Any) -> Any:
    safe_value = json_safe(value)
    if safe_value is None or isinstance(safe_value, int | float | bool):
        return safe_value

    if isinstance(safe_value, str):
        return _REDACTED

    if isinstance(safe_value, dict):
        if frozenset(safe_value) in _SAFE_EVIDENCE_KEY_SETS and all(
            item is None or isinstance(item, int | float | bool) for item in safe_value.values()
        ):
            return dict(safe_value)
        return _REDACTED

    if isinstance(safe_value, list):
        return _REDACTED

    return None


def _safe_identifier(value: Any) -> str:
    if not isinstance(value, str):
        return _REDACTED

    if _SENSITIVE_TEXT_RE.search(value):
        return _REDACTED

    if _STABLE_LABEL_RE.fullmatch(value):
        return value

    return _REDACTED


def _project_integration_report(report: dict[str, Any]) -> dict[str, Any]:
    checks = _project_checks(report.get("checks"))
    cases = _project_cases(report.get("cases"))
    return {
        "schema_version": 1,
        "generated_at": _safe_timestamp(report.get("generated_at")),
        "passed": bool(checks)
        and bool(cases)
        and all(check["passed"] for check in checks)
        and all(case["executed"] and case["status"] == "passed" for case in cases),
        "target": _project_target(report.get("target")),
        "metrics": _derive_metrics(checks, cases),
        "checks": checks,
        "cases": cases,
        "artifacts": dict(_ARTIFACT_IDENTITIES),
    }


def _safe_timestamp(value: Any) -> str:
    if not isinstance(value, str):
        return _REDACTED
    try:
        return datetime.fromisoformat(value).isoformat()
    except ValueError:
        return _REDACTED


def _project_target(value: Any) -> dict[str, str]:
    source = value if isinstance(value, dict) else {}
    return {
        name: _safe_identifier(source.get(name))
        for name in ("api_host", "neo4j_host", "milvus_host")
    }


def _derive_metrics(
    checks: list[dict[str, Any]],
    cases: list[dict[str, Any]],
) -> dict[str, Any]:
    failed_checks = [check for check in checks if check["status"] == GateCheckStatus.FAILED.value]
    observed_cases = [case for case in cases if case["has_observation"]]
    failure_counts = Counter(check["failure_type"] for check in failed_checks)
    return {
        "check_count": len(checks),
        "failed_count": len(failed_checks),
        "blocked_count": sum(check["status"] == GateCheckStatus.BLOCKED.value for check in checks),
        "case_count": len(cases),
        "executed_case_count": sum(case["executed"] for case in cases),
        "observation_count": len(observed_cases),
        "failure_type_counts": dict(sorted(failure_counts.items())),
        "total_estimated_cost_usd": round(
            sum(case["estimated_cost_usd"] for case in observed_cases),
            6,
        ),
        "max_latency_ms": round(
            max((case["latency_ms"] for case in observed_cases), default=0.0),
            3,
        ),
    }


def _safe_number(value: Any, *, default: int | float) -> int | float:
    if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(value):
        return default
    return value


def _project_checks(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [_project_check_payload(item) for item in value if isinstance(item, dict)]


def _project_check_payload(check: dict[str, Any]) -> dict[str, Any]:
    statuses = {status.value for status in GateCheckStatus}
    failure_types = {failure_type.value for failure_type in GateFailureType}
    status = check.get("status")
    failure_type = check.get("failure_type")
    normalized_status = status if status in statuses else GateCheckStatus.BLOCKED.value
    if normalized_status == GateCheckStatus.FAILED.value:
        normalized_failure_type = (
            failure_type if failure_type in failure_types else GateFailureType.GATE_ERROR.value
        )
    else:
        normalized_failure_type = None
    return {
        "name": _safe_identifier(check.get("name")),
        "status": normalized_status,
        "passed": normalized_status == GateCheckStatus.PASSED.value,
        "failure_type": normalized_failure_type,
        "code": _safe_identifier(check.get("code")),
        "expected": _safe_evidence_value(check.get("expected")),
        "actual": _safe_evidence_value(check.get("actual")),
        "duration_ms": _safe_number(check.get("duration_ms"), default=0.0),
    }


def _project_cases(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [_project_case_payload(item) for item in value if isinstance(item, dict)]


def _project_case_payload(case: dict[str, Any]) -> dict[str, Any]:
    statuses = {status.value for status in GateCheckStatus}
    executed = case.get("executed") is True
    status = case.get("status")
    normalized_status = status if executed and status in statuses else GateCheckStatus.BLOCKED.value
    has_observation = executed and case.get("has_observation") is True
    if normalized_status == GateCheckStatus.PASSED.value and not has_observation:
        normalized_status = GateCheckStatus.BLOCKED.value
    raw_codes = case.get("check_codes")
    codes = raw_codes if isinstance(raw_codes, list) else []
    return {
        "case_id": _safe_identifier(case.get("case_id")),
        "executed": executed,
        "status": normalized_status,
        "has_observation": has_observation,
        "evidence_count": (
            _safe_number(case.get("evidence_count"), default=0) if has_observation else 0
        ),
        "latency_ms": (
            _safe_number(case.get("latency_ms"), default=0.0) if has_observation else 0.0
        ),
        "total_tokens": (
            _safe_number(case.get("total_tokens"), default=0) if has_observation else 0
        ),
        "estimated_cost_usd": (
            _safe_number(case.get("estimated_cost_usd"), default=0.0) if has_observation else 0.0
        ),
        "check_codes": [_safe_identifier(code) for code in codes],
    }


def render_integration_summary(report: Mapping[str, Any]) -> bytes:
    """Render the canonical UTF-8/LF summary for a persisted integration report."""

    return _render_markdown_summary(report).encode("utf-8")


def _render_markdown_summary(report: Mapping[str, Any]) -> str:
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
                "| case_id | executed | status | has_observation | evidence_count | latency_ms | "
                "total_tokens | estimated_cost_usd | check_codes |"
            ),
            "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
        ]
    )
    cases = [case for case in report.get("cases", []) if isinstance(case, dict)]
    if cases:
        for case in cases:
            lines.append(
                "| "
                f"{_markdown_cell(case.get('case_id'))} | "
                f"{_markdown_cell(case.get('executed'))} | "
                f"{_markdown_cell(case.get('status'))} | "
                f"{_markdown_cell(case.get('has_observation'))} | "
                f"{_markdown_cell(case.get('evidence_count'))} | "
                f"{_markdown_cell(case.get('latency_ms'))} | "
                f"{_markdown_cell(case.get('total_tokens'))} | "
                f"{_markdown_cell(case.get('estimated_cost_usd'))} | "
                f"{_markdown_cell(case.get('check_codes'))} |"
            )
    else:
        lines.append("| none |  |  |  |  |  |  |  |  |")

    lines.append("")
    return "\n".join(lines)


def _markdown_value(value: Any) -> str:
    if isinstance(value, str | int | float | bool) or value is None:
        return str(value)
    return json.dumps(json_safe(value), ensure_ascii=False, sort_keys=True, allow_nan=False)


def _markdown_cell(value: Any) -> str:
    text = _markdown_value(value)
    return text.replace("|", "\\|").replace("\n", " ")
