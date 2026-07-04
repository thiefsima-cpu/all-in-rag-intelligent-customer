"""Service orchestration for the real-dependency integration gate."""

from __future__ import annotations

import json
import os
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Protocol

from pydantic import ValidationError

from scripts.gates import GateCheckResult, GateCheckStatus, aggregate_checks

from .evaluator import evaluate_integration_metrics
from .live_cases import run_live_case
from .models import (
    DEFAULT_POLICY_PATH,
    IntegrationCaseSummary,
    IntegrationGatePolicy,
    IntegrationGateSettings,
    LiveCaseObservation,
    LiveCasePolicy,
    LiveCaseRunResult,
    load_integration_policy,
)
from .probes import run_dependency_probes
from .reporter import DEFAULT_OUTPUT_DIR, build_integration_report, write_integration_report


class IntegrationGateConfigurationError(RuntimeError):
    """Raised when integration gate policy or required environment is invalid."""


class IntegrationGateExecutionError(RuntimeError):
    """Raised when an integration gate collaborator violates its runtime contract."""


_REQUIRED_PROBE_CHECK_NAMES = frozenset(
    {
        "dependency.neo4j.recipe_count",
        "dependency.milvus.entity_count",
        "dependency.serving.ready",
    }
)
_OBSERVED_CASE_CHECK_SUFFIXES = frozenset(
    {
        "strategy",
        "sources",
        "evidence_count",
        "fallback",
        "retrieval_degradation",
        "model_usage",
        "latency",
    }
)


class ProbeRunner(Protocol):
    def __call__(
        self,
        *,
        settings: IntegrationGateSettings,
        policy: IntegrationGatePolicy,
    ) -> Sequence[GateCheckResult]: ...


class LiveCaseRunner(Protocol):
    def __call__(
        self,
        *,
        settings: IntegrationGateSettings,
        policy: IntegrationGatePolicy,
        case: LiveCasePolicy,
    ) -> LiveCaseRunResult: ...


def run_integration_gate(
    *,
    policy_path: str | Path = DEFAULT_POLICY_PATH,
    output_dir: str | Path = DEFAULT_OUTPUT_DIR,
    environ: Mapping[str, str] | None = None,
    probe_runner: ProbeRunner = run_dependency_probes,
    case_runner: LiveCaseRunner = run_live_case,
) -> dict[str, Any]:
    """Run dependency probes, live cases, aggregate checks, and write reports."""

    try:
        policy = load_integration_policy(policy_path)
        settings = IntegrationGateSettings.from_environ(os.environ if environ is None else environ)
    except (OSError, ValueError, ValidationError, json.JSONDecodeError) as exc:
        raise IntegrationGateConfigurationError(
            "Integration gate configuration is invalid."
        ) from exc

    checks: list[GateCheckResult] = []
    case_summaries: list[IntegrationCaseSummary] = []

    probe_checks = _run_validated_probes(
        probe_runner,
        settings=settings,
        policy=policy,
    )
    checks.extend(probe_checks)

    if any(not check.passed for check in probe_checks):
        for case in policy.live_cases:
            blocked_check = GateCheckResult.block_check(
                f"case.{case.case_id}",
                code="PREREQUISITE_FAILED",
            )
            checks.append(blocked_check)
            case_summaries.append(
                IntegrationCaseSummary(
                    case_id=case.case_id,
                    executed=False,
                    status=GateCheckStatus.BLOCKED,
                    observation=None,
                    check_codes=(blocked_check.code,),
                )
            )
    else:
        observations = []
        for case in policy.live_cases:
            result = _run_validated_case(
                case_runner,
                settings=settings,
                policy=policy,
                case=case,
            )
            checks.extend(result.checks)
            case_summaries.append(_summarize_executed_case(case.case_id, result))
            if result.observation is not None:
                observations.append(result.observation)

        checks.extend(evaluate_integration_metrics(policy, observations))

    evaluation = aggregate_checks(checks)
    report = build_integration_report(
        policy=policy,
        settings=settings,
        evaluation=evaluation,
        case_summaries=tuple(case_summaries),
    )
    write_integration_report(report, output_dir)
    return report


def _run_validated_probes(
    probe_runner: ProbeRunner,
    *,
    settings: IntegrationGateSettings,
    policy: IntegrationGatePolicy,
) -> tuple[GateCheckResult, ...]:
    try:
        probe_checks = tuple(probe_runner(settings=settings, policy=policy))
    except Exception as exc:
        raise IntegrationGateExecutionError("Integration dependency probes failed.") from exc

    if not all(isinstance(check, GateCheckResult) for check in probe_checks):
        raise IntegrationGateExecutionError("Integration dependency probe results are invalid.")

    names = tuple(check.name for check in probe_checks)
    if len(names) != len(_REQUIRED_PROBE_CHECK_NAMES) or set(names) != _REQUIRED_PROBE_CHECK_NAMES:
        raise IntegrationGateExecutionError("Integration dependency probe results are invalid.")

    return probe_checks


def _run_validated_case(
    case_runner: LiveCaseRunner,
    *,
    settings: IntegrationGateSettings,
    policy: IntegrationGatePolicy,
    case: LiveCasePolicy,
) -> LiveCaseRunResult:
    try:
        result = case_runner(settings=settings, policy=policy, case=case)
    except Exception as exc:
        raise IntegrationGateExecutionError("Integration live case execution failed.") from exc

    if not isinstance(result, LiveCaseRunResult) or result.case_id != case.case_id:
        raise IntegrationGateExecutionError("Integration live case result is invalid.")

    observation = result.observation
    if observation is not None and (
        not isinstance(observation, LiveCaseObservation) or observation.case_id != case.case_id
    ):
        raise IntegrationGateExecutionError("Integration live case result is invalid.")

    if (
        not isinstance(result.checks, tuple)
        or not result.checks
        or not all(isinstance(check, GateCheckResult) for check in result.checks)
    ):
        raise IntegrationGateExecutionError("Integration live case result is invalid.")

    _validate_case_check_contract(case.case_id, result)

    return result


def _validate_case_check_contract(case_id: str, result: LiveCaseRunResult) -> None:
    names = tuple(check.name for check in result.checks)
    if result.observation is not None:
        required_names = {f"case.{case_id}.{suffix}" for suffix in _OBSERVED_CASE_CHECK_SUFFIXES}
        if len(names) != len(required_names) or set(names) != required_names:
            raise IntegrationGateExecutionError("Integration live case checks are invalid.")
        return

    request_name = f"case.{case_id}.request"
    if (
        len(result.checks) != 1
        or names != (request_name,)
        or result.checks[0].status is not GateCheckStatus.FAILED
    ):
        raise IntegrationGateExecutionError("Integration live case checks are invalid.")


def _summarize_executed_case(
    case_id: str,
    result: LiveCaseRunResult,
) -> IntegrationCaseSummary:
    if any(check.status is GateCheckStatus.FAILED for check in result.checks):
        status = GateCheckStatus.FAILED
    elif any(check.status is GateCheckStatus.BLOCKED for check in result.checks):
        status = GateCheckStatus.BLOCKED
    else:
        status = GateCheckStatus.PASSED

    return IntegrationCaseSummary(
        case_id=case_id,
        executed=True,
        status=status,
        observation=result.observation,
        check_codes=tuple(check.code for check in result.checks if check.code),
    )
