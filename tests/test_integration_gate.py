from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any
from unittest.mock import Mock, patch

import pytest

from scripts.gates import GateCheckResult, GateCheckStatus, GateFailureType
from scripts.integration_gate.models import (
    IntegrationCaseSummary,
    IntegrationGatePolicy,
    LiveCaseObservation,
    LiveCasePolicy,
    LiveCaseRunResult,
)
from scripts.integration_gate.service import (
    IntegrationGateConfigurationError,
    IntegrationGateExecutionError,
    run_integration_gate,
)


def _policy_payload() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "dependency_minimums": {
            "neo4j_recipe_count": 1,
            "milvus_entity_count": 1,
        },
        "timeouts": {
            "probe_seconds": 10.0,
            "request_seconds": 90.0,
        },
        "thresholds": {
            "maximum_fallback_rate": 0.0,
            "maximum_retrieval_degradation_rate": 0.0,
            "maximum_p95_latency_ms": 60_000.0,
            "maximum_estimated_cost_usd": 1.0,
        },
        "live_cases": [
            {
                "case_id": "vector_recipe_lookup",
                "question": "宫保鸡丁怎么做？",
                "allowed_strategies": ["hybrid_traditional", "combined"],
                "required_sources": ["vector"],
                "minimum_evidence_count": 1,
                "generation_required": True,
                "timeout_seconds": 60.0,
            },
            {
                "case_id": "graph_relationship_reasoning",
                "question": "花生和辣椒之间是什么关系？",
                "allowed_strategies": ["graph_rag", "combined"],
                "required_sources": ["graph_rag"],
                "minimum_evidence_count": 1,
                "generation_required": True,
                "timeout_seconds": 90.0,
            },
            {
                "case_id": "combined_constrained_recommendation",
                "question": "推荐一道清淡豆腐菜，并解释食材、风味和减脂条件。",
                "allowed_strategies": ["combined"],
                "required_sources": ["vector", "graph_rag"],
                "minimum_evidence_count": 1,
                "generation_required": True,
                "timeout_seconds": 90.0,
            },
        ],
    }


def _write_policy(tmp_path: Path) -> Path:
    policy_path = tmp_path / "integration_gate.json"
    policy_path.write_text(json.dumps(_policy_payload(), ensure_ascii=False), encoding="utf-8")
    return policy_path


def _policy_model() -> IntegrationGatePolicy:
    return IntegrationGatePolicy.model_validate(_policy_payload())


def _required_environ() -> dict[str, str]:
    return {
        "INTEGRATION_GATE_API_URL": "https://api_user:api_pass@api.example.com:8443/secret/path?token=query-token",
        "INTEGRATION_GATE_API_TOKEN": "Bearer raw-secret-token",
        "NEO4J_URI": "bolt://neo4j_user:neo4j_pass@graph.internal:7687/db?password=hidden",
        "NEO4J_USER": "neo4j",
        "NEO4J_PASSWORD": "password-from-env",
        "NEO4J_DATABASE": "neo4j",
        "MILVUS_HOST": "user:pass@milvus.internal/path?token=milvus-token",
        "MILVUS_PORT": "19530",
        "MILVUS_COLLECTION_NAME": "cooking_knowledge",
    }


def _passing_probe_checks() -> tuple[GateCheckResult, ...]:
    return (
        GateCheckResult.pass_check(
            "dependency.neo4j.recipe_count",
            code="NEO4J_READY",
            expected={"minimum": 1},
            actual=3,
        ),
        GateCheckResult.pass_check(
            "dependency.milvus.entity_count",
            code="MILVUS_READY",
            expected={"minimum": 1},
            actual=5,
        ),
        GateCheckResult.pass_check(
            "dependency.serving.ready",
            code="SERVING_API_READY",
            expected=True,
            actual=True,
        ),
    )


def _observation(
    case: LiveCasePolicy,
    *,
    sources: frozenset[str] = frozenset({"vector", "graph_rag"}),
) -> LiveCaseObservation:
    return LiveCaseObservation(
        case_id=case.case_id,
        strategy=case.allowed_strategies[-1],
        sources=sources,
        evidence_count=2,
        fallback_used=False,
        retrieval_degraded=False,
        latency_ms=100.0,
        total_tokens=42,
        estimated_cost_usd=0.01,
    )


def _case_ids(report: dict[str, Any]) -> list[str]:
    return [case["case_id"] for case in report["cases"]]


def _passing_case_result(case: LiveCasePolicy) -> LiveCaseRunResult:
    checks = tuple(
        GateCheckResult.pass_check(
            f"case.{case.case_id}.{suffix}",
            code=code,
            expected=True,
            actual=True,
        )
        for suffix, code in (
            ("strategy", "STRATEGY_OK"),
            ("sources", "REQUIRED_SOURCES_OK"),
            ("evidence_count", "EVIDENCE_COUNT_OK"),
            ("fallback", "FALLBACK_OK"),
            ("retrieval_degradation", "RETRIEVAL_DEGRADATION_OK"),
            ("model_usage", "MODEL_USAGE_OK"),
            ("latency", "CASE_LATENCY_OK"),
        )
    )
    return LiveCaseRunResult(
        case_id=case.case_id,
        observation=_observation(case),
        checks=checks,
    )


def test_failed_probe_blocks_live_cases_without_calling_case_runner(tmp_path: Path) -> None:
    policy_path = _write_policy(tmp_path)
    case_runner = Mock()

    def probe_runner(**_kwargs: object) -> tuple[GateCheckResult, ...]:
        return (
            GateCheckResult.fail_check(
                "dependency.neo4j.recipe_count",
                failure_type=GateFailureType.DEPENDENCY_UNAVAILABLE,
                code="NEO4J_UNAVAILABLE",
                expected={"minimum": 1},
                actual=None,
            ),
            *_passing_probe_checks()[1:],
        )

    report = run_integration_gate(
        policy_path=policy_path,
        output_dir=tmp_path / "reports",
        environ=_required_environ(),
        probe_runner=probe_runner,
        case_runner=case_runner,
    )

    case_runner.assert_not_called()
    blocked_checks = [check for check in report["checks"] if check["code"] == "PREREQUISITE_FAILED"]

    assert [check["name"] for check in blocked_checks] == [
        "case.vector_recipe_lookup",
        "case.graph_relationship_reasoning",
        "case.combined_constrained_recommendation",
    ]
    assert all(check["status"] == "blocked" for check in blocked_checks)
    assert report["cases"] == [
        {
            "case_id": case_id,
            "executed": False,
            "status": "blocked",
            "has_observation": False,
            "evidence_count": 0,
            "latency_ms": 0.0,
            "total_tokens": 0,
            "estimated_cost_usd": 0.0,
            "check_codes": ["PREREQUISITE_FAILED"],
        }
        for case_id in (
            "vector_recipe_lookup",
            "graph_relationship_reasoning",
            "combined_constrained_recommendation",
        )
    ]
    assert report["passed"] is False


def test_successful_probes_run_every_case_even_after_case_failure(tmp_path: Path) -> None:
    policy_path = _write_policy(tmp_path)
    called_case_ids: list[str] = []

    def case_runner(**kwargs: object) -> LiveCaseRunResult:
        case = kwargs["case"]
        assert isinstance(case, LiveCasePolicy)
        called_case_ids.append(case.case_id)

        if len(called_case_ids) == 1:
            return LiveCaseRunResult(
                case_id=case.case_id,
                observation=None,
                checks=(
                    GateCheckResult.fail_check(
                        f"case.{case.case_id}.request",
                        failure_type=GateFailureType.DEPENDENCY_UNAVAILABLE,
                        code="SERVING_API_REQUEST_FAILED",
                        expected=True,
                        actual=False,
                    ),
                ),
            )

        return _passing_case_result(case)

    report = run_integration_gate(
        policy_path=policy_path,
        output_dir=tmp_path / "reports",
        environ=_required_environ(),
        probe_runner=lambda **_kwargs: _passing_probe_checks(),
        case_runner=case_runner,
    )

    assert called_case_ids == [
        "vector_recipe_lookup",
        "graph_relationship_reasoning",
        "combined_constrained_recommendation",
    ]
    assert _case_ids(report) == called_case_ids
    assert [case["status"] for case in report["cases"]] == ["failed", "passed", "passed"]
    assert report["passed"] is False


def test_report_json_and_markdown_use_safe_allowlisted_fields(tmp_path: Path) -> None:
    policy_path = _write_policy(tmp_path)

    def case_runner(**kwargs: object) -> LiveCaseRunResult:
        case = kwargs["case"]
        assert isinstance(case, LiveCasePolicy)
        return LiveCaseRunResult(
            case_id=case.case_id,
            observation=None,
            checks=(
                GateCheckResult.fail_check(
                    f"case.{case.case_id}.request",
                    failure_type=GateFailureType.DEPENDENCY_UNAVAILABLE,
                    code="SERVING_API_REQUEST_FAILED",
                    expected={
                        "stable_policy": "CustomerQuestionAlpha",
                        "secret_hint": "password raw-secret-token",
                        "auth_header": "Bearer abc",
                    },
                    actual={
                        "status": False,
                        "provider_payload": "ProviderPayloadABC",
                        "url": "https://host/secret/path?token=x",
                        "errors": ["RuntimeError('response body')", "raw exception details"],
                    },
                ),
            ),
        )

    output_dir = tmp_path / "reports"
    report = run_integration_gate(
        policy_path=policy_path,
        output_dir=output_dir,
        environ=_required_environ(),
        probe_runner=lambda **_kwargs: _passing_probe_checks(),
        case_runner=case_runner,
    )
    report_json = output_dir / "report.json"
    summary_md = output_dir / "summary.md"
    report_text = report_json.read_text(encoding="utf-8")
    summary_text = summary_md.read_text(encoding="utf-8")
    combined = f"{report_text}\n{summary_text}"

    assert {
        "schema_version",
        "generated_at",
        "target",
        "metrics",
        "checks",
        "cases",
    } <= set(report)
    assert "vector_recipe_lookup" in combined
    assert "SERVING_API_REQUEST_FAILED" in combined
    assert "CustomerQuestionAlpha" not in combined
    assert "ProviderPayloadABC" not in combined
    assert "宫保鸡丁怎么做？" not in combined
    assert "花生和辣椒之间是什么关系？" not in combined
    assert "推荐一道清淡豆腐菜" not in combined
    assert "password" not in combined.lower()
    assert "secret" not in combined.lower()
    assert "Bearer" not in combined
    assert "raw-secret-token" not in combined
    assert "/secret/path" not in combined
    assert "query-token" not in combined
    assert "https://host" not in combined
    assert "token=x" not in combined
    assert "Bearer abc" not in combined
    assert "raw exception" not in combined.lower()
    assert "exception" not in combined.lower()
    assert "RuntimeError" not in combined
    assert "response body" not in combined.lower()


def test_passing_report_markdown_cases_section_lists_case_ids_and_codes(tmp_path: Path) -> None:
    policy_path = _write_policy(tmp_path)

    def case_runner(**kwargs: object) -> LiveCaseRunResult:
        case = kwargs["case"]
        assert isinstance(case, LiveCasePolicy)
        return _passing_case_result(case)

    output_dir = tmp_path / "reports"
    run_integration_gate(
        policy_path=policy_path,
        output_dir=output_dir,
        environ=_required_environ(),
        probe_runner=lambda **_kwargs: _passing_probe_checks(),
        case_runner=case_runner,
    )

    summary_text = (output_dir / "summary.md").read_text(encoding="utf-8")

    assert "## Cases" in summary_text
    assert (
        "| case_id | executed | status | has_observation | evidence_count | latency_ms | "
        "total_tokens | estimated_cost_usd | check_codes |"
    ) in summary_text
    assert "vector_recipe_lookup" in summary_text
    assert "STRATEGY_OK" in summary_text


@pytest.mark.parametrize("status", [GateCheckStatus.PASSED, GateCheckStatus.BLOCKED])
def test_rejects_nonfailed_request_check_without_observation(
    tmp_path: Path,
    status: GateCheckStatus,
) -> None:
    policy_path = _write_policy(tmp_path)

    def case_runner(**kwargs: object) -> LiveCaseRunResult:
        case = kwargs["case"]
        assert isinstance(case, LiveCasePolicy)
        check = (
            GateCheckResult.pass_check(
                f"case.{case.case_id}.request",
                code="CASE_REQUEST_OK",
            )
            if status is GateCheckStatus.PASSED
            else GateCheckResult.block_check(
                f"case.{case.case_id}.request",
                code="CASE_DEPENDENCY_BLOCKED",
            )
        )
        return LiveCaseRunResult(
            case_id=case.case_id,
            observation=None,
            checks=(check,),
        )

    with pytest.raises(IntegrationGateExecutionError):
        run_integration_gate(
            policy_path=policy_path,
            output_dir=tmp_path / "reports",
            environ=_required_environ(),
            probe_runner=lambda **_kwargs: _passing_probe_checks(),
            case_runner=case_runner,
        )


def test_explicit_empty_environ_does_not_fall_back_to_process_environment(
    tmp_path: Path,
) -> None:
    policy_path = _write_policy(tmp_path)
    probe_runner = Mock()

    with patch.dict(os.environ, _required_environ(), clear=True):
        with pytest.raises(IntegrationGateConfigurationError):
            run_integration_gate(
                policy_path=policy_path,
                output_dir=tmp_path / "reports",
                environ={},
                probe_runner=probe_runner,
            )

    probe_runner.assert_not_called()


@pytest.mark.parametrize(
    "probe_checks",
    [
        (),
        _passing_probe_checks()[:2],
        (_passing_probe_checks()[0],) * 3,
        (*_passing_probe_checks(), GateCheckResult.pass_check("dependency.extra")),
        (*_passing_probe_checks()[:2], object()),
    ],
    ids=["empty", "missing", "duplicate", "extra", "wrong-type"],
)
def test_rejects_malformed_probe_runner_results(
    tmp_path: Path,
    probe_checks: tuple[object, ...],
) -> None:
    case_runner = Mock()

    with pytest.raises(IntegrationGateExecutionError):
        run_integration_gate(
            policy_path=_write_policy(tmp_path),
            output_dir=tmp_path / "reports",
            environ=_required_environ(),
            probe_runner=lambda **_kwargs: probe_checks,
            case_runner=case_runner,
        )

    case_runner.assert_not_called()


@pytest.mark.parametrize("checks", [(), (object(),)], ids=["empty", "wrong-type"])
def test_rejects_invalid_live_case_checks(
    tmp_path: Path,
    checks: tuple[object, ...],
) -> None:
    def case_runner(**kwargs: object) -> LiveCaseRunResult:
        case = kwargs["case"]
        assert isinstance(case, LiveCasePolicy)
        return LiveCaseRunResult(case_id=case.case_id, observation=None, checks=checks)

    with pytest.raises(IntegrationGateExecutionError):
        run_integration_gate(
            policy_path=_write_policy(tmp_path),
            output_dir=tmp_path / "reports",
            environ=_required_environ(),
            probe_runner=lambda **_kwargs: _passing_probe_checks(),
            case_runner=case_runner,
        )


def test_rejects_live_case_result_id_mismatch(tmp_path: Path) -> None:
    def case_runner(**kwargs: object) -> LiveCaseRunResult:
        case = kwargs["case"]
        assert isinstance(case, LiveCasePolicy)
        result = _passing_case_result(case)
        return LiveCaseRunResult(
            case_id="ProviderPayloadABC",
            observation=result.observation,
            checks=result.checks,
        )

    with pytest.raises(IntegrationGateExecutionError):
        run_integration_gate(
            policy_path=_write_policy(tmp_path),
            output_dir=tmp_path / "reports",
            environ=_required_environ(),
            probe_runner=lambda **_kwargs: _passing_probe_checks(),
            case_runner=case_runner,
        )


def test_rejects_live_case_observation_id_mismatch(tmp_path: Path) -> None:
    def case_runner(**kwargs: object) -> LiveCaseRunResult:
        case = kwargs["case"]
        assert isinstance(case, LiveCasePolicy)
        observation = _observation(case)
        mismatched_observation = LiveCaseObservation(
            case_id="CustomerQuestionAlpha",
            strategy=observation.strategy,
            sources=observation.sources,
            evidence_count=observation.evidence_count,
            fallback_used=observation.fallback_used,
            retrieval_degraded=observation.retrieval_degraded,
            latency_ms=observation.latency_ms,
            total_tokens=observation.total_tokens,
            estimated_cost_usd=observation.estimated_cost_usd,
        )
        return LiveCaseRunResult(
            case_id=case.case_id,
            observation=mismatched_observation,
            checks=_passing_case_result(case).checks,
        )

    with pytest.raises(IntegrationGateExecutionError):
        run_integration_gate(
            policy_path=_write_policy(tmp_path),
            output_dir=tmp_path / "reports",
            environ=_required_environ(),
            probe_runner=lambda **_kwargs: _passing_probe_checks(),
            case_runner=case_runner,
        )


@pytest.mark.parametrize("mutation", ["missing", "duplicate", "extra"])
def test_rejects_incomplete_observed_case_check_set(
    tmp_path: Path,
    mutation: str,
) -> None:
    def case_runner(**kwargs: object) -> LiveCaseRunResult:
        case = kwargs["case"]
        assert isinstance(case, LiveCasePolicy)
        valid = _passing_case_result(case)
        if mutation == "missing":
            checks = valid.checks[:-1]
        elif mutation == "duplicate":
            checks = (*valid.checks, valid.checks[0])
        else:
            checks = (
                *valid.checks,
                GateCheckResult.pass_check(
                    f"case.{case.case_id}.provider_payload",
                    code="PROVIDER_PAYLOAD_OK",
                ),
            )
        return LiveCaseRunResult(
            case_id=case.case_id,
            observation=valid.observation,
            checks=checks,
        )

    with pytest.raises(IntegrationGateExecutionError):
        run_integration_gate(
            policy_path=_write_policy(tmp_path),
            output_dir=tmp_path / "reports",
            environ=_required_environ(),
            probe_runner=lambda **_kwargs: _passing_probe_checks(),
            case_runner=case_runner,
        )


@pytest.mark.parametrize(("report", "expected"), [({"passed": True}, 0), ({"passed": False}, 1)])
def test_cli_maps_evaluated_status_to_exit_code(report: dict[str, bool], expected: int) -> None:
    from scripts.integration_gate import cli

    with (
        patch.object(sys, "argv", ["integration_gate", "--json"]),
        patch.object(cli, "run_integration_gate", return_value=report),
    ):
        assert cli.main() == expected


def test_cli_returns_configuration_error_status_without_sensitive_details(
    capsys: pytest.CaptureFixture[str],
) -> None:
    from scripts.integration_gate import cli

    error = IntegrationGateConfigurationError(
        "bad password raw-secret-token RuntimeError('response body')"
    )
    with (
        patch.object(sys, "argv", ["integration_gate", "--json"]),
        patch.object(cli, "run_integration_gate", side_effect=error),
    ):
        assert cli.main() == 2

    captured = capsys.readouterr()
    payload = json.loads(captured.err)

    assert payload == {
        "passed": False,
        "failure_type": "gate-error",
        "code": "INTEGRATION_GATE_CONFIGURATION_INVALID",
    }
    assert "password" not in captured.err.lower()
    assert "raw-secret-token" not in captured.err
    assert "RuntimeError" not in captured.err
    assert "response body" not in captured.err


def test_cli_returns_safe_execution_error_for_runner_failure(
    capsys: pytest.CaptureFixture[str],
) -> None:
    from scripts.integration_gate import cli

    with (
        patch.object(sys, "argv", ["integration_gate", "--json"]),
        patch.object(
            cli,
            "run_integration_gate",
            side_effect=RuntimeError("provider runner leaked CustomerQuestionAlpha"),
        ),
    ):
        assert cli.main() == 2

    captured = capsys.readouterr()
    assert json.loads(captured.err) == {
        "passed": False,
        "failure_type": "gate-error",
        "code": "INTEGRATION_GATE_EXECUTION_FAILED",
    }
    assert "CustomerQuestionAlpha" not in captured.err
    assert "traceback" not in captured.err.lower()


def test_cli_returns_safe_execution_error_when_report_write_fails(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from scripts.integration_gate import cli, service

    policy_path = _write_policy(tmp_path)

    def run_gate_with_fakes(**kwargs: object) -> dict[str, Any]:
        return service.run_integration_gate(
            policy_path=kwargs["policy_path"],
            output_dir=kwargs["output_dir"],
            environ=_required_environ(),
            probe_runner=lambda **_kwargs: _passing_probe_checks(),
            case_runner=lambda **case_kwargs: _passing_case_result(case_kwargs["case"]),
        )

    with (
        patch.object(
            sys,
            "argv",
            [
                "integration_gate",
                "--policy",
                str(policy_path),
                "--output-dir",
                str(tmp_path / "reports"),
                "--json",
            ],
        ),
        patch.object(cli, "run_integration_gate", side_effect=run_gate_with_fakes),
        patch.object(
            service,
            "write_integration_report",
            side_effect=OSError("write failed at C:/customer/ProviderPayloadABC"),
        ),
    ):
        assert cli.main() == 2

    captured = capsys.readouterr()
    assert json.loads(captured.err) == {
        "passed": False,
        "failure_type": "gate-error",
        "code": "INTEGRATION_GATE_EXECUTION_FAILED",
    }
    assert "ProviderPayloadABC" not in captured.err
    assert "traceback" not in captured.err.lower()


def test_cli_passes_policy_and_output_dir_arguments() -> None:
    from scripts.integration_gate import cli

    report = {"passed": True}
    with (
        patch.object(
            sys,
            "argv",
            [
                "integration_gate",
                "--policy",
                "custom-policy.json",
                "--output-dir",
                "custom-reports",
            ],
        ),
        patch.object(cli, "run_integration_gate", return_value=report) as run_gate,
    ):
        assert cli.main() == 0

    run_gate.assert_called_once_with(
        policy_path="custom-policy.json",
        output_dir="custom-reports",
    )


def test_execution_error_is_exported_from_public_integration_gate_package() -> None:
    from scripts import integration_gate

    assert integration_gate.IntegrationGateExecutionError is IntegrationGateExecutionError
    assert "IntegrationGateExecutionError" in integration_gate.__all__


def test_building_safe_report_from_models_keeps_policy_question_out() -> None:
    from scripts.integration_gate.reporter import build_integration_report

    policy = _policy_model()
    evaluation = GateCheckResult.fail_check(
        "case.vector_recipe_lookup.request",
        failure_type=GateFailureType.DEPENDENCY_UNAVAILABLE,
        code="SERVING_API_REQUEST_FAILED",
        expected=True,
        actual=False,
    )
    report = build_integration_report(
        policy=policy,
        settings=type(
            "SafeSettings",
            (),
            {"safe_target_identity": lambda _self: {"api_host": "api.example.com"}},
        )(),
        evaluation=type(
            "Evaluation",
            (),
            {
                "passed": False,
                "checks": (evaluation,),
                "failure_type_counts": {"dependency-unavailable": 1},
            },
        )(),
        case_summaries=(
            IntegrationCaseSummary(
                case_id="vector_recipe_lookup",
                executed=True,
                status=GateCheckStatus.FAILED,
                observation=None,
                check_codes=(evaluation.code,),
            ),
        ),
    )

    assert "question" not in json.dumps(report, ensure_ascii=False)


def test_unknown_evidence_structures_are_redacted_as_a_whole(tmp_path: Path) -> None:
    def case_runner(**kwargs: object) -> LiveCaseRunResult:
        case = kwargs["case"]
        assert isinstance(case, LiveCasePolicy)
        return LiveCaseRunResult(
            case_id=case.case_id,
            observation=None,
            checks=(
                GateCheckResult.fail_check(
                    f"case.{case.case_id}.request",
                    failure_type=GateFailureType.CONTRACT_REGRESSION,
                    code="PROVIDER_PAYLOAD_INVALID",
                    expected={"customer_numeric_id": 912345678},
                    actual={"provider_numeric_id": 898765432, "accepted": False},
                ),
            ),
        )

    output_dir = tmp_path / "reports"
    run_integration_gate(
        policy_path=_write_policy(tmp_path),
        output_dir=output_dir,
        environ=_required_environ(),
        probe_runner=lambda **_kwargs: _passing_probe_checks(),
        case_runner=case_runner,
    )
    combined = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (output_dir / "report.json", output_dir / "summary.md")
    )

    assert "912345678" not in combined
    assert "898765432" not in combined
    assert "customer_numeric_id" not in combined
    assert "provider_numeric_id" not in combined


def test_report_write_boundary_drops_unknown_fields_and_user_paths(tmp_path: Path) -> None:
    from scripts.integration_gate.reporter import write_integration_report

    output_dir = tmp_path / "reports"
    report = run_integration_gate(
        policy_path=_write_policy(tmp_path),
        output_dir=output_dir,
        environ=_required_environ(),
        probe_runner=lambda **_kwargs: _passing_probe_checks(),
        case_runner=lambda **kwargs: _passing_case_result(kwargs["case"]),
    )
    report["CustomerQuestionAlpha"] = "ProviderPayloadABC"
    report["artifacts"] = {
        "report_json": "C:/customer/CustomerQuestionAlpha/report.json",
        "summary_md": "C:/provider/ProviderPayloadABC/summary.md",
    }

    final_dir = tmp_path / "final"
    write_integration_report(report, final_dir)
    report_text = (final_dir / "report.json").read_text(encoding="utf-8")
    summary_text = (final_dir / "summary.md").read_text(encoding="utf-8")
    persisted = json.loads(report_text)

    assert "CustomerQuestionAlpha" not in report_text + summary_text
    assert "ProviderPayloadABC" not in report_text + summary_text
    assert persisted["artifacts"] == {
        "report_json": "report.json",
        "summary_md": "summary.md",
    }


def test_report_artifacts_use_fixed_safe_relative_names(tmp_path: Path) -> None:
    output_dir = tmp_path / "CustomerQuestionAlpha" / "ProviderPayloadABC"
    report = run_integration_gate(
        policy_path=_write_policy(tmp_path),
        output_dir=output_dir,
        environ=_required_environ(),
        probe_runner=lambda **_kwargs: _passing_probe_checks(),
        case_runner=lambda **kwargs: _passing_case_result(kwargs["case"]),
    )

    assert report["artifacts"] == {
        "report_json": "report.json",
        "summary_md": "summary.md",
    }
    assert "CustomerQuestionAlpha" not in json.dumps(report)
    assert "ProviderPayloadABC" not in json.dumps(report)


def test_final_report_projection_derives_consistent_status_and_metrics(tmp_path: Path) -> None:
    from scripts.integration_gate.reporter import write_integration_report

    malicious_report = {
        "generated_at": "2026-07-04T00:00:00+00:00",
        "passed": True,
        "target": {
            "api_host": "api.example.com",
            "neo4j_host": "neo4j.example.com",
            "milvus_host": "milvus.example.com",
        },
        "metrics": {
            "check_count": 999,
            "failed_count": 0,
            "blocked_count": 0,
            "case_count": 999,
            "executed_case_count": 999,
            "observation_count": 999,
            "failure_type_counts": {"quality-regression": 999},
            "total_estimated_cost_usd": 999.0,
            "max_latency_ms": 999.0,
        },
        "checks": [
            {
                "name": "check.passed",
                "status": "passed",
                "passed": False,
                "failure_type": "quality-regression",
                "code": "PASSED_CHECK",
                "duration_ms": 1.0,
            },
            {
                "name": "check.failed",
                "status": "failed",
                "passed": True,
                "failure_type": "CustomerQuestionAlpha",
                "code": "FAILED_CHECK",
                "duration_ms": 2.0,
            },
            {
                "name": "check.blocked",
                "status": "blocked",
                "passed": True,
                "failure_type": "budget-regression",
                "code": "BLOCKED_CHECK",
                "duration_ms": 3.0,
            },
        ],
        "cases": [
            {
                "case_id": "not_executed",
                "executed": False,
                "status": "passed",
                "has_observation": True,
                "evidence_count": 77,
                "latency_ms": 888.0,
                "total_tokens": 999,
                "estimated_cost_usd": 123.0,
                "check_codes": ["PASSED_CHECK"],
            },
            {
                "case_id": "executed",
                "executed": True,
                "status": "passed",
                "has_observation": True,
                "evidence_count": 2,
                "latency_ms": 25.0,
                "total_tokens": 10,
                "estimated_cost_usd": 0.25,
                "check_codes": ["PASSED_CHECK"],
            },
        ],
    }

    write_integration_report(malicious_report, tmp_path)
    report_text = (tmp_path / "report.json").read_text(encoding="utf-8")
    summary_text = (tmp_path / "summary.md").read_text(encoding="utf-8")
    persisted = json.loads(report_text)

    assert persisted["passed"] is False
    assert [check["passed"] for check in persisted["checks"]] == [True, False, False]
    assert [check["failure_type"] for check in persisted["checks"]] == [
        None,
        "gate-error",
        None,
    ]
    assert persisted["cases"][0] == {
        "case_id": "not_executed",
        "executed": False,
        "status": "blocked",
        "has_observation": False,
        "evidence_count": 0,
        "latency_ms": 0.0,
        "total_tokens": 0,
        "estimated_cost_usd": 0.0,
        "check_codes": ["PASSED_CHECK"],
    }
    assert persisted["metrics"] == {
        "check_count": 3,
        "failed_count": 1,
        "blocked_count": 1,
        "case_count": 2,
        "executed_case_count": 1,
        "observation_count": 1,
        "failure_type_counts": {"gate-error": 1},
        "total_estimated_cost_usd": 0.25,
        "max_latency_ms": 25.0,
    }
    assert "Status: FAIL" in summary_text
    assert "Status: PASS" not in summary_text
    assert "CustomerQuestionAlpha" not in report_text + summary_text
