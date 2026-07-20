from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from scripts.gates import GateCheckResult, GateFailureType
from scripts.live_quality_gate.runtime_models import (
    JudgeRunResult,
    JudgeVerdict,
    LiveQualityCaseRunResult,
)
from scripts.live_quality_gate.service import (
    LiveQualityGateConfigurationError,
    LiveQualityGateExecutionError,
    run_live_quality_gate,
)
from tests.test_live_quality_gate_client import policy, settings
from tests.test_live_quality_gate_evaluator import make_observation


def case_runner(**kwargs):
    case = kwargs["case"]
    return LiveQualityCaseRunResult(
        case_id=case.case_id,
        observation=make_observation(case_id=case.case_id),
        checks=(),
    )


def passing_judge_runner(**kwargs):
    case = kwargs["case"]
    return JudgeRunResult(
        case_id=case.case_id,
        verdict=JudgeVerdict(
            case_id=case.case_id,
            passed=True,
            scores={"faithfulness": 1.0, "answer_relevance": 1.0},
            rationale="grounded",
        ),
        checks=(
            GateCheckResult.pass_check(
                f"case.{case.case_id}.judge",
                code="JUDGE_QUALITY_OK",
            ),
        ),
    )


def failing_score_judge_runner(**kwargs):
    case = kwargs["case"]
    return JudgeRunResult(
        case_id=case.case_id,
        verdict=JudgeVerdict(
            case_id=case.case_id,
            passed=True,
            scores={"faithfulness": 1.0, "answer_relevance": 0.2},
            rationale="relevant score is too low",
        ),
        checks=(
            GateCheckResult.fail_check(
                f"case.{case.case_id}.judge",
                failure_type=GateFailureType.QUALITY_REGRESSION,
                code="JUDGE_QUALITY_FAILED",
            ),
        ),
    )


def test_service_runs_cases_judge_thresholds_and_writes_reports(tmp_path: Path) -> None:
    report = run_live_quality_gate(
        policy=policy(),
        settings=settings(),
        output_dir=tmp_path,
        case_runner=case_runner,
        judge_runner=passing_judge_runner,
    )

    assert report["passed"] is True
    assert report["schema_version"] == 2
    assert report["metrics"]["case_count"] == 1
    assert report["metrics"]["judge_pass_rate"] == 1.0
    assert report["cases"][0]["timings"]["ttft_ms"] == 1000.0
    assert (tmp_path / "report.json").exists()
    assert (tmp_path / "summary.md").exists()
    assert (tmp_path / "manual_review_sample.jsonl").exists()


def test_service_uses_judge_quality_check_status_for_case_result(tmp_path: Path) -> None:
    report = run_live_quality_gate(
        policy=policy(),
        settings=settings(),
        output_dir=tmp_path,
        case_runner=case_runner,
        judge_runner=failing_score_judge_runner,
    )

    assert report["passed"] is False
    assert report["metrics"]["pass_rate"] == 0.0
    assert report["metrics"]["judge_pass_rate"] == 0.0
    assert report["cases"][0]["passed"] is False
    assert any(check["code"] == "JUDGE_QUALITY_FAILED" for check in report["checks"])


def test_service_fails_when_judge_is_required_but_disabled(tmp_path: Path) -> None:
    gate_policy = policy().model_copy(
        update={"judge": policy().judge.model_copy(update={"required": True})}
    )

    with pytest.raises(LiveQualityGateConfigurationError):
        run_live_quality_gate(
            policy=gate_policy,
            settings=settings(),
            output_dir=tmp_path,
            deterministic_only=True,
            case_runner=case_runner,
            judge_runner=passing_judge_runner,
        )


def test_service_rejects_invalid_case_runner_result(tmp_path: Path) -> None:
    with pytest.raises(LiveQualityGateExecutionError):
        run_live_quality_gate(
            policy=policy(),
            settings=settings(),
            output_dir=tmp_path,
            case_runner=lambda **_kwargs: object(),
            judge_runner=passing_judge_runner,
        )


def test_cli_maps_pass_fail_and_configuration_errors(capsys: pytest.CaptureFixture[str]) -> None:
    from scripts.live_quality_gate import cli

    with (
        patch.object(sys, "argv", ["live_quality_gate", "--json"]),
        patch.object(cli, "run_live_quality_gate", return_value={"passed": True}),
    ):
        assert cli.main() == 0

    with (
        patch.object(sys, "argv", ["live_quality_gate", "--json"]),
        patch.object(cli, "run_live_quality_gate", return_value={"passed": False}),
    ):
        assert cli.main() == 1

    with (
        patch.object(sys, "argv", ["live_quality_gate", "--json"]),
        patch.object(
            cli,
            "run_live_quality_gate",
            side_effect=LiveQualityGateConfigurationError("judge-key leaked"),
        ),
    ):
        assert cli.main() == 2

    captured = capsys.readouterr()
    assert "judge-key" not in captured.err
    assert json.loads(captured.err) == {
        "passed": False,
        "failure_type": "configuration-error",
        "code": "LIVE_QUALITY_CONFIGURATION_INVALID",
    }


def test_cli_passes_policy_output_and_deterministic_only_arguments() -> None:
    from scripts.live_quality_gate import cli

    with (
        patch.object(
            sys,
            "argv",
            [
                "live_quality_gate",
                "--policy",
                "custom-policy.json",
                "--output-dir",
                "custom-reports",
                "--deterministic-only",
            ],
        ),
        patch.object(cli, "run_live_quality_gate", return_value={"passed": True}) as run_gate,
    ):
        assert cli.main() == 0

    run_gate.assert_called_once_with(
        policy_path="custom-policy.json",
        output_dir="custom-reports",
        deterministic_only=True,
    )
