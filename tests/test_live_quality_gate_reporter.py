from __future__ import annotations

import json
from pathlib import Path

from scripts.gates import GateCheckResult, GateFailureType
from scripts.live_quality_gate.evaluator import (
    evaluate_deterministic_case,
    evaluate_policy_thresholds,
)
from scripts.live_quality_gate.models import (
    LiveQualitySliceThresholds,
    RequiredSliceCoverage,
    SliceThreshold,
)
from scripts.live_quality_gate.reporter import (
    build_live_quality_report,
    render_live_quality_summary,
    write_live_quality_report,
)
from tests.test_live_quality_gate_client import policy, settings
from tests.test_live_quality_gate_evaluator import make_case, make_observation


def scored_result():
    return evaluate_deterministic_case(
        make_case(),
        make_observation(),
        top_k=2,
    ).with_judge_result(
        passed=True,
        scores={"faithfulness": 1.0, "answer_relevance": 0.9},
    )


def passing_metrics() -> dict[str, object]:
    return {
        "case_count": 1,
        "pass_rate": 1.0,
        "deterministic_pass_rate": 1.0,
        "judge_pass_rate": 1.0,
        "recall_at_k": 1.0,
        "mrr": 1.0,
        "ndcg_at_k": 1.0,
        "fallback_rate": 0.0,
        "retrieval_degradation_rate": 0.0,
        "p95_latency_ms": 1000.0,
        "estimated_cost_usd": 0.02,
        "avg_judge_scores": {"faithfulness": 1.0, "answer_relevance": 0.9},
        "by_risk_tag": {},
        "by_query_type": {"single_recipe": {"case_count": 1, "pass_rate": 1.0}},
        "by_cuisine": {"sichuan": {"case_count": 1, "pass_rate": 1.0}},
        "by_constraint_type": {"weekday": {"case_count": 1, "pass_rate": 1.0}},
        "by_response_mode": {"grounded_answer": {"case_count": 1, "pass_rate": 1.0}},
        "by_strategy": {"combined": {"case_count": 1, "pass_rate": 1.0}},
    }


def test_policy_thresholds_fail_missing_required_slice_as_coverage_regression() -> None:
    gate_policy = policy().model_copy(
        update={
            "required_slice_coverage": RequiredSliceCoverage(
                risk_tags={"prompt_injection": 1},
                query_types={"single_recipe": 1},
                cuisines={"sichuan": 1},
                constraint_types={},
                response_modes={"grounded_answer": 1},
            )
        }
    )

    checks = evaluate_policy_thresholds(gate_policy, passing_metrics())

    failed = [check for check in checks if not check.passed]
    assert any(check.name == "coverage.risk_tags.prompt_injection" for check in failed)
    assert any(check.code == "SLICE_COVERAGE_MISSING" for check in failed)
    assert failed[0].failure_type is GateFailureType.COVERAGE_REGRESSION


def test_policy_thresholds_enforce_configured_slice_pass_rate() -> None:
    gate_policy = policy().model_copy(
        update={
            "slice_thresholds": LiveQualitySliceThresholds(
                query_types={
                    "single_recipe": SliceThreshold(
                        minimum_case_count=1,
                        minimum_pass_rate=0.9,
                    )
                },
                strategies={
                    "combined": SliceThreshold(
                        minimum_case_count=2,
                        minimum_pass_rate=1.0,
                    )
                },
            )
        }
    )
    metrics = passing_metrics()
    metrics["by_query_type"] = {"single_recipe": {"case_count": 1, "pass_rate": 0.8}}
    metrics["by_strategy"] = {"combined": {"case_count": 1, "pass_rate": 1.0}}

    checks = evaluate_policy_thresholds(gate_policy, metrics)
    by_name = {check.name: check for check in checks}

    assert by_name["slice.query_types.single_recipe.pass_rate"].code == "METRIC_BELOW_MINIMUM"
    assert (
        by_name["slice.query_types.single_recipe.pass_rate"].failure_type
        is GateFailureType.QUALITY_REGRESSION
    )
    assert by_name["slice.strategies.combined.case_count"].code == "METRIC_BELOW_MINIMUM"
    assert (
        by_name["slice.strategies.combined.case_count"].failure_type
        is GateFailureType.COVERAGE_REGRESSION
    )


def test_report_writes_safe_json_markdown_and_manual_review_sample(tmp_path: Path) -> None:
    result = scored_result()
    report = build_live_quality_report(
        policy=policy(),
        settings=settings(),
        metrics=passing_metrics(),
        checks=tuple(result.checks),
        results=(result,),
    )

    paths = write_live_quality_report(report, tmp_path)

    report_json = tmp_path / "report.json"
    summary_md = tmp_path / "summary.md"
    sample_jsonl = tmp_path / "manual_review_sample.jsonl"
    persisted = json.loads(report_json.read_text(encoding="utf-8"))
    combined = report_json.read_text(encoding="utf-8") + summary_md.read_text(encoding="utf-8")
    sample = json.loads(sample_jsonl.read_text(encoding="utf-8").strip())

    assert paths == (report_json, summary_md, sample_jsonl)
    assert persisted["schema_version"] == 1
    assert persisted["target"] == {
        "api_host": "serving.example.com:443",
        "judge_host": "judge.example.com",
    }
    assert persisted["artifacts"] == {
        "report_json": "report.json",
        "summary_md": "summary.md",
        "manual_review_sample_jsonl": "manual_review_sample.jsonl",
    }
    assert persisted["manual_review_sample_count"] == 1
    assert sample["case_id"] == "grounded_mapo_tofu"
    assert sample["owner"] == "business-quality"
    assert "grounded_mapo_tofu" in combined
    assert "serving-token" not in combined
    assert "judge-key" not in combined
    assert "Authorization" not in combined
    assert summary_md.read_bytes() == render_live_quality_summary(persisted)
    assert b"\r\n" not in summary_md.read_bytes()


def test_report_uses_aggregate_thresholds_for_valid_case_quality_failures() -> None:
    result = scored_result().with_judge_result(
        passed=False,
        scores={"faithfulness": 1.0, "answer_relevance": 0.7},
    )
    report = build_live_quality_report(
        policy=policy(),
        settings=settings(),
        metrics=passing_metrics(),
        checks=(
            GateCheckResult.fail_check(
                "case.grounded_mapo_tofu.judge",
                failure_type=GateFailureType.QUALITY_REGRESSION,
                code="JUDGE_QUALITY_FAILED",
            ),
            GateCheckResult.pass_check("metrics.judge_pass_rate"),
        ),
        results=(result,),
    )

    assert report["passed"] is True
    assert report["cases"][0]["passed"] is False


def test_report_still_blocks_invalid_judge_protocol() -> None:
    result = scored_result()
    report = build_live_quality_report(
        policy=policy(),
        settings=settings(),
        metrics=passing_metrics(),
        checks=(
            GateCheckResult.fail_check(
                "case.grounded_mapo_tofu.judge",
                failure_type=GateFailureType.JUDGE_UNAVAILABLE,
                code="JUDGE_RESPONSE_INVALID",
            ),
        ),
        results=(result,),
    )

    assert report["passed"] is False
