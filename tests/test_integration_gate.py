from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any
from unittest.mock import Mock, patch

import pytest

from scripts.gates import GateCheckResult, GateFailureType
from scripts.integration_gate.models import (
    IntegrationGatePolicy,
    LiveCaseObservation,
    LiveCasePolicy,
    LiveCaseRunResult,
)
from scripts.integration_gate.service import (
    IntegrationGateConfigurationError,
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

        return LiveCaseRunResult(
            case_id=case.case_id,
            observation=_observation(case),
            checks=(
                GateCheckResult.pass_check(
                    f"case.{case.case_id}.request",
                    code="CASE_OK",
                    expected=True,
                    actual=True,
                ),
            ),
        )

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
                        "stable_policy": "CASE_OK",
                        "secret_hint": "password raw-secret-token",
                        "auth_header": "Bearer abc",
                    },
                    actual={
                        "status": False,
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
    assert "CASE_OK" in combined
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
        return LiveCaseRunResult(
            case_id=case.case_id,
            observation=_observation(case),
            checks=(
                GateCheckResult.pass_check(
                    f"case.{case.case_id}.request",
                    code="CASE_OK",
                    expected="case.request",
                    actual="case.request",
                ),
            ),
        )

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
        "| case_id | executed | has_observation | evidence_count | latency_ms | "
        "total_tokens | estimated_cost_usd | check_codes |"
    ) in summary_text
    assert "vector_recipe_lookup" in summary_text
    assert "CASE_OK" in summary_text


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
        case_results=(
            LiveCaseRunResult(
                case_id="vector_recipe_lookup",
                observation=None,
                checks=(evaluation,),
            ),
        ),
    )

    assert "question" not in json.dumps(report, ensure_ascii=False)
