from __future__ import annotations

import json
import zipfile
from dataclasses import replace
from pathlib import Path

import pytest

from scripts.gates import GateCheckResult, GateFailureType
from scripts.live_quality_gate.evaluator import evaluate_policy_thresholds
from scripts.live_quality_gate.models import LiveQualityGatePolicy
from scripts.release_evidence import capture as capture_module
from scripts.release_evidence.capture import (
    CaptureInputs,
    ReleaseEvidenceCaptureError,
    capture_release_evidence,
)
from scripts.release_evidence.models import load_capture_receipt
from tests.release_evidence_fixtures import git, make_release_evidence_fixture, write_json


def capture_inputs(fixture) -> CaptureInputs:
    return CaptureInputs(
        repository_root=fixture.repository_root,
        repository="owner/repository",
        package_version="0.4.0rc1",
        tag="v0.4.0-rc.1",
        evaluated_commit=fixture.evaluated_commit,
        integration_policy_path=fixture.integration_policy,
        live_quality_policy_path=fixture.live_quality_policy,
        integration_report_path=fixture.integration_report,
        live_quality_report_path=fixture.live_quality_report,
        diagnostics_path=fixture.diagnostics,
        artifact_manifest_path=fixture.artifact_manifest,
        judge_model="qwen3.7-plus",
        output_dir=fixture.output_dir,
    )


def _commit_tree_symlink(repository_root: Path, relative_path: str, target: Path) -> str:
    repository_root.joinpath(relative_path).write_text(
        target.resolve().as_posix(),
        encoding="utf-8",
    )
    blob = git(repository_root, "hash-object", "-w", relative_path)
    git(
        repository_root,
        "update-index",
        "--add",
        "--cacheinfo",
        "120000",
        blob,
        relative_path,
    )
    git(repository_root, "commit", "-m", f"test: link {relative_path}")
    return git(repository_root, "rev-parse", "HEAD")


def _check_detail(
    *,
    name: str,
    status: str,
    code: str,
    failure_type: str | None,
    expected: object = None,
    actual: object = None,
) -> dict[str, object]:
    return {
        "name": name,
        "status": status,
        "passed": status == "passed",
        "failure_type": failure_type,
        "code": code,
        "expected": expected,
        "actual": actual,
        "duration_ms": 1.0,
    }


def _integration_case_detail(*, status: str = "passed") -> dict[str, object]:
    return {
        "case_id": "vector_recipe_lookup",
        "executed": True,
        "status": status,
        "has_observation": True,
        "evidence_count": 1,
        "latency_ms": 1000.0,
        "total_tokens": 10,
        "estimated_cost_usd": 0.01,
        "check_codes": ["CASE_OK"],
    }


def _live_case_detail(
    case_id: str,
    *,
    judge_passed: bool = True,
    manual_review_sample: bool = True,
) -> dict[str, object]:
    return {
        "case_id": case_id,
        "query_type": "single_recipe",
        "cuisine": "sichuan",
        "constraint_types": [],
        "risk_tags": [],
        "response_mode": "grounded_answer",
        "strategy": "hybrid_traditional",
        "passed": judge_passed,
        "deterministic_passed": True,
        "judge_passed": judge_passed,
        "judge_scores": {
            "faithfulness": 1.0,
            "answer_relevance": 1.0,
            "safety": 1.0,
            "completeness": 1.0,
        },
        "failures": [],
        "metrics": {"recall_at_k": 1.0, "mrr": 1.0, "ndcg_at_k": 1.0},
        "manual_review": {
            "owner": "business-quality",
            "sample": manual_review_sample,
        },
        "answer_preview": "Mapo tofu uses tofu.",
        "evidence": [
            {
                "recipe_name": "Mapo Tofu",
                "source": "vector",
                "snippet": "Mapo tofu uses tofu and a spicy sauce.",
            }
        ],
    }


def _write_manual_review_jsonl(path: Path, rows: list[object]) -> None:
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False, allow_nan=False) + "\n" for row in rows),
        encoding="utf-8",
    )


def test_capture_builds_safe_receipt_and_deterministic_bundle(tmp_path: Path) -> None:
    fixture = make_release_evidence_fixture(tmp_path)
    inputs = capture_inputs(fixture)

    first = capture_release_evidence(
        inputs,
        generated_at="2026-07-16T08:00:00+00:00",
    )
    first_bytes = first.bundle_path.read_bytes()
    second = capture_release_evidence(
        inputs,
        generated_at="2026-07-16T08:00:00+00:00",
    )

    receipt = load_capture_receipt(first.receipt_path)
    assert second.bundle_path.read_bytes() == first_bytes
    assert receipt.provenance.evaluated_commit == fixture.evaluated_commit
    assert receipt.quality.metrics.case_count == 1
    assert receipt.quality.metrics.recall_at_k == 1.0
    assert receipt.runtime.profile.path == "profiles/eval_quality.toml"
    assert receipt.runtime.models.judge == "qwen3.7-plus"
    assert receipt.knowledge_base.index_signature == "index-signature"
    assert receipt.bundle.bytes == len(first_bytes)

    with zipfile.ZipFile(first.bundle_path) as archive:
        names = archive.namelist()
        assert names == sorted(names)
        assert "capture-receipt.json" not in names
        assert "checksums.json" in names
        checksums = json.loads(archive.read("checksums.json"))
        assert "checksums.json" not in checksums
        assert set(checksums) == set(names) - {"checksums.json"}
        for member in archive.infolist():
            assert member.compress_type == zipfile.ZIP_STORED
            assert member.date_time == (1980, 1, 1, 0, 0, 0)
            assert member.create_system == 3
            assert member.external_attr >> 16 == 0o100644


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("passed", False, "live quality report did not pass"),
        ("case_count", 0, "live quality case count must be positive"),
        ("judge_pass_rate", None, "live quality metric judge_pass_rate is invalid"),
    ],
)
def test_capture_rejects_invalid_live_quality_success(
    tmp_path: Path,
    field: str,
    value: object,
    message: str,
) -> None:
    fixture = make_release_evidence_fixture(tmp_path)
    report = json.loads(fixture.live_quality_report.read_text(encoding="utf-8"))
    if field == "passed":
        report["passed"] = value
    else:
        report["metrics"][field] = value
    write_json(fixture.live_quality_report, report)

    with pytest.raises(ReleaseEvidenceCaptureError, match=message):
        capture_release_evidence(capture_inputs(fixture))


def test_capture_rejects_missing_judge_metric(tmp_path: Path) -> None:
    fixture = make_release_evidence_fixture(tmp_path)
    report = json.loads(fixture.live_quality_report.read_text(encoding="utf-8"))
    report["metrics"].pop("judge_pass_rate")
    write_json(fixture.live_quality_report, report)

    with pytest.raises(
        ReleaseEvidenceCaptureError,
        match="live quality metric judge_pass_rate is invalid",
    ):
        capture_release_evidence(capture_inputs(fixture))


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ({"passed": False}, "integration report did not pass"),
        ({"metrics.failed_count": 1}, "failed or blocked checks"),
        ({"metrics.blocked_count": 1}, "failed or blocked checks"),
        ({"metrics.executed_case_count": 2}, "cases were not all executed"),
        (
            {"metrics.case_count": 2, "metrics.executed_case_count": 2},
            "policy and report case counts differ",
        ),
    ],
)
def test_capture_rejects_invalid_integration_success(
    tmp_path: Path,
    mutation: dict[str, object],
    message: str,
) -> None:
    fixture = make_release_evidence_fixture(tmp_path)
    report = json.loads(fixture.integration_report.read_text(encoding="utf-8"))
    for field, value in mutation.items():
        if field.startswith("metrics."):
            report["metrics"][field.removeprefix("metrics.")] = value
        else:
            report[field] = value
    write_json(fixture.integration_report, report)

    with pytest.raises(ReleaseEvidenceCaptureError, match=message):
        capture_release_evidence(capture_inputs(fixture))


def test_capture_rejects_live_quality_case_mismatch(tmp_path: Path) -> None:
    fixture = make_release_evidence_fixture(tmp_path)
    report = json.loads(fixture.live_quality_report.read_text(encoding="utf-8"))
    report["metrics"]["case_count"] = 2
    write_json(fixture.live_quality_report, report)

    with pytest.raises(ReleaseEvidenceCaptureError, match="policy and report case counts differ"):
        capture_release_evidence(capture_inputs(fixture))


def test_capture_rejects_non_ready_knowledge_artifact(tmp_path: Path) -> None:
    fixture = make_release_evidence_fixture(tmp_path)
    manifest = json.loads(fixture.artifact_manifest.read_text(encoding="utf-8"))
    manifest["stage"] = "stale"
    write_json(fixture.artifact_manifest, manifest)

    with pytest.raises(ReleaseEvidenceCaptureError, match="knowledge artifact is not ready"):
        capture_release_evidence(capture_inputs(fixture))


@pytest.mark.parametrize(
    "field",
    [
        "graph_signature",
        "document_signature",
        "embedding_signature",
        "index_signature",
    ],
)
def test_capture_rejects_blank_knowledge_signature(tmp_path: Path, field: str) -> None:
    fixture = make_release_evidence_fixture(tmp_path)
    manifest = json.loads(fixture.artifact_manifest.read_text(encoding="utf-8"))
    manifest[field] = "   "
    write_json(fixture.artifact_manifest, manifest)

    with pytest.raises(ReleaseEvidenceCaptureError, match="knowledge artifact field is missing"):
        capture_release_evidence(capture_inputs(fixture))


def test_capture_allows_semantic_secret_text_and_benign_url(tmp_path: Path) -> None:
    fixture = make_release_evidence_fixture(tmp_path)
    report = json.loads(fixture.live_quality_report.read_text(encoding="utf-8"))
    answer_preview = (
        "The customer asks whether this is a secret recipe. "
        "See https://docs.example.com/search?q=secret+recipe."
    )
    report["cases"][0]["answer_preview"] = answer_preview
    report["manual_review_sample"][0]["answer_preview"] = answer_preview
    write_json(fixture.live_quality_report, report)
    _write_manual_review_jsonl(
        fixture.live_quality_report.parent / "manual_review_sample.jsonl",
        report["manual_review_sample"],
    )

    capture_release_evidence(capture_inputs(fixture))


@pytest.mark.parametrize(
    ("report_name", "location"),
    [
        ("integration_report", "top_level"),
        ("integration_report", "target"),
        ("integration_report", "metrics"),
        ("integration_report", "artifacts"),
        ("integration_report", "case"),
        ("live_quality_report", "top_level"),
        ("live_quality_report", "target"),
        ("live_quality_report", "metrics"),
        ("live_quality_report", "artifacts"),
        ("live_quality_report", "slice_summary"),
        ("live_quality_report", "avg_judge_scores"),
        ("live_quality_report", "case"),
        ("live_quality_report", "case_metrics"),
        ("live_quality_report", "manual_review"),
        ("live_quality_report", "evidence"),
        ("live_quality_report", "manual_sample"),
        ("live_quality_report", "manual_evidence"),
    ],
)
def test_capture_rejects_unknown_gate_report_fields(
    tmp_path: Path,
    report_name: str,
    location: str,
) -> None:
    fixture = make_release_evidence_fixture(tmp_path)
    report_path = getattr(fixture, report_name)
    report = json.loads(report_path.read_text(encoding="utf-8"))
    if location == "top_level":
        target = report
    elif location in {"target", "metrics", "artifacts"}:
        target = report[location]
    elif location == "slice_summary":
        target = report["metrics"]["by_query_type"]["single_recipe"]
    elif location == "avg_judge_scores":
        target = report["metrics"]["avg_judge_scores"]
    elif location == "case":
        target = report["cases"][0]
    elif location == "case_metrics":
        target = report["cases"][0]["metrics"]
    elif location == "manual_review":
        target = report["cases"][0]["manual_review"]
    elif location == "evidence":
        target = report["cases"][0]["evidence"][0]
    elif location == "manual_sample":
        target = report["manual_review_sample"][0]
    else:
        target = report["manual_review_sample"][0]["evidence"][0]
    target["unknown_producer_field"] = "benign"
    write_json(report_path, report)

    with pytest.raises(ReleaseEvidenceCaptureError, match="schema"):
        capture_release_evidence(capture_inputs(fixture))


@pytest.mark.parametrize(
    ("location", "metric_name", "value"),
    [
        ("top_level", "total_tokens", "ghp_actual-secret-value"),
        ("target", "prompt_tokens", -1),
        ("metrics", "completion_tokens", float("nan")),
        ("case", "input_tokens", float("inf")),
    ],
)
def test_capture_rejects_token_metric_outside_producer_schema(
    tmp_path: Path,
    location: str,
    metric_name: str,
    value: object,
) -> None:
    fixture = make_release_evidence_fixture(tmp_path)
    report = json.loads(fixture.live_quality_report.read_text(encoding="utf-8"))
    if location == "top_level":
        target = report
    elif location in {"target", "metrics"}:
        target = report[location]
    else:
        target = report["cases"][0]
    target[metric_name] = value
    fixture.live_quality_report.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, allow_nan=True) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ReleaseEvidenceCaptureError, match="sensitive|schema"):
        capture_release_evidence(capture_inputs(fixture))


def test_capture_accepts_numeric_token_metric_at_producer_path(tmp_path: Path) -> None:
    fixture = make_release_evidence_fixture(tmp_path)
    report = json.loads(fixture.integration_report.read_text(encoding="utf-8"))
    report["cases"][0]["total_tokens"] = 20
    model_usage_check = next(
        check
        for check in report["checks"]
        if check["name"] == "case.vector_recipe_lookup.model_usage"
    )
    model_usage_check["actual"] = 20
    write_json(fixture.integration_report, report)

    capture_release_evidence(capture_inputs(fixture))


@pytest.mark.parametrize(
    "value",
    ["ghp_actual-secret-value", -1, float("nan"), float("inf")],
)
def test_capture_rejects_invalid_token_metric_at_producer_path(
    tmp_path: Path,
    value: object,
) -> None:
    fixture = make_release_evidence_fixture(tmp_path)
    report = json.loads(fixture.integration_report.read_text(encoding="utf-8"))
    report["cases"][0]["total_tokens"] = value
    model_usage_check = next(
        check
        for check in report["checks"]
        if check["name"] == "case.vector_recipe_lookup.model_usage"
    )
    model_usage_check["actual"] = value
    fixture.integration_report.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, allow_nan=True) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ReleaseEvidenceCaptureError, match="sensitive|schema"):
        capture_release_evidence(capture_inputs(fixture))


def test_capture_rejects_duplicate_token_metric_hiding_secret(tmp_path: Path) -> None:
    fixture = make_release_evidence_fixture(tmp_path)
    report_text = fixture.integration_report.read_text(encoding="utf-8")
    duplicate = '"total_tokens": "Bearer duplicate-secret",\n      "total_tokens": 10'
    fixture.integration_report.write_text(
        report_text.replace('"total_tokens": 10', duplicate, 1),
        encoding="utf-8",
    )

    with pytest.raises(ReleaseEvidenceCaptureError, match="duplicate|JSON"):
        capture_release_evidence(capture_inputs(fixture))


@pytest.mark.parametrize(
    "tamper",
    [
        "same_count_different_row",
        "extra_field",
        "missing_field",
        "unknown_case_id",
        "private_customer_note",
        "non_object",
        "duplicate",
        "numeric_representation",
    ],
)
def test_capture_rejects_unbound_manual_review_jsonl(
    tmp_path: Path,
    tamper: str,
) -> None:
    fixture = make_release_evidence_fixture(tmp_path)
    report = json.loads(fixture.live_quality_report.read_text(encoding="utf-8"))
    report_rows: list[dict[str, object]] = json.loads(json.dumps(report["manual_review_sample"]))
    jsonl_row_dicts: list[dict[str, object]] = json.loads(json.dumps(report_rows))
    jsonl_rows: list[object] = jsonl_row_dicts
    if tamper == "same_count_different_row":
        jsonl_row_dicts[0]["owner"] = "different-owner"
    elif tamper == "extra_field":
        report_rows[0]["reviewer_note"] = "benign"
        jsonl_rows = json.loads(json.dumps(report_rows))
    elif tamper == "missing_field":
        report_rows[0].pop("evidence")
        jsonl_rows = json.loads(json.dumps(report_rows))
    elif tamper == "unknown_case_id":
        report_rows[0]["case_id"] = "unknown_case"
        jsonl_rows = json.loads(json.dumps(report_rows))
    elif tamper == "private_customer_note":
        report_rows[0]["private_customer_note"] = "household allergy details"
        jsonl_rows = json.loads(json.dumps(report_rows))
    elif tamper == "non_object":
        jsonl_rows = ["not-an-object"]
    elif tamper == "numeric_representation":
        judge_scores = jsonl_row_dicts[0]["judge_scores"]
        assert isinstance(judge_scores, dict)
        judge_scores["faithfulness"] = 1
    else:
        report_rows = [report_rows[0], json.loads(json.dumps(report_rows[0]))]
        report["manual_review_sample_count"] = 2
        jsonl_rows = json.loads(json.dumps(report_rows))
    report["manual_review_sample"] = report_rows
    write_json(fixture.live_quality_report, report)
    _write_manual_review_jsonl(
        fixture.live_quality_report.parent / "manual_review_sample.jsonl",
        jsonl_rows,
    )

    with pytest.raises(ReleaseEvidenceCaptureError, match="manual review|JSONL"):
        capture_release_evidence(capture_inputs(fixture))


def test_capture_rejects_manual_review_jsonl_reordered_from_policy_order(tmp_path: Path) -> None:
    fixture = make_release_evidence_fixture(tmp_path)
    policy = json.loads(fixture.live_quality_policy.read_text(encoding="utf-8"))
    second_policy_case = json.loads(json.dumps(policy["cases"][0]))
    second_policy_case["case_id"] = "grounded_mapo_tofu_2"
    policy["cases"].append(second_policy_case)
    write_json(fixture.live_quality_policy, policy)
    git(fixture.repository_root, "add", "eval/live_quality_gate.json")
    git(fixture.repository_root, "commit", "-m", "test: add manual review policy case")
    evaluated_commit = git(fixture.repository_root, "rev-parse", "HEAD")

    report = json.loads(fixture.live_quality_report.read_text(encoding="utf-8"))
    report["metrics"]["case_count"] = 2
    for group_name, label in (
        ("by_query_type", "single_recipe"),
        ("by_cuisine", "sichuan"),
        ("by_response_mode", "grounded_answer"),
        ("by_strategy", "hybrid_traditional"),
    ):
        report["metrics"][group_name][label]["case_count"] = 2
    second_case = json.loads(json.dumps(report["cases"][0]))
    second_case["case_id"] = second_policy_case["case_id"]
    report["cases"].append(second_case)
    case_checks = [check for check in report["checks"] if check["name"].startswith("case.")]
    second_case_checks = json.loads(json.dumps(case_checks))
    for check in second_case_checks:
        check["name"] = check["name"].replace(
            "case.grounded_mapo_tofu.",
            "case.grounded_mapo_tofu_2.",
        )
    gate_policy = LiveQualityGatePolicy.model_validate(policy)
    threshold_checks = evaluate_policy_thresholds(gate_policy, report["metrics"])
    report["checks"] = (
        case_checks + second_case_checks + [check.to_dict() for check in threshold_checks]
    )
    second_sample = json.loads(json.dumps(report["manual_review_sample"][0]))
    second_sample["case_id"] = second_policy_case["case_id"]
    report["manual_review_sample"].append(second_sample)
    report["manual_review_sample_count"] = 2
    write_json(fixture.live_quality_report, report)
    _write_manual_review_jsonl(
        fixture.live_quality_report.parent / "manual_review_sample.jsonl",
        list(reversed(report["manual_review_sample"])),
    )

    with pytest.raises(ReleaseEvidenceCaptureError, match="manual review|JSONL"):
        capture_release_evidence(
            replace(capture_inputs(fixture), evaluated_commit=evaluated_commit)
        )


def test_capture_rejects_invalid_manual_review_jsonl(tmp_path: Path) -> None:
    fixture = make_release_evidence_fixture(tmp_path)
    sample_path = fixture.live_quality_report.parent / "manual_review_sample.jsonl"
    sample_path.write_text("{invalid-json}\n", encoding="utf-8")

    with pytest.raises(ReleaseEvidenceCaptureError, match="manual review|JSONL"):
        capture_release_evidence(capture_inputs(fixture))


def test_capture_rejects_blank_manual_review_jsonl_record(tmp_path: Path) -> None:
    fixture = make_release_evidence_fixture(tmp_path)
    sample_path = fixture.live_quality_report.parent / "manual_review_sample.jsonl"
    sample_path.write_bytes(sample_path.read_bytes() + b"\n")

    with pytest.raises(ReleaseEvidenceCaptureError, match="manual review|JSONL"):
        capture_release_evidence(capture_inputs(fixture))


def test_capture_rejects_duplicate_manual_review_key_hiding_secret(tmp_path: Path) -> None:
    fixture = make_release_evidence_fixture(tmp_path)
    sample_path = fixture.live_quality_report.parent / "manual_review_sample.jsonl"
    sample_text = sample_path.read_text(encoding="utf-8")
    duplicate = (
        '"answer_preview": "Bearer duplicate-secret", "answer_preview": "Mapo tofu uses tofu."'
    )
    sample_path.write_text(
        sample_text.replace('"answer_preview": "Mapo tofu uses tofu."', duplicate, 1),
        encoding="utf-8",
    )

    with pytest.raises(ReleaseEvidenceCaptureError, match="duplicate|JSONL"):
        capture_release_evidence(capture_inputs(fixture))


@pytest.mark.parametrize(
    ("field_name", "route"),
    [
        ("endpoint", "/v1/debug/answers"),
        ("route", "/v2/answers"),
        ("apiEndpoint", "/v10/health/ready"),
        ("api_route", "/v3/diagnostics"),
    ],
)
def test_scan_json_allows_versioned_api_route_in_route_context(
    field_name: str,
    route: str,
) -> None:
    capture_module._scan_json({field_name: route})


@pytest.mark.parametrize(
    ("field_name", "route"),
    [
        ("note", "/v1/debug/answers"),
        ("endpoint", "/data/private.txt"),
        ("route", "/usr/local/bin/server"),
        ("apiEndpoint", "//server/share/private.txt"),
        ("api_route", "/v1/../data/private.txt"),
        ("endpoint", "/v1/debug/answers?token=value"),
        ("route", "/debug/answers"),
    ],
)
def test_scan_json_rejects_path_outside_versioned_api_route_context(
    field_name: str,
    route: str,
) -> None:
    with pytest.raises(ReleaseEvidenceCaptureError, match="sensitive release evidence"):
        capture_module._scan_json({field_name: route})


@pytest.mark.parametrize(
    "sensitive_key",
    [
        "api_key",
        "openai_api_key",
        "token",
        "accessToken",
        "clientSecret",
        "credential",
        "db_password",
        "github_token",
        "provider_authorization",
        "exception",
        "stack_trace",
    ],
)
def test_capture_rejects_sensitive_key_in_allowed_check_detail(
    tmp_path: Path,
    sensitive_key: str,
) -> None:
    fixture = make_release_evidence_fixture(tmp_path)
    report = json.loads(fixture.live_quality_report.read_text(encoding="utf-8"))
    report["checks"][0]["expected"] = {sensitive_key: "actual-token-value"}
    write_json(fixture.live_quality_report, report)

    with pytest.raises(ReleaseEvidenceCaptureError, match="sensitive release evidence"):
        capture_release_evidence(capture_inputs(fixture))


@pytest.mark.parametrize(
    "sensitive_value",
    [
        "Bearer actual-token-value",
        "Bearer x",
        "Authorization: actual-token-value",
        "https://user:password@example.com/private",
        "https://example.com/private?access_token=actual-token-value",
        "postgresql://dbuser:dbpass@db.example.com/app",
        "C:\\Users\\alice\\private.txt",
        "D:/data/private.txt",
        "\\\\server\\share\\private.txt",
        "//server/share/private.txt",
        "/home/alice/private.txt",
        "/Users/alice/private.txt",
        "/var/log/private.log",
        "/tmp/private.txt",
        "/opt/private.txt",
        "/workspace/private.txt",
        "/data/private.txt",
        "/usr/local/private.txt",
        (
            "Traceback (most recent call last):\n"
            '  File "provider.py", line 7, in request\n'
            "RuntimeError: provider failed"
        ),
        "ProviderRuntimeException: raw provider response",
        "RuntimeError('provider failed')",
        "ProviderException('provider failed')",
    ],
)
def test_capture_rejects_sensitive_value_in_allowed_evidence_snippet(
    tmp_path: Path,
    sensitive_value: str,
) -> None:
    fixture = make_release_evidence_fixture(tmp_path)
    report = json.loads(fixture.live_quality_report.read_text(encoding="utf-8"))
    report["cases"][0]["evidence"][0]["snippet"] = sensitive_value
    report["manual_review_sample"][0]["evidence"][0]["snippet"] = sensitive_value
    write_json(fixture.live_quality_report, report)
    _write_manual_review_jsonl(
        fixture.live_quality_report.parent / "manual_review_sample.jsonl",
        report["manual_review_sample"],
    )

    with pytest.raises(ReleaseEvidenceCaptureError, match="sensitive release evidence"):
        capture_release_evidence(capture_inputs(fixture))


def test_capture_rejects_dirty_checkout(tmp_path: Path) -> None:
    fixture = make_release_evidence_fixture(tmp_path)
    (fixture.repository_root / "dirty.txt").write_text("dirty", encoding="utf-8")

    with pytest.raises(ReleaseEvidenceCaptureError, match="checkout must be clean"):
        capture_release_evidence(capture_inputs(fixture))


def test_capture_rejects_checkout_head_mismatch(tmp_path: Path) -> None:
    fixture = make_release_evidence_fixture(tmp_path)
    inputs = replace(capture_inputs(fixture), evaluated_commit="0" * 40)

    with pytest.raises(ReleaseEvidenceCaptureError, match="does not match checkout HEAD"):
        capture_release_evidence(inputs)


def test_capture_rejects_noncanonical_policy_path(tmp_path: Path) -> None:
    fixture = make_release_evidence_fixture(tmp_path)
    copied_policy = write_json(
        tmp_path / "copied-integration-policy.json",
        json.loads(fixture.integration_policy.read_text(encoding="utf-8")),
    )
    inputs = replace(capture_inputs(fixture), integration_policy_path=copied_policy)

    with pytest.raises(ReleaseEvidenceCaptureError, match="canonical repository policies"):
        capture_release_evidence(inputs)


def test_capture_rejects_profile_hash_mismatch(tmp_path: Path) -> None:
    fixture = make_release_evidence_fixture(tmp_path)
    manifest = json.loads(fixture.artifact_manifest.read_text(encoding="utf-8"))
    manifest["build_metadata"]["config_profile"]["hash"] = "0" * 64
    write_json(fixture.artifact_manifest, manifest)

    with pytest.raises(ReleaseEvidenceCaptureError, match="profile hash"):
        capture_release_evidence(capture_inputs(fixture))


def test_capture_rejects_profile_path_mismatch(tmp_path: Path) -> None:
    fixture = make_release_evidence_fixture(tmp_path)
    manifest = json.loads(fixture.artifact_manifest.read_text(encoding="utf-8"))
    manifest["build_metadata"]["config_profile"]["path"] = "profiles/other.toml"
    write_json(fixture.artifact_manifest, manifest)

    with pytest.raises(ReleaseEvidenceCaptureError, match="profile path"):
        capture_release_evidence(capture_inputs(fixture))


def test_capture_rejects_unsafe_profile_name(tmp_path: Path) -> None:
    fixture = make_release_evidence_fixture(tmp_path)
    manifest = json.loads(fixture.artifact_manifest.read_text(encoding="utf-8"))
    manifest["build_metadata"]["config_profile"]["name"] = "../outside"
    write_json(fixture.artifact_manifest, manifest)

    with pytest.raises(ReleaseEvidenceCaptureError, match="profile name is invalid"):
        capture_release_evidence(capture_inputs(fixture))


def test_capture_rejects_report_artifact_escape(tmp_path: Path) -> None:
    fixture = make_release_evidence_fixture(tmp_path)
    report = json.loads(fixture.integration_report.read_text(encoding="utf-8"))
    report["artifacts"]["summary_md"] = "../summary.md"
    write_json(fixture.integration_report, report)

    with pytest.raises(ReleaseEvidenceCaptureError, match="escaped its output directory"):
        capture_release_evidence(capture_inputs(fixture))


@pytest.mark.parametrize(
    "relative_path",
    [
        "pyproject.toml",
        "eval/integration_gate.json",
        "eval/live_quality_gate.json",
        "profiles/base.toml",
        "profiles/eval_quality.toml",
    ],
)
def test_capture_rejects_assume_unchanged_commit_source_modification(
    tmp_path: Path,
    relative_path: str,
) -> None:
    fixture = make_release_evidence_fixture(tmp_path)
    git(fixture.repository_root, "update-index", "--assume-unchanged", relative_path)
    path = fixture.repository_root / relative_path
    path.write_bytes(path.read_bytes() + b"\n")
    assert git(fixture.repository_root, "status", "--porcelain") == ""

    with pytest.raises(ReleaseEvidenceCaptureError, match="does not match evaluated commit"):
        capture_release_evidence(capture_inputs(fixture))


@pytest.mark.parametrize(
    "relative_path",
    [
        "pyproject.toml",
        "eval/integration_gate.json",
        "eval/live_quality_gate.json",
        "profiles/base.toml",
        "profiles/eval_quality.toml",
    ],
)
def test_capture_rejects_non_regular_commit_source(
    tmp_path: Path,
    relative_path: str,
) -> None:
    fixture = make_release_evidence_fixture(tmp_path)
    outside = tmp_path / "outside-source"
    outside.write_text("outside", encoding="utf-8")
    evaluated_commit = _commit_tree_symlink(
        fixture.repository_root,
        relative_path,
        outside,
    )
    assert git(fixture.repository_root, "status", "--porcelain") == ""
    inputs = replace(capture_inputs(fixture), evaluated_commit=evaluated_commit)

    with pytest.raises(ReleaseEvidenceCaptureError, match="ordinary committed file"):
        capture_release_evidence(inputs)


def test_capture_uses_one_immutable_snapshot_when_source_changes_after_read(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = make_release_evidence_fixture(tmp_path)
    original_bytes = fixture.live_quality_report.read_bytes()
    mutated_report = json.loads(original_bytes)
    mutated_report["metrics"]["recall_at_k"] = 0.25
    real_read = capture_module._read_bytes
    changed = False

    def mutate_after_read(path: Path) -> bytes:
        nonlocal changed
        data = real_read(path)
        if path.resolve() == fixture.live_quality_report.resolve() and not changed:
            changed = True
            write_json(fixture.live_quality_report, mutated_report)
        return data

    monkeypatch.setattr(capture_module, "_read_bytes", mutate_after_read)
    outputs = capture_release_evidence(capture_inputs(fixture))
    receipt = load_capture_receipt(outputs.receipt_path)

    with zipfile.ZipFile(outputs.bundle_path) as archive:
        bundled_bytes = archive.read("live_quality_gate/report.json")
        bundled_report = json.loads(bundled_bytes)
        checksums = json.loads(archive.read("checksums.json"))

    assert bundled_bytes == original_bytes
    assert bundled_report["metrics"]["recall_at_k"] == receipt.quality.metrics.recall_at_k
    assert checksums["live_quality_gate/report.json"]["sha256"] == capture_module._sha256_bytes(
        original_bytes
    )


def test_capture_reads_each_source_path_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = make_release_evidence_fixture(tmp_path)
    real_read = capture_module._read_bytes
    read_counts: dict[Path, int] = {}

    def count_reads(path: Path) -> bytes:
        resolved = path.resolve()
        read_counts[resolved] = read_counts.get(resolved, 0) + 1
        return real_read(path)

    monkeypatch.setattr(capture_module, "_read_bytes", count_reads)
    capture_release_evidence(capture_inputs(fixture))

    assert read_counts
    assert set(read_counts.values()) == {1}


def test_bounded_reader_never_requests_more_than_member_limit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requested_sizes: list[int] = []

    class GuardedStream:
        def __enter__(self):
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def read(self, size: int = -1) -> bytes:
            requested_sizes.append(size)
            if size < 0 or size > capture_module.MAX_MEMBER_BYTES + 1:
                raise AssertionError("unbounded source read")
            return b"x" * size

    monkeypatch.setattr(Path, "open", lambda *_args, **_kwargs: GuardedStream())

    with pytest.raises(ReleaseEvidenceCaptureError, match="member is too large"):
        capture_module._read_bytes(tmp_path / "virtual-source")

    assert all(0 < size <= 64 * 1024 for size in requested_sizes)
    assert sum(requested_sizes) == capture_module.MAX_MEMBER_BYTES + 1


def test_capture_rejects_snapshot_budget_immediately(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = make_release_evidence_fixture(tmp_path)
    real_read = capture_module._read_bytes
    read_count = 0

    def count_reads(path: Path) -> bytes:
        nonlocal read_count
        read_count += 1
        return real_read(path)

    monkeypatch.setattr(capture_module, "_read_bytes", count_reads)
    monkeypatch.setattr(capture_module, "MAX_BUNDLE_SOURCE_BYTES", 1)

    with pytest.raises(ReleaseEvidenceCaptureError, match="source snapshot is too large"):
        capture_release_evidence(capture_inputs(fixture))

    assert read_count == 1


def test_release_evidence_fixture_uses_real_gate_report_details(tmp_path: Path) -> None:
    fixture = make_release_evidence_fixture(tmp_path)
    integration = json.loads(fixture.integration_report.read_text(encoding="utf-8"))
    live_quality = json.loads(fixture.live_quality_report.read_text(encoding="utf-8"))

    assert len(integration["checks"]) == integration["metrics"]["check_count"] == 16
    assert len(integration["cases"]) == integration["metrics"]["case_count"] == 1
    assert integration["cases"][0]["has_observation"] is True
    assert len(live_quality["checks"]) == 13
    assert len(live_quality["cases"]) == live_quality["metrics"]["case_count"] == 1
    assert live_quality["cases"][0]["metrics"] == {
        "recall_at_k": 1.0,
        "mrr": 1.0,
        "ndcg_at_k": 1.0,
    }


@pytest.mark.parametrize(
    ("report_name", "detail_name", "message"),
    [
        ("integration_report", "checks", "integration check details"),
        ("integration_report", "cases", "integration case details"),
        ("live_quality_report", "checks", "live quality check details"),
        ("live_quality_report", "cases", "live quality case details"),
    ],
)
def test_capture_rejects_empty_required_gate_details(
    tmp_path: Path,
    report_name: str,
    detail_name: str,
    message: str,
) -> None:
    fixture = make_release_evidence_fixture(tmp_path)
    report_path = getattr(fixture, report_name)
    report = json.loads(report_path.read_text(encoding="utf-8"))
    report[detail_name] = []
    write_json(report_path, report)

    with pytest.raises(ReleaseEvidenceCaptureError, match=message):
        capture_release_evidence(capture_inputs(fixture))


@pytest.mark.parametrize(
    ("report_name", "detail_name", "message"),
    [
        ("integration_report", "checks", "integration check details"),
        ("integration_report", "cases", "integration case details"),
        ("live_quality_report", "checks", "live quality check details"),
        ("live_quality_report", "cases", "live quality case details"),
    ],
)
def test_capture_rejects_missing_required_gate_details(
    tmp_path: Path,
    report_name: str,
    detail_name: str,
    message: str,
) -> None:
    fixture = make_release_evidence_fixture(tmp_path)
    report_path = getattr(fixture, report_name)
    report = json.loads(report_path.read_text(encoding="utf-8"))
    report.pop(detail_name)
    write_json(report_path, report)

    with pytest.raises(ReleaseEvidenceCaptureError, match=message):
        capture_release_evidence(capture_inputs(fixture))


@pytest.mark.parametrize(
    ("metric_name", "value"),
    [
        ("total_estimated_cost_usd", 0.02),
        ("max_latency_ms", 1001.0),
    ],
)
def test_capture_rejects_integration_detail_derived_metric_mismatch(
    tmp_path: Path,
    metric_name: str,
    value: float,
) -> None:
    fixture = make_release_evidence_fixture(tmp_path)
    report = json.loads(fixture.integration_report.read_text(encoding="utf-8"))
    report["metrics"][metric_name] = value
    write_json(fixture.integration_report, report)

    with pytest.raises(ReleaseEvidenceCaptureError, match="integration case details"):
        capture_release_evidence(capture_inputs(fixture))


@pytest.mark.parametrize("metric_name", ["recall_at_k", "mrr", "ndcg_at_k"])
def test_capture_rejects_live_retrieval_metric_detail_mismatch(
    tmp_path: Path,
    metric_name: str,
) -> None:
    fixture = make_release_evidence_fixture(tmp_path)
    report = json.loads(fixture.live_quality_report.read_text(encoding="utf-8"))
    report["cases"][0]["metrics"][metric_name] = 0.5
    write_json(fixture.live_quality_report, report)

    with pytest.raises(ReleaseEvidenceCaptureError, match="live quality case details"):
        capture_release_evidence(capture_inputs(fixture))


def test_capture_rejects_live_metric_check_actual_mismatch(tmp_path: Path) -> None:
    fixture = make_release_evidence_fixture(tmp_path)
    report = json.loads(fixture.live_quality_report.read_text(encoding="utf-8"))
    metric_check = next(
        check for check in report["checks"] if check["name"] == "metrics.fallback_rate"
    )
    metric_check["actual"] = 0.5
    write_json(fixture.live_quality_report, report)

    with pytest.raises(ReleaseEvidenceCaptureError, match="live quality check details"):
        capture_release_evidence(capture_inputs(fixture))


def test_capture_rejects_missing_live_metric_check(tmp_path: Path) -> None:
    fixture = make_release_evidence_fixture(tmp_path)
    report = json.loads(fixture.live_quality_report.read_text(encoding="utf-8"))
    report["checks"] = [check for check in report["checks"] if check["name"] != "metrics.mrr"]
    write_json(fixture.live_quality_report, report)

    with pytest.raises(ReleaseEvidenceCaptureError, match="live quality check details"):
        capture_release_evidence(capture_inputs(fixture))


@pytest.mark.parametrize(
    ("status", "failure_type"),
    [("failed", "contract-regression"), ("blocked", None)],
)
def test_capture_rejects_integration_nonpassing_check_detail(
    tmp_path: Path,
    status: str,
    failure_type: str | None,
) -> None:
    fixture = make_release_evidence_fixture(tmp_path)
    report = json.loads(fixture.integration_report.read_text(encoding="utf-8"))
    report["metrics"]["check_count"] = 1
    report["checks"] = [
        _check_detail(
            name="dependency.neo4j",
            status=status,
            code="DEPENDENCY_FAILED",
            failure_type=failure_type,
        )
    ]
    write_json(fixture.integration_report, report)

    with pytest.raises(ReleaseEvidenceCaptureError, match="integration check details"):
        capture_release_evidence(capture_inputs(fixture))


@pytest.mark.parametrize("status", ["failed", "blocked", "error"])
def test_capture_rejects_integration_nonpassing_case_detail(
    tmp_path: Path,
    status: str,
) -> None:
    fixture = make_release_evidence_fixture(tmp_path)
    report = json.loads(fixture.integration_report.read_text(encoding="utf-8"))
    report["cases"] = [_integration_case_detail(status=status)]
    write_json(fixture.integration_report, report)

    with pytest.raises(ReleaseEvidenceCaptureError, match="integration case details"):
        capture_release_evidence(capture_inputs(fixture))


def test_capture_rejects_integration_detail_aggregate_mismatch(tmp_path: Path) -> None:
    fixture = make_release_evidence_fixture(tmp_path)
    report = json.loads(fixture.integration_report.read_text(encoding="utf-8"))
    report["checks"] = [
        _check_detail(
            name="dependency.neo4j",
            status="passed",
            code="DEPENDENCY_OK",
            failure_type=None,
        )
    ]
    write_json(fixture.integration_report, report)

    with pytest.raises(ReleaseEvidenceCaptureError, match="integration check details"):
        capture_release_evidence(capture_inputs(fixture))


def test_capture_rejects_arbitrary_integration_success_check_set(tmp_path: Path) -> None:
    fixture = make_release_evidence_fixture(tmp_path)
    report = json.loads(fixture.integration_report.read_text(encoding="utf-8"))
    report["checks"] = [
        _check_detail(
            name="arbitrary.success",
            status="passed",
            code="ARBITRARY_OK",
            failure_type=None,
        )
    ]
    report["metrics"]["check_count"] = 1
    write_json(fixture.integration_report, report)

    with pytest.raises(ReleaseEvidenceCaptureError, match="integration check details"):
        capture_release_evidence(capture_inputs(fixture))


@pytest.mark.parametrize(
    "tamper",
    [
        "evidence_count",
        "model_usage",
        "latency",
        "estimated_cost",
        "probe_actual",
        "aggregate_actual",
        "expected_payload",
    ],
)
def test_capture_rejects_semantically_fabricated_integration_success(
    tmp_path: Path,
    tamper: str,
) -> None:
    fixture = make_release_evidence_fixture(tmp_path)
    report = json.loads(fixture.integration_report.read_text(encoding="utf-8"))
    checks_by_name = {check["name"]: check for check in report["checks"]}
    case = report["cases"][0]
    case_prefix = "case.vector_recipe_lookup"
    if tamper == "evidence_count":
        case["evidence_count"] = 0
        checks_by_name[f"{case_prefix}.evidence_count"]["actual"] = 0
    elif tamper == "model_usage":
        case["total_tokens"] = 0
        checks_by_name[f"{case_prefix}.model_usage"]["actual"] = 0
    elif tamper == "latency":
        case["latency_ms"] = 61_000.0
        report["metrics"]["max_latency_ms"] = 61_000.0
        checks_by_name[f"{case_prefix}.latency"]["actual"] = 61_000.0
        checks_by_name["metrics.p95_latency_ms"]["actual"] = 61_000.0
    elif tamper == "estimated_cost":
        case["estimated_cost_usd"] = 1.5
        report["metrics"]["total_estimated_cost_usd"] = 1.5
        checks_by_name["metrics.estimated_cost_usd"]["actual"] = 1.5
    elif tamper == "probe_actual":
        checks_by_name["dependency.neo4j.recipe_count"]["actual"] = 0
    elif tamper == "aggregate_actual":
        checks_by_name["metrics.global_vector_coverage"]["actual"] = False
    else:
        checks_by_name[f"{case_prefix}.evidence_count"]["expected"] = {"minimum": 999}
    write_json(fixture.integration_report, report)

    with pytest.raises(ReleaseEvidenceCaptureError, match="integration check details"):
        capture_release_evidence(capture_inputs(fixture))


@pytest.mark.parametrize("tamper", ["missing_null_field", "extra_field"])
def test_capture_rejects_nonexact_live_check_payload(
    tmp_path: Path,
    tamper: str,
) -> None:
    fixture = make_release_evidence_fixture(tmp_path)
    report = json.loads(fixture.live_quality_report.read_text(encoding="utf-8"))
    deterministic_check = next(
        check
        for check in report["checks"]
        if check["name"] == "case.grounded_mapo_tofu.deterministic"
    )
    if tamper == "missing_null_field":
        deterministic_check.pop("expected")
    else:
        deterministic_check["unexpected"] = None
    write_json(fixture.live_quality_report, report)

    with pytest.raises(ReleaseEvidenceCaptureError, match="live quality check details"):
        capture_release_evidence(capture_inputs(fixture))


@pytest.mark.parametrize(
    ("status", "failure_type", "code"),
    [
        ("failed", "judge-unavailable", "JUDGE_RESPONSE_INVALID"),
        ("blocked", None, "PREREQUISITE_FAILED"),
    ],
)
def test_capture_rejects_live_quality_blocking_check_detail(
    tmp_path: Path,
    status: str,
    failure_type: str | None,
    code: str,
) -> None:
    fixture = make_release_evidence_fixture(tmp_path)
    report = json.loads(fixture.live_quality_report.read_text(encoding="utf-8"))
    report["checks"] = [
        _check_detail(
            name="case.grounded_mapo_tofu.judge",
            status=status,
            code=code,
            failure_type=failure_type,
        )
    ]
    report["failure_type_counts"] = {failure_type: 1} if failure_type is not None else {}
    write_json(fixture.live_quality_report, report)

    with pytest.raises(ReleaseEvidenceCaptureError, match="live quality check details"):
        capture_release_evidence(capture_inputs(fixture))


def test_capture_rejects_live_quality_case_aggregate_mismatch(tmp_path: Path) -> None:
    fixture = make_release_evidence_fixture(tmp_path)
    report = json.loads(fixture.live_quality_report.read_text(encoding="utf-8"))
    case = _live_case_detail("grounded_mapo_tofu")
    case["deterministic_passed"] = False
    case["failures"] = ["response_mode_mismatch"]
    report["cases"] = [case]
    write_json(fixture.live_quality_report, report)

    with pytest.raises(ReleaseEvidenceCaptureError, match="live quality case details"):
        capture_release_evidence(capture_inputs(fixture))


@pytest.mark.parametrize(
    "check_suffix",
    ["deterministic", "judge"],
)
def test_capture_rejects_missing_live_case_check(
    tmp_path: Path,
    check_suffix: str,
) -> None:
    fixture = make_release_evidence_fixture(tmp_path)
    report = json.loads(fixture.live_quality_report.read_text(encoding="utf-8"))
    missing_name = f"case.grounded_mapo_tofu.{check_suffix}"
    report["checks"] = [check for check in report["checks"] if check["name"] != missing_name]
    write_json(fixture.live_quality_report, report)

    with pytest.raises(ReleaseEvidenceCaptureError, match="live quality check details"):
        capture_release_evidence(capture_inputs(fixture))


def test_capture_rejects_fabricated_passing_live_threshold_check(tmp_path: Path) -> None:
    fixture = make_release_evidence_fixture(tmp_path)
    report = json.loads(fixture.live_quality_report.read_text(encoding="utf-8"))
    report["metrics"]["fallback_rate"] = 0.5
    fallback_check = next(
        check for check in report["checks"] if check["name"] == "metrics.fallback_rate"
    )
    fallback_check["actual"] = 0.5
    write_json(fixture.live_quality_report, report)

    with pytest.raises(ReleaseEvidenceCaptureError, match="live quality check details"):
        capture_release_evidence(capture_inputs(fixture))


@pytest.mark.parametrize(
    ("policy_section", "configured_value"),
    [
        ("required_slice_coverage", {"single_recipe": 1}),
        (
            "slice_thresholds",
            {"single_recipe": {"minimum_case_count": 1, "minimum_pass_rate": 0.8}},
        ),
    ],
)
def test_capture_rejects_missing_policy_configured_live_checks(
    tmp_path: Path,
    policy_section: str,
    configured_value: dict[str, object],
) -> None:
    fixture = make_release_evidence_fixture(tmp_path)
    policy = json.loads(fixture.live_quality_policy.read_text(encoding="utf-8"))
    policy[policy_section]["query_types"] = configured_value
    write_json(fixture.live_quality_policy, policy)
    git(fixture.repository_root, "add", "eval/live_quality_gate.json")
    git(fixture.repository_root, "commit", "-m", "test: configure live quality slice")
    evaluated_commit = git(fixture.repository_root, "rev-parse", "HEAD")

    with pytest.raises(ReleaseEvidenceCaptureError, match="live quality check details"):
        capture_release_evidence(
            replace(capture_inputs(fixture), evaluated_commit=evaluated_commit)
        )


def test_capture_accepts_complete_policy_configured_live_checks(tmp_path: Path) -> None:
    fixture = make_release_evidence_fixture(tmp_path)
    policy = json.loads(fixture.live_quality_policy.read_text(encoding="utf-8"))
    policy["required_slice_coverage"]["query_types"] = {"single_recipe": 1}
    policy["slice_thresholds"]["query_types"] = {
        "single_recipe": {"minimum_case_count": 1, "minimum_pass_rate": 0.8}
    }
    write_json(fixture.live_quality_policy, policy)
    git(fixture.repository_root, "add", "eval/live_quality_gate.json")
    git(fixture.repository_root, "commit", "-m", "test: configure complete live quality slice")
    evaluated_commit = git(fixture.repository_root, "rev-parse", "HEAD")

    report = json.loads(fixture.live_quality_report.read_text(encoding="utf-8"))
    gate_policy = LiveQualityGatePolicy.model_validate(policy)
    case_checks = [check for check in report["checks"] if check["name"].startswith("case.")]
    threshold_checks = evaluate_policy_thresholds(gate_policy, report["metrics"])
    report["checks"] = case_checks + [check.to_dict() for check in threshold_checks]
    write_json(fixture.live_quality_report, report)

    capture_release_evidence(replace(capture_inputs(fixture), evaluated_commit=evaluated_commit))


@pytest.mark.parametrize("metric_name", ["recall_at_k", "mrr", "ndcg_at_k"])
def test_capture_rejects_missing_grounded_case_retrieval_metric(
    tmp_path: Path,
    metric_name: str,
) -> None:
    fixture = make_release_evidence_fixture(tmp_path)
    policy = json.loads(fixture.live_quality_policy.read_text(encoding="utf-8"))
    second_policy_case = json.loads(json.dumps(policy["cases"][0]))
    second_policy_case["case_id"] = "grounded_mapo_tofu_2"
    policy["cases"].append(second_policy_case)
    write_json(fixture.live_quality_policy, policy)
    git(fixture.repository_root, "add", "eval/live_quality_gate.json")
    git(fixture.repository_root, "commit", "-m", "test: add grounded quality case")
    evaluated_commit = git(fixture.repository_root, "rev-parse", "HEAD")

    report = json.loads(fixture.live_quality_report.read_text(encoding="utf-8"))
    report["metrics"]["case_count"] = 2
    report["metrics"]["by_query_type"]["single_recipe"]["case_count"] = 2
    report["metrics"]["by_cuisine"]["sichuan"]["case_count"] = 2
    report["metrics"]["by_response_mode"]["grounded_answer"]["case_count"] = 2
    report["metrics"]["by_strategy"]["hybrid_traditional"]["case_count"] = 2
    case_count_check = next(
        check for check in report["checks"] if check["name"] == "metrics.case_count"
    )
    case_count_check["actual"] = 2
    second_case = _live_case_detail("grounded_mapo_tofu_2")
    second_case["metrics"][metric_name] = None
    report["cases"].append(second_case)
    report["checks"].extend(
        [
            _check_detail(
                name="case.grounded_mapo_tofu_2.deterministic",
                status="passed",
                code="DETERMINISTIC_QUALITY_OK",
                failure_type=None,
            ),
            _check_detail(
                name="case.grounded_mapo_tofu_2.judge",
                status="passed",
                code="JUDGE_QUALITY_OK",
                failure_type=None,
                expected={"minimum_score": 0.8},
                actual=second_case["judge_scores"],
            ),
        ]
    )
    write_json(fixture.live_quality_report, report)

    with pytest.raises(ReleaseEvidenceCaptureError, match="live quality case details"):
        capture_release_evidence(
            replace(capture_inputs(fixture), evaluated_commit=evaluated_commit)
        )


def test_capture_allows_nonblocking_live_case_quality_failure(tmp_path: Path) -> None:
    fixture = make_release_evidence_fixture(tmp_path)
    policy = json.loads(fixture.live_quality_policy.read_text(encoding="utf-8"))
    template = policy["cases"][0]
    policy_cases: list[dict[str, object]] = []
    case_ids: list[str] = []
    for index in range(20):
        case_id = f"grounded_mapo_tofu_{index:02d}"
        case_ids.append(case_id)
        cloned = json.loads(json.dumps(template))
        cloned["case_id"] = case_id
        cloned["manual_review"]["sample"] = index == 0
        policy_cases.append(cloned)
    policy["cases"] = policy_cases
    write_json(fixture.live_quality_policy, policy)
    git(fixture.repository_root, "add", "eval/live_quality_gate.json")
    git(fixture.repository_root, "commit", "-m", "test: expand live quality policy")
    evaluated_commit = git(fixture.repository_root, "rev-parse", "HEAD")

    report = json.loads(fixture.live_quality_report.read_text(encoding="utf-8"))
    report["metrics"].update(
        {
            "case_count": 20,
            "pass_rate": 0.95,
            "deterministic_pass_rate": 1.0,
            "judge_pass_rate": 0.95,
        }
    )
    report["cases"] = [
        _live_case_detail(
            case_id,
            judge_passed=index != 0,
            manual_review_sample=index == 0,
        )
        for index, case_id in enumerate(case_ids)
    ]
    for group_name, label in (
        ("by_query_type", "single_recipe"),
        ("by_cuisine", "sichuan"),
        ("by_response_mode", "grounded_answer"),
        ("by_strategy", "hybrid_traditional"),
    ):
        report["metrics"][group_name][label].update({"case_count": 20, "pass_rate": 0.95})
    gate_policy = LiveQualityGatePolicy.model_validate(policy)
    complete_checks: list[GateCheckResult] = []
    for case in report["cases"]:
        case_id = case["case_id"]
        complete_checks.append(
            GateCheckResult.pass_check(
                f"case.{case_id}.deterministic",
                code="DETERMINISTIC_QUALITY_OK",
            )
        )
        judge_kwargs = {
            "expected": {"minimum_score": gate_policy.judge.minimum_score},
            "actual": case["judge_scores"],
        }
        if case["judge_passed"]:
            complete_checks.append(
                GateCheckResult.pass_check(
                    f"case.{case_id}.judge",
                    code="JUDGE_QUALITY_OK",
                    **judge_kwargs,
                )
            )
        else:
            complete_checks.append(
                GateCheckResult.fail_check(
                    f"case.{case_id}.judge",
                    failure_type=GateFailureType.QUALITY_REGRESSION,
                    code="JUDGE_QUALITY_FAILED",
                    **judge_kwargs,
                )
            )
    complete_checks.extend(evaluate_policy_thresholds(gate_policy, report["metrics"]))
    report["checks"] = [check.to_dict() for check in complete_checks]
    report["failure_type_counts"] = {"quality-regression": 1}
    first_case = report["cases"][0]
    manual_sample = report["manual_review_sample"][0]
    for field_name in (
        "case_id",
        "passed",
        "deterministic_passed",
        "judge_passed",
        "judge_scores",
        "failures",
        "answer_preview",
        "evidence",
    ):
        manual_sample[field_name] = first_case[field_name]
    write_json(fixture.live_quality_report, report)
    _write_manual_review_jsonl(
        fixture.live_quality_report.parent / "manual_review_sample.jsonl",
        report["manual_review_sample"],
    )

    capture_release_evidence(replace(capture_inputs(fixture), evaluated_commit=evaluated_commit))


@pytest.mark.parametrize(
    ("integration_host", "live_host"),
    [
        ("QUALITY.EXAMPLE.COM", "quality.example.com:443"),
        ("127.0.0.1", "127.0.0.1:8000"),
        ("::1", "[::1]:8000"),
        ("2001:db8::1", "[2001:db8::1]:443"),
    ],
)
def test_capture_accepts_same_gate_target_hostname(
    tmp_path: Path,
    integration_host: str,
    live_host: str,
) -> None:
    fixture = make_release_evidence_fixture(tmp_path)
    integration_report = json.loads(fixture.integration_report.read_text(encoding="utf-8"))
    integration_report["target"]["api_host"] = integration_host
    write_json(fixture.integration_report, integration_report)
    live_report = json.loads(fixture.live_quality_report.read_text(encoding="utf-8"))
    live_report["target"]["api_host"] = live_host
    write_json(fixture.live_quality_report, live_report)

    capture_release_evidence(capture_inputs(fixture))


def test_capture_rejects_gate_target_hostname_mismatch(tmp_path: Path) -> None:
    fixture = make_release_evidence_fixture(tmp_path)
    integration_report = json.loads(fixture.integration_report.read_text(encoding="utf-8"))
    integration_report["target"]["api_host"] = "other.example.com"
    write_json(fixture.integration_report, integration_report)

    with pytest.raises(ReleaseEvidenceCaptureError, match="gate target hostnames differ"):
        capture_release_evidence(capture_inputs(fixture))


@pytest.mark.parametrize(
    ("integration_host", "live_host"),
    [
        ("::1", "::1:8000"),
        ("2001:db8::1", "[2001:db8::2]:8000"),
    ],
)
def test_capture_rejects_different_ipv6_gate_target_hostname(
    tmp_path: Path,
    integration_host: str,
    live_host: str,
) -> None:
    fixture = make_release_evidence_fixture(tmp_path)
    integration_report = json.loads(fixture.integration_report.read_text(encoding="utf-8"))
    integration_report["target"]["api_host"] = integration_host
    write_json(fixture.integration_report, integration_report)
    live_report = json.loads(fixture.live_quality_report.read_text(encoding="utf-8"))
    live_report["target"]["api_host"] = live_host
    write_json(fixture.live_quality_report, live_report)

    with pytest.raises(ReleaseEvidenceCaptureError, match="gate target hostnames differ"):
        capture_release_evidence(capture_inputs(fixture))
