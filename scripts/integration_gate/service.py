"""Service orchestration for the real-dependency integration gate."""

from __future__ import annotations

import json
import os
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Protocol

from pydantic import ValidationError

from scripts.gates import GateCheckResult, aggregate_checks

from .evaluator import evaluate_integration_metrics
from .live_cases import run_live_case
from .models import (
    DEFAULT_POLICY_PATH,
    IntegrationGatePolicy,
    IntegrationGateSettings,
    LiveCasePolicy,
    LiveCaseRunResult,
    load_integration_policy,
)
from .probes import run_dependency_probes
from .reporter import DEFAULT_OUTPUT_DIR, build_integration_report, write_integration_report


class IntegrationGateConfigurationError(RuntimeError):
    """Raised when integration gate policy or required environment is invalid."""


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
        settings = IntegrationGateSettings.from_environ(environ or os.environ)
    except (OSError, ValueError, ValidationError, json.JSONDecodeError) as exc:
        raise IntegrationGateConfigurationError(
            "Integration gate configuration is invalid."
        ) from exc

    checks: list[GateCheckResult] = []
    case_results: list[LiveCaseRunResult] = []

    probe_checks = tuple(probe_runner(settings=settings, policy=policy))
    checks.extend(probe_checks)

    if any(not check.passed for check in probe_checks):
        checks.extend(
            GateCheckResult.block_check(
                f"case.{case.case_id}",
                code="PREREQUISITE_FAILED",
            )
            for case in policy.live_cases
        )
    else:
        observations = []
        for case in policy.live_cases:
            result = case_runner(settings=settings, policy=policy, case=case)
            case_results.append(result)
            checks.extend(result.checks)
            if result.observation is not None:
                observations.append(result.observation)

        checks.extend(evaluate_integration_metrics(policy, observations))

    evaluation = aggregate_checks(checks)
    output_path = Path(output_dir)
    report = build_integration_report(
        policy=policy,
        settings=settings,
        evaluation=evaluation,
        case_results=tuple(case_results),
    )
    report["artifacts"] = {
        "report_json": str(output_path / "report.json"),
        "summary_md": str(output_path / "summary.md"),
    }
    write_integration_report(report, output_path)
    return report
