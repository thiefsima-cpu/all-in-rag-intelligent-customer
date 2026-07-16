from __future__ import annotations

import json
import zipfile
from dataclasses import replace
from pathlib import Path

import pytest

from scripts.release_evidence.capture import (
    CaptureInputs,
    ReleaseEvidenceCaptureError,
    capture_release_evidence,
)
from scripts.release_evidence.models import load_capture_receipt
from tests.release_evidence_fixtures import make_release_evidence_fixture, write_json


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
    report["cases"] = [
        {
            "note": "The customer asks whether this is a secret recipe.",
            "reference": "https://docs.example.com/search?q=secret+recipe",
        }
    ]
    write_json(fixture.live_quality_report, report)

    capture_release_evidence(capture_inputs(fixture))


@pytest.mark.parametrize(
    "sensitive_value",
    [
        {"api_key": "actual-token-value"},
        {"note": "Bearer actual-token-value"},
        {"note": "Authorization: actual-token-value"},
        {"note": "https://user:password@example.com/private"},
        {"note": "https://example.com/private?access_token=actual-token-value"},
        {"note": "C:\\Users\\alice\\private.txt"},
        {"note": "\\\\server\\share\\private.txt"},
        {"note": "/home/alice/private.txt"},
        {"note": "/Users/alice/private.txt"},
        {"note": "/var/log/private.log"},
        {"note": "/tmp/private.txt"},
        {"note": "/opt/private.txt"},
        {"note": "/workspace/private.txt"},
    ],
)
def test_capture_rejects_sensitive_values(
    tmp_path: Path,
    sensitive_value: dict[str, str],
) -> None:
    fixture = make_release_evidence_fixture(tmp_path)
    report = json.loads(fixture.live_quality_report.read_text(encoding="utf-8"))
    report["cases"] = [sensitive_value]
    write_json(fixture.live_quality_report, report)

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
