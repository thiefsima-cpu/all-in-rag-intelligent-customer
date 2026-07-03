"""Deterministic suite runners for the offline release gate."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from scripts.gates import GateFailureType
from scripts.smoke_answer_pipeline import run_smoke as run_answer_pipeline
from scripts.smoke_answer_pipeline_real_route import (
    run_smoke as run_answer_pipeline_real_route,
)
from scripts.smoke_generation_plans import run_smoke as run_generation_plans
from scripts.smoke_generation_prompts import run_smoke as run_generation_prompts
from scripts.smoke_route_queries import run_smoke as run_route_semantics

from .policy import QualityRunnerSettings

SuiteRunner = Callable[[], dict[str, Any]]

SUITE_RUNNERS: dict[str, SuiteRunner] = {
    "route_semantics": run_route_semantics,
    "answer_pipeline": run_answer_pipeline,
    "answer_pipeline_real_route": run_answer_pipeline_real_route,
    "generation_plans": run_generation_plans,
    "generation_prompts": run_generation_prompts,
}


class OfflineSuiteFailure(Exception):
    """A suite failure whose gate classification is known by the runner."""

    def __init__(
        self,
        failure_type: GateFailureType,
        *,
        code: str = "OFFLINE_SUITE_FAILURE",
    ) -> None:
        super().__init__(code)
        self.failure_type = failure_type
        self.code = code


def _failed_suite_report(failure_type: GateFailureType, code: str) -> dict[str, Any]:
    failure_value = failure_type.value
    return {
        "case_count": 0,
        "passed_count": 0,
        "results": [],
        "failures": [{"suite_error": code, "failure_type": failure_value}],
        "suite_error": code,
        "failure_type": failure_value,
    }


def run_suites(
    suite_names: list[str],
    *,
    runners: dict[str, SuiteRunner] | None = None,
) -> dict[str, dict[str, Any]]:
    resolved_runners = runners or SUITE_RUNNERS
    reports: dict[str, dict[str, Any]] = {}
    for suite_name in suite_names:
        runner = resolved_runners.get(suite_name)
        if runner is None:
            reports[suite_name] = _failed_suite_report(
                GateFailureType.GATE_ERROR,
                "UNKNOWN_SUITE",
            )
            continue
        try:
            reports[suite_name] = dict(runner() or {})
        except OfflineSuiteFailure as exc:
            reports[suite_name] = _failed_suite_report(exc.failure_type, exc.code)
        except Exception as exc:
            reports[suite_name] = _failed_suite_report(
                GateFailureType.GATE_ERROR,
                f"RUNNER_ERROR_{type(exc).__name__.upper()}",
            )
    return reports


def run_quality_eval(settings: QualityRunnerSettings) -> dict[str, Any]:
    from scripts.eval_reporting import evaluate_offline_quality_queries

    report = evaluate_offline_quality_queries(
        top_k=settings.top_k,
        generate=settings.generate,
        profile=settings.profile,
    )
    metrics = dict(report.get("metrics") or {})
    results = [dict(item) for item in (report.get("results") or [])]
    failures = [dict(item) for item in (report.get("failures") or [])]
    case_count = max(0, int(metrics.get("case_count") or len(results)))
    passed_count = sum(1 for item in results if item.get("passed"))
    return {
        "case_count": case_count,
        "passed_count": min(case_count, passed_count),
        "metrics": metrics,
        "results": results,
        "failures": failures,
        "profile": dict(report.get("profile") or {}),
    }
