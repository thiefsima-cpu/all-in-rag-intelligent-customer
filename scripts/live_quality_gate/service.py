"""Service orchestration for the live AI quality gate."""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Protocol

from pydantic import ValidationError

from scripts.gates import GateCheckResult

from .client import run_live_case
from .evaluator import (
    aggregate_live_quality_metrics,
    evaluate_deterministic_case,
    evaluate_policy_thresholds,
)
from .judge import run_judge
from .models import (
    DEFAULT_POLICY_PATH,
    JudgeSettings,
    LiveQualityCasePolicy,
    LiveQualityGatePolicy,
    LiveQualityGateSettings,
    load_live_quality_policy,
)
from .reporter import DEFAULT_OUTPUT_DIR, build_live_quality_report, write_live_quality_report
from .runtime_models import (
    DeterministicCaseResult,
    JudgeRunResult,
    JudgeVerdict,
    LiveQualityCaseRunResult,
    LiveQualityObservation,
)


class LiveQualityGateConfigurationError(RuntimeError):
    """Raised when live quality policy or required environment is invalid."""


class LiveQualityGateExecutionError(RuntimeError):
    """Raised when a live quality collaborator violates its runtime contract."""


class CaseRunner(Protocol):
    def __call__(
        self,
        *,
        settings: LiveQualityGateSettings,
        policy: LiveQualityGatePolicy,
        case: LiveQualityCasePolicy,
    ) -> LiveQualityCaseRunResult: ...


class JudgeRunner(Protocol):
    def __call__(
        self,
        *,
        settings: JudgeSettings,
        case: LiveQualityCasePolicy,
        observation: LiveQualityObservation,
        expected_score_names: tuple[str, ...],
        minimum_score: float,
    ) -> JudgeRunResult: ...


def run_live_quality_gate(
    *,
    policy_path: str | Path = DEFAULT_POLICY_PATH,
    output_dir: str | Path = DEFAULT_OUTPUT_DIR,
    environ: Mapping[str, str] | None = None,
    policy: LiveQualityGatePolicy | None = None,
    settings: LiveQualityGateSettings | None = None,
    deterministic_only: bool = False,
    case_runner: CaseRunner = run_live_case,
    judge_runner: JudgeRunner = run_judge,
) -> dict[str, Any]:
    """Run live cases, deterministic scoring, optional judge scoring, and reports."""

    gate_policy, gate_settings = _load_configuration(
        policy_path=policy_path,
        environ=environ,
        policy=policy,
        settings=settings,
    )

    if deterministic_only and gate_policy.judge.required:
        raise LiveQualityGateConfigurationError(
            "Judge is required for release-quality live quality execution."
        )

    checks: list[GateCheckResult] = []
    deterministic_results: list[DeterministicCaseResult] = []

    for case in gate_policy.cases:
        case_result = _run_validated_case(
            case_runner,
            settings=gate_settings,
            policy=gate_policy,
            case=case,
        )
        checks.extend(case_result.checks)
        if case_result.observation is None:
            continue

        scored = evaluate_deterministic_case(
            case,
            case_result.observation,
            top_k=gate_policy.top_k,
        )
        checks.extend(scored.checks)

        if gate_policy.judge.required and not deterministic_only:
            judge_result = _run_validated_judge(
                judge_runner,
                settings=gate_settings,
                policy=gate_policy,
                case=case,
                observation=case_result.observation,
            )
            checks.extend(judge_result.checks)
            if judge_result.verdict is not None:
                scored = scored.with_judge_result(
                    passed=all(check.passed for check in judge_result.checks),
                    scores=judge_result.verdict.scores,
                )

        deterministic_results.append(scored)

    metrics = aggregate_live_quality_metrics(deterministic_results)
    checks.extend(evaluate_policy_thresholds(gate_policy, metrics))
    report = build_live_quality_report(
        policy=gate_policy,
        settings=gate_settings,
        metrics=metrics,
        checks=tuple(checks),
        results=tuple(deterministic_results),
    )
    write_live_quality_report(report, output_dir)
    return report


def _load_configuration(
    *,
    policy_path: str | Path,
    environ: Mapping[str, str] | None,
    policy: LiveQualityGatePolicy | None,
    settings: LiveQualityGateSettings | None,
) -> tuple[LiveQualityGatePolicy, LiveQualityGateSettings]:
    try:
        gate_policy = policy if policy is not None else load_live_quality_policy(policy_path)
        gate_settings = (
            settings
            if settings is not None
            else LiveQualityGateSettings.from_environ(os.environ if environ is None else environ)
        )
    except (OSError, ValueError, ValidationError, json.JSONDecodeError) as exc:
        raise LiveQualityGateConfigurationError(
            "Live quality gate configuration is invalid."
        ) from exc

    return gate_policy, gate_settings


def _run_validated_case(
    case_runner: CaseRunner,
    *,
    settings: LiveQualityGateSettings,
    policy: LiveQualityGatePolicy,
    case: LiveQualityCasePolicy,
) -> LiveQualityCaseRunResult:
    try:
        result = case_runner(settings=settings, policy=policy, case=case)
    except Exception as exc:
        raise LiveQualityGateExecutionError("Live quality case execution failed.") from exc

    if not isinstance(result, LiveQualityCaseRunResult) or result.case_id != case.case_id:
        raise LiveQualityGateExecutionError("Live quality case result is invalid.")

    if result.observation is not None and (
        not isinstance(result.observation, LiveQualityObservation)
        or result.observation.case_id != case.case_id
    ):
        raise LiveQualityGateExecutionError("Live quality case result is invalid.")

    if not isinstance(result.checks, tuple) or not all(
        isinstance(check, GateCheckResult) for check in result.checks
    ):
        raise LiveQualityGateExecutionError("Live quality case result is invalid.")

    return result


def _run_validated_judge(
    judge_runner: JudgeRunner,
    *,
    settings: LiveQualityGateSettings,
    policy: LiveQualityGatePolicy,
    case: LiveQualityCasePolicy,
    observation: LiveQualityObservation,
) -> JudgeRunResult:
    try:
        result = judge_runner(
            settings=settings.judge,
            case=case,
            observation=observation,
            expected_score_names=tuple(policy.judge.score_names),
            minimum_score=policy.judge.minimum_score,
        )
    except Exception as exc:
        raise LiveQualityGateExecutionError("Live quality judge execution failed.") from exc

    if not isinstance(result, JudgeRunResult) or result.case_id != case.case_id:
        raise LiveQualityGateExecutionError("Live quality judge result is invalid.")

    if result.verdict is not None and (
        not isinstance(result.verdict, JudgeVerdict) or result.verdict.case_id != case.case_id
    ):
        raise LiveQualityGateExecutionError("Live quality judge result is invalid.")

    if (
        not isinstance(result.checks, tuple)
        or not result.checks
        or not all(isinstance(check, GateCheckResult) for check in result.checks)
    ):
        raise LiveQualityGateExecutionError("Live quality judge result is invalid.")

    return result
