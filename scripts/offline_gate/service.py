"""Application service for the required offline release gate."""

from __future__ import annotations

from functools import partial
from pathlib import Path
from typing import Any

from .evaluator import evaluate_gate
from .policy import (
    DEFAULT_POLICY_PATH,
    load_policy,
    required_quality_stage,
    validate_metric_threshold_rules,
)
from .reporter import DEFAULT_OUTPUT_DIR, write_report
from .runners import SUITE_RUNNERS, run_quality_eval, run_suites


def run_release_gate(
    *,
    policy_path: str | Path = DEFAULT_POLICY_PATH,
    output_dir: str | Path = DEFAULT_OUTPUT_DIR,
) -> dict[str, Any]:
    resolved_policy_path = Path(policy_path).resolve()
    policy = load_policy(policy_path)
    try:
        validate_metric_threshold_rules(
            policy.get("metric_thresholds") or {},
            context="Release gate policy",
        )
        quality_settings = required_quality_stage(policy)
        required_suites = [
            str(item) for item in (policy.get("required_suites") or []) if str(item).strip()
        ]
        if "quality_eval" not in required_suites:
            raise ValueError("Required release-gate suite is missing: quality_eval")
    except ValueError as exc:
        raise ValueError(f"Invalid release gate policy at {resolved_policy_path}: {exc}") from exc

    runners = dict(SUITE_RUNNERS)
    runners["quality_eval"] = partial(run_quality_eval, quality_settings)
    suite_reports = run_suites(required_suites, runners=runners)
    report = evaluate_gate(policy, suite_reports)
    report["quality_eval_required"] = True
    report["policy_path"] = str(resolved_policy_path)
    report_path, summary_path = write_report(report, output_dir)
    report["report_path"] = str(report_path)
    report["summary_path"] = str(summary_path)
    return report
