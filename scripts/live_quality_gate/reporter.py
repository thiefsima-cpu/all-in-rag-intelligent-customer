"""Safe report artifacts for the live quality gate."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from scripts.gates import GateCheckResult, aggregate_checks, json_safe

from .models import ROOT_DIR, LiveQualityCasePolicy, LiveQualityGatePolicy, LiveQualityGateSettings
from .runtime_models import DeterministicCaseResult

DEFAULT_OUTPUT_DIR = ROOT_DIR / "eval" / "reports" / "live_quality_gate"
_ARTIFACTS = {
    "report_json": "report.json",
    "summary_md": "summary.md",
    "manual_review_sample_jsonl": "manual_review_sample.jsonl",
}
_PRIMARY_METRIC_NAMES = (
    "case_count",
    "pass_rate",
    "deterministic_pass_rate",
    "judge_pass_rate",
    "recall_at_k",
    "mrr",
    "ndcg_at_k",
    "fallback_rate",
    "retrieval_degradation_rate",
    "p95_latency_ms",
    "estimated_cost_usd",
    "avg_judge_scores",
)
_NON_BLOCKING_CASE_QUALITY_CODES = frozenset(
    {"DETERMINISTIC_QUALITY_FAILED", "JUDGE_QUALITY_FAILED"}
)


def build_live_quality_report(
    *,
    policy: LiveQualityGatePolicy,
    settings: LiveQualityGateSettings,
    metrics: dict[str, Any],
    checks: tuple[GateCheckResult, ...],
    results: tuple[DeterministicCaseResult, ...],
) -> dict[str, Any]:
    evaluation = aggregate_checks(checks)
    release_evaluation = aggregate_checks(
        tuple(check for check in checks if _is_release_blocking_check(check))
    )
    cases_by_id = {case.case_id: case for case in policy.cases}
    case_summaries = [_case_summary(result, cases_by_id.get(result.case_id)) for result in results]
    manual_review_sample = [
        _manual_review_sample(result, cases_by_id[result.case_id])
        for result in results
        if result.case_id in cases_by_id and cases_by_id[result.case_id].manual_review.sample
    ]
    return {
        "schema_version": 1,
        "generated_at": datetime.now(UTC).isoformat(),
        "passed": release_evaluation.passed,
        "target": settings.safe_target_identity(),
        "top_k": policy.top_k,
        "metrics": json_safe(metrics),
        "failure_type_counts": dict(evaluation.failure_type_counts),
        "checks": [check.to_dict() for check in checks],
        "cases": case_summaries,
        "manual_review_sample_count": len(manual_review_sample),
        "manual_review_sample": manual_review_sample,
        "artifacts": dict(_ARTIFACTS),
    }


def _is_release_blocking_check(check: GateCheckResult) -> bool:
    """Let aggregate and slice thresholds govern valid per-case quality misses."""

    return not (check.name.startswith("case.") and check.code in _NON_BLOCKING_CASE_QUALITY_CODES)


def write_live_quality_report(
    report: dict[str, Any],
    output_dir: str | Path = DEFAULT_OUTPUT_DIR,
) -> tuple[Path, Path, Path]:
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    report_path = output_path / _ARTIFACTS["report_json"]
    summary_path = output_path / _ARTIFACTS["summary_md"]
    sample_path = output_path / _ARTIFACTS["manual_review_sample_jsonl"]

    report_path.write_text(
        json.dumps(json_safe(report), ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    summary_path.write_text(_markdown_summary(report), encoding="utf-8")
    sample_path.write_text(_manual_review_jsonl(report), encoding="utf-8")
    return report_path, summary_path, sample_path


def _case_summary(
    result: DeterministicCaseResult,
    case: LiveQualityCasePolicy | None,
) -> dict[str, Any]:
    return {
        "case_id": result.case_id,
        "query_type": result.query_type,
        "cuisine": result.cuisine,
        "constraint_types": list(result.constraint_types),
        "risk_tags": list(result.risk_tags),
        "response_mode": result.response_mode,
        "strategy": result.strategy,
        "passed": result.passed,
        "deterministic_passed": not result.failures,
        "judge_passed": result.judge_passed,
        "judge_scores": dict(result.judge_scores or {}),
        "failures": list(result.failures),
        "metrics": dict(result.metrics),
        "manual_review": (
            {
                "owner": case.manual_review.owner,
                "sample": case.manual_review.sample,
            }
            if case is not None
            else None
        ),
        "answer_preview": result.observation.answer[:300],
        "evidence": [
            {
                "recipe_name": item.recipe_name,
                "source": item.source,
                "snippet": item.content[:160],
            }
            for item in result.observation.evidence[:5]
        ],
    }


def _manual_review_sample(
    result: DeterministicCaseResult,
    case: LiveQualityCasePolicy,
) -> dict[str, Any]:
    return {
        "case_id": result.case_id,
        "owner": case.manual_review.owner,
        "query_type": result.query_type,
        "cuisine": result.cuisine,
        "risk_tags": list(result.risk_tags),
        "constraint_types": list(result.constraint_types),
        "expected_response_mode": result.response_mode,
        "query": case.query,
        "passed": result.passed,
        "deterministic_passed": not result.failures,
        "judge_passed": result.judge_passed,
        "judge_scores": dict(result.judge_scores or {}),
        "failures": list(result.failures),
        "answer_preview": result.observation.answer[:500],
        "evidence": [
            {
                "recipe_name": item.recipe_name,
                "source": item.source,
                "snippet": item.content[:240],
            }
            for item in result.observation.evidence[:6]
        ],
    }


def _markdown_summary(report: dict[str, Any]) -> str:
    lines = [
        "# Live Quality Gate",
        "",
        f"Status: {'PASS' if report.get('passed') is True else 'FAIL'}",
        "",
        "## Target",
        "",
    ]
    target = report.get("target", {})
    if isinstance(target, dict):
        lines.append(f"- api_host: `{target.get('api_host')}`")
        lines.append(f"- judge_host: `{target.get('judge_host')}`")

    lines.extend(["", "## Metrics", ""])
    metrics = report.get("metrics", {})
    if isinstance(metrics, dict):
        for key in _PRIMARY_METRIC_NAMES:
            lines.append(f"- {key}: `{metrics.get(key)}`")

    lines.extend(["", "## Failing Checks", ""])
    failed_checks = [
        check
        for check in report.get("checks", [])
        if isinstance(check, dict) and not check.get("passed")
    ]
    if failed_checks:
        for check in failed_checks:
            lines.append(f"- `{check.get('name')}`: `{check.get('code')}`")
    else:
        lines.append("- none")

    lines.extend(["", "## Manual Review", ""])
    lines.append(f"- sample_count: `{report.get('manual_review_sample_count', 0)}`")
    return "\n".join(lines) + "\n"


def _manual_review_jsonl(report: dict[str, Any]) -> str:
    samples = report.get("manual_review_sample", [])
    if not isinstance(samples, list):
        return ""
    return "".join(
        json.dumps(json_safe(sample), ensure_ascii=False, allow_nan=False) + "\n"
        for sample in samples
        if isinstance(sample, dict)
    )
