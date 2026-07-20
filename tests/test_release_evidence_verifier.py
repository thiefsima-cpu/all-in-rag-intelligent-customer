from __future__ import annotations

import hashlib
import json
import shutil
import zipfile
from pathlib import Path

import pytest

from scripts.integration_gate.models import IntegrationGatePolicy
from scripts.release_evidence import verifier as verifier_module
from scripts.release_evidence.capture import (
    CaptureInputs,
    ReleaseEvidenceCaptureError,
    capture_release_evidence,
    validate_v2_integration_evidence,
)
from scripts.release_evidence.finalize import finalize_release_evidence
from scripts.release_evidence.models import IntegrationMetrics, TransportIdentity
from scripts.release_evidence.verifier import (
    ReleaseEvidenceVerificationError,
    VerifyInputs,
    release_manifest_path,
    verify_release_evidence,
)
from tests.release_evidence_fixtures import git, make_release_evidence_fixture, write_json

_ARTIFACT_NAMES = {
    "checksums.json": "checksums",
    "integration_gate/report.json": "integration_report",
    "integration_gate/summary.md": "integration_summary",
    "live_quality_gate/manual_review_sample.jsonl": "manual_review_sample",
    "live_quality_gate/report.json": "live_quality_report",
    "live_quality_gate/summary.md": "live_quality_summary",
    "policies/integration_gate.json": "integration_policy",
    "policies/live_quality_gate.json": "live_quality_policy",
    "runtime/artifact_manifest.json": "knowledge_artifact",
    "runtime/diagnostics.json": "runtime_diagnostics",
}


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _json_bytes(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode("utf-8")


def _manifest_payload(manifest_path: Path) -> dict[str, object]:
    return json.loads(manifest_path.read_text(encoding="utf-8"))


def _commit_manifest(
    repository_root: Path,
    manifest_path: Path,
    payload: dict[str, object],
    message: str,
) -> str:
    write_json(manifest_path, payload)
    relative_path = manifest_path.relative_to(repository_root).as_posix()
    git(repository_root, "add", relative_path)
    git(repository_root, "commit", "-m", message)
    return git(repository_root, "rev-parse", "HEAD")


def _bundle_entries(bundle_path: Path) -> dict[str, bytes]:
    with zipfile.ZipFile(bundle_path) as archive:
        return {name: archive.read(name) for name in archive.namelist()}


def _write_bundle(bundle_path: Path, entries: dict[str, bytes]) -> None:
    bundle_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(
        bundle_path,
        "w",
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=9,
    ) as archive:
        for name, data in sorted(entries.items()):
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 3
            info.external_attr = (0o100644 & 0xFFFF) << 16
            archive.writestr(info, data)


def _synchronize_bundle(
    *,
    fixture,
    capture,
    manifest_path: Path,
    entries: dict[str, bytes],
    manifest: dict[str, object] | None = None,
    bundle_path: Path | None = None,
    extra_artifact_names: dict[str, str] | None = None,
    refresh_checksums: bool = True,
) -> tuple[str, Path]:
    if refresh_checksums:
        entries["checksums.json"] = _json_bytes(
            {
                name: {"bytes": len(data), "sha256": _sha256(data)}
                for name, data in sorted(entries.items())
                if name != "checksums.json"
            }
        )
    output_path = bundle_path or capture.bundle_path
    _write_bundle(output_path, entries)

    payload = manifest or _manifest_payload(manifest_path)
    names = dict(_ARTIFACT_NAMES)
    names.update(extra_artifact_names or {})
    payload["artifacts"] = [
        {
            "name": names[name],
            "path": name,
            "bytes": len(data),
            "sha256": _sha256(data),
        }
        for name, data in sorted(entries.items())
    ]
    payload["bundle"] = {
        "name": output_path.name,
        "bytes": output_path.stat().st_size,
        "sha256": _sha256(output_path.read_bytes()),
    }
    release_commit = _commit_manifest(
        fixture.repository_root,
        manifest_path,
        payload,
        "test: update release evidence",
    )
    return release_commit, output_path


def _synchronize_report_timestamps(
    *,
    fixture,
    capture,
    manifest_path: Path,
    integration_generated_at: str,
    live_generated_at: str,
    capture_generated_at: str = "2026-07-16T08:00:00+00:00",
) -> tuple[str, Path]:
    entries = _bundle_entries(capture.bundle_path)
    integration_report = json.loads(entries["integration_gate/report.json"])
    integration_report["generated_at"] = integration_generated_at
    entries["integration_gate/report.json"] = _json_bytes(integration_report)
    entries["integration_gate/summary.md"] = verifier_module.render_integration_summary(
        json.loads(entries["integration_gate/report.json"])
    )
    live_report = json.loads(entries["live_quality_gate/report.json"])
    live_report["generated_at"] = live_generated_at
    entries["live_quality_gate/report.json"] = _json_bytes(live_report)
    entries["live_quality_gate/summary.md"] = verifier_module.render_live_quality_summary(
        json.loads(entries["live_quality_gate/report.json"])
    )
    manifest = _manifest_payload(manifest_path)
    manifest["provenance"]["generated_at"] = capture_generated_at
    manifest["integration"]["generated_at"] = integration_generated_at
    manifest["quality"]["generated_at"] = live_generated_at
    return _synchronize_bundle(
        fixture=fixture,
        capture=capture,
        manifest_path=manifest_path,
        entries=entries,
        manifest=manifest,
    )


def finalized_release(tmp_path: Path):
    fixture = make_release_evidence_fixture(tmp_path)
    capture = capture_release_evidence(
        CaptureInputs(
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
        ),
        generated_at="2026-07-16T08:00:00+00:00",
    )
    transport = TransportIdentity(
        provider="github-actions",
        workflow_run_id=123,
        workflow_head_sha=fixture.evaluated_commit,
        artifact_id=456,
        artifact_name="graph-rag-c9-0.4.0rc1-quality-evidence",
        artifact_digest="sha256:" + "a" * 64,
    )
    manifest_path = release_manifest_path(fixture.repository_root, "0.4.0rc1")
    finalize_release_evidence(capture.receipt_path, transport, manifest_path)
    git(
        fixture.repository_root,
        "add",
        manifest_path.relative_to(fixture.repository_root).as_posix(),
    )
    git(fixture.repository_root, "commit", "-m", "release: add quality evidence")
    release_commit = git(fixture.repository_root, "rev-parse", "HEAD")
    metadata_path = write_json(
        tmp_path / "artifact-metadata.json",
        {
            "id": 456,
            "name": "graph-rag-c9-0.4.0rc1-quality-evidence",
            "size_in_bytes": capture.bundle_path.stat().st_size + 4096,
            "expired": False,
            "digest": "sha256:" + "a" * 64,
            "workflow_run": {
                "id": 123,
                "head_sha": fixture.evaluated_commit,
            },
        },
    )
    return fixture, capture, manifest_path, release_commit, metadata_path


def _verify(
    fixture,
    capture,
    manifest_path: Path,
    release_commit: str,
    metadata_path: Path,
):
    return verify_release_evidence(
        VerifyInputs(
            repository_root=fixture.repository_root,
            manifest_path=manifest_path,
            release_commit=release_commit,
            tag="v0.4.0-rc.1",
            bundle_path=capture.bundle_path,
            artifact_metadata_path=metadata_path,
        )
    )


def test_verify_accepts_evidence_only_release_commit(tmp_path: Path) -> None:
    fixture, capture, manifest_path, release_commit, metadata_path = finalized_release(tmp_path)

    manifest = _verify(fixture, capture, manifest_path, release_commit, metadata_path)

    assert manifest.provenance.evaluated_commit == fixture.evaluated_commit


def test_verify_rejects_self_consistent_v1_live_quality_report(tmp_path: Path) -> None:
    fixture, capture, manifest_path, _, metadata_path = finalized_release(tmp_path)
    entries = _bundle_entries(capture.bundle_path)
    report = json.loads(entries["live_quality_gate/report.json"])
    report["schema_version"] = 1
    entries["live_quality_gate/report.json"] = _json_bytes(report)
    entries["live_quality_gate/summary.md"] = verifier_module.render_live_quality_summary(report)
    manifest = _manifest_payload(manifest_path)
    manifest["quality"]["report_schema_version"] = 1
    release_commit, _ = _synchronize_bundle(
        fixture=fixture,
        capture=capture,
        manifest_path=manifest_path,
        entries=entries,
        manifest=manifest,
    )

    with pytest.raises(ReleaseEvidenceVerificationError, match="live quality report schema"):
        _verify(fixture, capture, manifest_path, release_commit, metadata_path)


@pytest.mark.parametrize(
    "tamper",
    [
        "case_schema",
        "recomputed_timing",
        "threshold_check",
        "sensitive_value",
    ],
)
def test_verify_rejects_rehashed_v2_content_that_capture_would_reject(
    tmp_path: Path,
    tamper: str,
) -> None:
    fixture, capture, manifest_path, _, metadata_path = finalized_release(tmp_path)
    entries = _bundle_entries(capture.bundle_path)
    report = json.loads(entries["live_quality_gate/report.json"])
    if tamper == "case_schema":
        report["cases"][0]["unexpected_field"] = "invalid"
    elif tamper == "recomputed_timing":
        report["cases"][0]["timings"]["ttft_ms"] = 1001.0
    elif tamper == "threshold_check":
        next(check for check in report["checks"] if check["name"] == "metrics.p95_ttft_ms")[
            "expected"
        ] = {"minimum": None, "maximum": 1999.0}
    else:
        report["cases"][0]["answer_preview"] = "Bearer verifier-sensitive-token"
    report_bytes = _json_bytes(report)
    entries["live_quality_gate/report.json"] = report_bytes
    entries["live_quality_gate/summary.md"] = verifier_module.render_live_quality_summary(
        json.loads(report_bytes)
    )
    release_commit, _ = _synchronize_bundle(
        fixture=fixture,
        capture=capture,
        manifest_path=manifest_path,
        entries=entries,
    )

    with pytest.raises(ReleaseEvidenceVerificationError, match="v2 evidence"):
        _verify(fixture, capture, manifest_path, release_commit, metadata_path)


def test_verify_rejects_rehashed_v2_integration_evidence_count_that_capture_rejects(
    tmp_path: Path,
) -> None:
    fixture, capture, manifest_path, _, metadata_path = finalized_release(tmp_path)
    entries = _bundle_entries(capture.bundle_path)
    report = json.loads(entries["integration_gate/report.json"])
    report["cases"][0]["evidence_count"] += 1
    policy = IntegrationGatePolicy.model_validate(
        json.loads(entries["policies/integration_gate.json"])
    )
    metrics = IntegrationMetrics.model_validate(
        _manifest_payload(manifest_path)["integration"]["metrics"]
    )

    with pytest.raises(ReleaseEvidenceCaptureError, match="integration check details"):
        validate_v2_integration_evidence(report, policy, metrics)

    report_bytes = _json_bytes(report)
    entries["integration_gate/report.json"] = report_bytes
    entries["integration_gate/summary.md"] = verifier_module.render_integration_summary(
        json.loads(report_bytes)
    )
    release_commit, _ = _synchronize_bundle(
        fixture=fixture,
        capture=capture,
        manifest_path=manifest_path,
        entries=entries,
    )

    with pytest.raises(ReleaseEvidenceVerificationError, match="v2 evidence"):
        _verify(fixture, capture, manifest_path, release_commit, metadata_path)


def test_verify_rejects_v1_evidence_manifest(tmp_path: Path) -> None:
    fixture, capture, manifest_path, _, metadata_path = finalized_release(tmp_path)
    manifest = _manifest_payload(manifest_path)
    manifest["schema_version"] = "graph-rag-release-evidence-v1"
    release_commit = _commit_manifest(
        fixture.repository_root,
        manifest_path,
        manifest,
        "test: downgrade evidence manifest schema",
    )

    with pytest.raises(ReleaseEvidenceVerificationError, match="input is invalid"):
        _verify(fixture, capture, manifest_path, release_commit, metadata_path)


@pytest.mark.parametrize(
    ("integration_generated_at", "live_generated_at", "message"),
    [
        (
            "2026-07-16T04:59:59+00:00",
            "2026-07-16T07:55:00+00:00",
            "more than 180 minutes old",
        ),
        (
            "2026-07-16T07:50:00+00:00",
            "2026-07-16T08:05:01+00:00",
            "more than 5 minutes in the future",
        ),
        (
            "2026-07-16T07:56:00+00:00",
            "2026-07-16T07:55:00+00:00",
            "execution order",
        ),
    ],
)
def test_verify_rejects_self_consistent_invalid_report_timestamps(
    tmp_path: Path,
    integration_generated_at: str,
    live_generated_at: str,
    message: str,
) -> None:
    fixture, capture, manifest_path, _, metadata_path = finalized_release(tmp_path)
    release_commit, _ = _synchronize_report_timestamps(
        fixture=fixture,
        capture=capture,
        manifest_path=manifest_path,
        integration_generated_at=integration_generated_at,
        live_generated_at=live_generated_at,
    )

    with pytest.raises(ReleaseEvidenceVerificationError, match=message):
        _verify(fixture, capture, manifest_path, release_commit, metadata_path)


def test_verify_rejects_naive_report_timestamp_after_rehash(tmp_path: Path) -> None:
    fixture, capture, manifest_path, _, metadata_path = finalized_release(tmp_path)
    entries = _bundle_entries(capture.bundle_path)
    report = json.loads(entries["integration_gate/report.json"])
    report["generated_at"] = "2026-07-16T07:50:00"
    entries["integration_gate/report.json"] = _json_bytes(report)
    entries["integration_gate/summary.md"] = verifier_module.render_integration_summary(
        json.loads(entries["integration_gate/report.json"])
    )
    release_commit, _ = _synchronize_bundle(
        fixture=fixture,
        capture=capture,
        manifest_path=manifest_path,
        entries=entries,
    )

    with pytest.raises(ReleaseEvidenceVerificationError, match="timezone-aware"):
        _verify(fixture, capture, manifest_path, release_commit, metadata_path)


def test_verify_accepts_inclusive_report_freshness_boundaries(tmp_path: Path) -> None:
    fixture, capture, manifest_path, _, metadata_path = finalized_release(tmp_path)
    release_commit, _ = _synchronize_report_timestamps(
        fixture=fixture,
        capture=capture,
        manifest_path=manifest_path,
        integration_generated_at="2026-07-16T05:00:00+00:00",
        live_generated_at="2026-07-16T08:05:00+00:00",
    )

    manifest = _verify(fixture, capture, manifest_path, release_commit, metadata_path)

    assert manifest.integration.generated_at == "2026-07-16T05:00:00+00:00"
    assert manifest.quality.generated_at == "2026-07-16T08:05:00+00:00"


def test_verify_rejects_source_change_after_evaluation(tmp_path: Path) -> None:
    fixture, capture, manifest_path, _, metadata_path = finalized_release(tmp_path)
    (fixture.repository_root / "profiles" / "eval_quality.toml").write_text(
        "[retrieval]\ntop_k = 7\n",
        encoding="utf-8",
    )
    git(fixture.repository_root, "add", "profiles/eval_quality.toml")
    git(fixture.repository_root, "commit", "-m", "change: modify evaluated profile")
    release_commit = git(fixture.repository_root, "rev-parse", "HEAD")

    with pytest.raises(ReleaseEvidenceVerificationError, match="unexpected files"):
        _verify(fixture, capture, manifest_path, release_commit, metadata_path)


def test_verify_rejects_manifest_modified_instead_of_added(tmp_path: Path) -> None:
    fixture, capture, manifest_path, _, metadata_path = finalized_release(tmp_path)
    manifest = _manifest_payload(manifest_path)
    git(fixture.repository_root, "checkout", "--detach", fixture.evaluated_commit)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text("superseded evidence\n", encoding="utf-8")
    relative_path = manifest_path.relative_to(fixture.repository_root).as_posix()
    git(fixture.repository_root, "add", relative_path)
    git(fixture.repository_root, "commit", "-m", "test: add superseded evidence")
    evaluated_commit = git(fixture.repository_root, "rev-parse", "HEAD")

    manifest["provenance"]["evaluated_commit"] = evaluated_commit
    manifest["transport"]["workflow_head_sha"] = evaluated_commit
    release_commit = _commit_manifest(
        fixture.repository_root,
        manifest_path,
        manifest,
        "release: replace quality evidence",
    )
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata["workflow_run"]["head_sha"] = evaluated_commit
    write_json(metadata_path, metadata)

    with pytest.raises(ReleaseEvidenceVerificationError, match="unexpected files"):
        _verify(fixture, capture, manifest_path, release_commit, metadata_path)


def test_verify_rejects_expired_artifact(tmp_path: Path) -> None:
    fixture, capture, manifest_path, release_commit, metadata_path = finalized_release(tmp_path)
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata["expired"] = True
    write_json(metadata_path, metadata)

    with pytest.raises(ReleaseEvidenceVerificationError, match="expired"):
        _verify(fixture, capture, manifest_path, release_commit, metadata_path)


def test_verify_rejects_extra_or_modified_bundle_member(tmp_path: Path) -> None:
    fixture, capture, manifest_path, release_commit, metadata_path = finalized_release(tmp_path)
    tampered = tmp_path / "tampered.zip"
    shutil.copy2(capture.bundle_path, tampered)
    with zipfile.ZipFile(tampered, "a") as archive:
        archive.writestr("../escape.txt", "tampered")

    with pytest.raises(ReleaseEvidenceVerificationError, match="bundle"):
        verify_release_evidence(
            VerifyInputs(
                repository_root=fixture.repository_root,
                manifest_path=manifest_path,
                release_commit=release_commit,
                tag="v0.4.0-rc.1",
                bundle_path=tampered,
                artifact_metadata_path=metadata_path,
            )
        )


def test_verify_excludes_generated_checksums_from_source_size_budget(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture, capture, manifest_path, release_commit, metadata_path = finalized_release(tmp_path)
    entries = _bundle_entries(capture.bundle_path)
    source_bytes = sum(len(data) for name, data in entries.items() if name != "checksums.json")
    assert sum(map(len, entries.values())) > source_bytes
    monkeypatch.setattr(verifier_module, "MAX_BUNDLE_SOURCE_BYTES", source_bytes)

    manifest = _verify(fixture, capture, manifest_path, release_commit, metadata_path)

    assert manifest.bundle.bytes == capture.bundle_path.stat().st_size


def test_verify_rejects_source_entries_over_size_budget(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture, capture, manifest_path, release_commit, metadata_path = finalized_release(tmp_path)
    entries = _bundle_entries(capture.bundle_path)
    source_bytes = sum(len(data) for name, data in entries.items() if name != "checksums.json")
    monkeypatch.setattr(verifier_module, "MAX_BUNDLE_SOURCE_BYTES", source_bytes - 1)

    with pytest.raises(ReleaseEvidenceVerificationError, match="bundle contents are too large"):
        _verify(fixture, capture, manifest_path, release_commit, metadata_path)


def test_verify_rejects_artifact_digest_mismatch(tmp_path: Path) -> None:
    fixture, capture, manifest_path, release_commit, metadata_path = finalized_release(tmp_path)
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata["digest"] = "sha256:" + "b" * 64
    write_json(metadata_path, metadata)

    with pytest.raises(ReleaseEvidenceVerificationError, match="artifact digest"):
        _verify(fixture, capture, manifest_path, release_commit, metadata_path)


def test_release_manifest_path_ignores_historical_failed_reports(tmp_path: Path) -> None:
    root = tmp_path / "repository"
    historical = root / "quality-evidence/live_quality_gate/20260708-203513/report.json"
    historical.parent.mkdir(parents=True)
    historical.write_text('{"passed":false,"metrics":{"case_count":0}}\n', encoding="utf-8")

    assert release_manifest_path(root, "0.4.0rc1") == (
        root / "quality-evidence/releases/0.4.0rc1/evidence-manifest.json"
    )


@pytest.mark.parametrize("gate", ["integration", "quality"])
def test_verify_rejects_manifest_gate_passed_false(tmp_path: Path, gate: str) -> None:
    fixture, capture, manifest_path, _, metadata_path = finalized_release(tmp_path)
    manifest = _manifest_payload(manifest_path)
    manifest[gate]["passed"] = False
    release_commit = _commit_manifest(
        fixture.repository_root,
        manifest_path,
        manifest,
        f"test: mark manifest {gate} failed",
    )

    with pytest.raises(ReleaseEvidenceVerificationError, match=f"manifest {gate} passed"):
        _verify(fixture, capture, manifest_path, release_commit, metadata_path)


@pytest.mark.parametrize(
    ("gate", "report_path"),
    [
        ("integration", "integration_gate/report.json"),
        ("quality", "live_quality_gate/report.json"),
    ],
)
def test_verify_rejects_raw_gate_passed_false_after_rehash(
    tmp_path: Path,
    gate: str,
    report_path: str,
) -> None:
    fixture, capture, manifest_path, _, metadata_path = finalized_release(tmp_path)
    entries = _bundle_entries(capture.bundle_path)
    report = json.loads(entries[report_path])
    report["passed"] = False
    entries[report_path] = _json_bytes(report)
    release_commit, _ = _synchronize_bundle(
        fixture=fixture,
        capture=capture,
        manifest_path=manifest_path,
        entries=entries,
    )

    with pytest.raises(ReleaseEvidenceVerificationError, match="failed gate report"):
        _verify(fixture, capture, manifest_path, release_commit, metadata_path)


@pytest.mark.parametrize(
    ("metric_name", "value"),
    [("failed_count", 1), ("blocked_count", 1), ("case_count", 2)],
)
def test_verify_rejects_manifest_integration_count_mismatch(
    tmp_path: Path,
    metric_name: str,
    value: int,
) -> None:
    fixture, capture, manifest_path, _, metadata_path = finalized_release(tmp_path)
    manifest = _manifest_payload(manifest_path)
    manifest["integration"]["metrics"][metric_name] = value
    release_commit = _commit_manifest(
        fixture.repository_root,
        manifest_path,
        manifest,
        f"test: change manifest {metric_name}",
    )

    with pytest.raises(
        ReleaseEvidenceVerificationError, match=f"integration metric.*{metric_name}"
    ):
        _verify(fixture, capture, manifest_path, release_commit, metadata_path)


@pytest.mark.parametrize("metric_name", ["failed_count", "blocked_count"])
def test_verify_rejects_incomplete_integration_counts_when_manifest_matches_report(
    tmp_path: Path,
    metric_name: str,
) -> None:
    fixture, capture, manifest_path, _, metadata_path = finalized_release(tmp_path)
    entries = _bundle_entries(capture.bundle_path)
    report = json.loads(entries["integration_gate/report.json"])
    report["metrics"][metric_name] = 1
    entries["integration_gate/report.json"] = _json_bytes(report)
    manifest = _manifest_payload(manifest_path)
    manifest["integration"]["metrics"][metric_name] = 1
    release_commit, _ = _synchronize_bundle(
        fixture=fixture,
        capture=capture,
        manifest_path=manifest_path,
        entries=entries,
        manifest=manifest,
    )

    with pytest.raises(ReleaseEvidenceVerificationError, match="failed or blocked"):
        _verify(fixture, capture, manifest_path, release_commit, metadata_path)


def test_verify_rejects_incomplete_integration_case_counts(tmp_path: Path) -> None:
    fixture, capture, manifest_path, _, metadata_path = finalized_release(tmp_path)
    entries = _bundle_entries(capture.bundle_path)
    report = json.loads(entries["integration_gate/report.json"])
    report["metrics"].update(
        {
            "case_count": 2,
            "executed_case_count": 1,
            "observation_count": 1,
        }
    )
    entries["integration_gate/report.json"] = _json_bytes(report)
    policy = json.loads(entries["policies/integration_gate.json"])
    second_case = dict(policy["live_cases"][0])
    second_case["case_id"] = "second_recipe_lookup"
    policy["live_cases"].append(second_case)
    entries["policies/integration_gate.json"] = _json_bytes(policy)
    manifest = _manifest_payload(manifest_path)
    manifest["integration"]["metrics"].update(
        {
            "case_count": 2,
            "executed_case_count": 1,
            "observation_count": 1,
        }
    )
    release_commit, _ = _synchronize_bundle(
        fixture=fixture,
        capture=capture,
        manifest_path=manifest_path,
        entries=entries,
        manifest=manifest,
    )

    with pytest.raises(ReleaseEvidenceVerificationError, match="integration cases"):
        _verify(fixture, capture, manifest_path, release_commit, metadata_path)


@pytest.mark.parametrize(
    ("field_path", "value", "message"),
    [
        (("id",), 999, "artifact id"),
        (("name",), "other-artifact", "artifact name"),
        (("digest",), "sha256:" + "b" * 64, "artifact digest"),
        (("workflow_run", "id"), 999, "workflow run id"),
        (("workflow_run", "head_sha"), "b" * 40, "workflow head sha"),
    ],
)
def test_verify_rejects_artifact_metadata_mismatch(
    tmp_path: Path,
    field_path: tuple[str, ...],
    value: object,
    message: str,
) -> None:
    fixture, capture, manifest_path, release_commit, metadata_path = finalized_release(tmp_path)
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    target = metadata
    for component in field_path[:-1]:
        target = target[component]
    target[field_path[-1]] = value
    write_json(metadata_path, metadata)

    with pytest.raises(ReleaseEvidenceVerificationError, match=message):
        _verify(fixture, capture, manifest_path, release_commit, metadata_path)


def test_verify_accepts_unknown_artifact_metadata_fields(tmp_path: Path) -> None:
    fixture, capture, manifest_path, release_commit, metadata_path = finalized_release(tmp_path)
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata["archive_download_url"] = "https://api.github.invalid/artifacts/456/zip"
    metadata["workflow_run"]["event"] = "workflow_dispatch"
    write_json(metadata_path, metadata)

    manifest = _verify(fixture, capture, manifest_path, release_commit, metadata_path)

    assert manifest.transport.artifact_id == 456


def test_verify_accepts_outer_artifact_size_independent_of_inner_bundle(
    tmp_path: Path,
) -> None:
    fixture, capture, manifest_path, release_commit, metadata_path = finalized_release(tmp_path)
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))

    manifest = _verify(fixture, capture, manifest_path, release_commit, metadata_path)

    assert metadata["size_in_bytes"] != manifest.bundle.bytes


def test_verify_rejects_coerced_artifact_metadata_field(tmp_path: Path) -> None:
    fixture, capture, manifest_path, release_commit, metadata_path = finalized_release(tmp_path)
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata["id"] = "456"
    write_json(metadata_path, metadata)

    with pytest.raises(ReleaseEvidenceVerificationError, match="input is invalid"):
        _verify(fixture, capture, manifest_path, release_commit, metadata_path)


def test_verify_rejects_manifest_not_bound_to_release_commit(tmp_path: Path) -> None:
    fixture, capture, manifest_path, release_commit, metadata_path = finalized_release(tmp_path)
    manifest = _manifest_payload(manifest_path)
    manifest["provenance"]["generated_at"] = "2026-07-16T09:00:00+00:00"
    write_json(manifest_path, manifest)

    with pytest.raises(ReleaseEvidenceVerificationError, match="release commit"):
        _verify(fixture, capture, manifest_path, release_commit, metadata_path)


def test_verify_uses_committed_pyproject_instead_of_worktree(tmp_path: Path) -> None:
    fixture, capture, manifest_path, release_commit, metadata_path = finalized_release(tmp_path)
    (fixture.repository_root / "pyproject.toml").write_text(
        '[project]\nname = "graph-rag-c9"\nversion = "9.9.9"\n',
        encoding="utf-8",
    )

    manifest = _verify(fixture, capture, manifest_path, release_commit, metadata_path)

    assert manifest.release.package_version == "0.4.0rc1"


def test_verify_uses_committed_profile_instead_of_worktree(tmp_path: Path) -> None:
    fixture, capture, manifest_path, release_commit, metadata_path = finalized_release(tmp_path)
    (fixture.repository_root / "profiles" / "eval_quality.toml").write_text(
        "[retrieval]\ntop_k = 7\n",
        encoding="utf-8",
    )

    manifest = _verify(fixture, capture, manifest_path, release_commit, metadata_path)

    assert manifest.runtime.profile.name == "eval_quality"


@pytest.mark.parametrize(
    ("member_path", "field_path", "value", "message"),
    [
        (
            "runtime/diagnostics.json",
            ("runtime", "models", "llm"),
            "other-model",
            "runtime identity",
        ),
        (
            "runtime/artifact_manifest.json",
            ("knowledge_base", "total_documents"),
            324,
            "knowledge-base identity",
        ),
    ],
)
def test_verify_rejects_manifest_identity_not_present_in_bundle(
    tmp_path: Path,
    member_path: str,
    field_path: tuple[str, ...],
    value: object,
    message: str,
) -> None:
    fixture, capture, manifest_path, _, metadata_path = finalized_release(tmp_path)
    manifest = _manifest_payload(manifest_path)
    target = manifest
    for component in field_path[:-1]:
        target = target[component]
    target[field_path[-1]] = value
    release_commit = _commit_manifest(
        fixture.repository_root,
        manifest_path,
        manifest,
        f"test: change {member_path} identity",
    )

    with pytest.raises(ReleaseEvidenceVerificationError, match=message):
        _verify(fixture, capture, manifest_path, release_commit, metadata_path)


def test_verify_rejects_wrong_knowledge_artifact_schema(tmp_path: Path) -> None:
    fixture, capture, manifest_path, _, metadata_path = finalized_release(tmp_path)
    manifest = _manifest_payload(manifest_path)
    manifest["knowledge_base"]["schema_version"] = "graph-rag-artifact-manifest-v1"
    release_commit = _commit_manifest(
        fixture.repository_root,
        manifest_path,
        manifest,
        "test: corrupt knowledge schema",
    )

    with pytest.raises(ReleaseEvidenceVerificationError, match="input is invalid"):
        _verify(fixture, capture, manifest_path, release_commit, metadata_path)


@pytest.mark.parametrize(
    ("policy_path", "policy_kind"),
    [
        ("policies/integration_gate.json", "integration"),
        ("policies/live_quality_gate.json", "live quality"),
    ],
)
def test_verify_rejects_zip_policy_not_present_at_evaluated_commit(
    tmp_path: Path,
    policy_path: str,
    policy_kind: str,
) -> None:
    fixture, capture, manifest_path, _, metadata_path = finalized_release(tmp_path)
    entries = _bundle_entries(capture.bundle_path)
    policy = json.loads(entries[policy_path])
    policy["timeouts"]["request_seconds"] = 89.0
    entries[policy_path] = _json_bytes(policy)
    manifest = _manifest_payload(manifest_path)
    if policy_kind == "live quality":
        manifest["dataset"]["sha256"] = _sha256(entries[policy_path])
    release_commit, _ = _synchronize_bundle(
        fixture=fixture,
        capture=capture,
        manifest_path=manifest_path,
        entries=entries,
        manifest=manifest,
    )

    with pytest.raises(ReleaseEvidenceVerificationError, match=f"{policy_kind} policy"):
        _verify(fixture, capture, manifest_path, release_commit, metadata_path)


def test_verify_rejects_self_consistent_extra_bundle_member(tmp_path: Path) -> None:
    fixture, capture, manifest_path, _, metadata_path = finalized_release(tmp_path)
    entries = _bundle_entries(capture.bundle_path)
    entries["notes.txt"] = b"unexpected but internally checksummed\n"
    release_commit, _ = _synchronize_bundle(
        fixture=fixture,
        capture=capture,
        manifest_path=manifest_path,
        entries=entries,
        extra_artifact_names={"notes.txt": "notes"},
    )

    with pytest.raises(ReleaseEvidenceVerificationError, match="allowed members"):
        _verify(fixture, capture, manifest_path, release_commit, metadata_path)


def test_verify_rejects_manifest_artifact_name_mismatch(tmp_path: Path) -> None:
    fixture, capture, manifest_path, _, metadata_path = finalized_release(tmp_path)
    manifest = _manifest_payload(manifest_path)
    artifact = next(
        item for item in manifest["artifacts"] if item["path"] == "integration_gate/report.json"
    )
    artifact["name"] = "wrong_name"
    release_commit = _commit_manifest(
        fixture.repository_root,
        manifest_path,
        manifest,
        "test: change artifact logical name",
    )

    with pytest.raises(ReleaseEvidenceVerificationError, match="artifact identities"):
        _verify(fixture, capture, manifest_path, release_commit, metadata_path)


def test_verify_rejects_runtime_target_not_bound_to_reports(tmp_path: Path) -> None:
    fixture, capture, manifest_path, _, metadata_path = finalized_release(tmp_path)
    entries = _bundle_entries(capture.bundle_path)
    runtime = json.loads(entries["runtime/diagnostics.json"])
    runtime["target"]["api_host"] = "other.example.com"
    entries["runtime/diagnostics.json"] = _json_bytes(runtime)
    manifest = _manifest_payload(manifest_path)
    manifest["runtime"] = runtime
    release_commit, _ = _synchronize_bundle(
        fixture=fixture,
        capture=capture,
        manifest_path=manifest_path,
        entries=entries,
        manifest=manifest,
    )

    with pytest.raises(ReleaseEvidenceVerificationError, match="runtime target"):
        _verify(fixture, capture, manifest_path, release_commit, metadata_path)


def test_verify_rejects_transport_name_not_derived_from_release(tmp_path: Path) -> None:
    fixture, capture, manifest_path, _, metadata_path = finalized_release(tmp_path)
    manifest = _manifest_payload(manifest_path)
    manifest["transport"]["artifact_name"] = "other-quality-evidence"
    release_commit = _commit_manifest(
        fixture.repository_root,
        manifest_path,
        manifest,
        "test: change transport name",
    )
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata["name"] = "other-quality-evidence"
    write_json(metadata_path, metadata)

    with pytest.raises(ReleaseEvidenceVerificationError, match="artifact name.*release"):
        _verify(fixture, capture, manifest_path, release_commit, metadata_path)


def test_verify_rejects_bundle_name_not_derived_from_release(tmp_path: Path) -> None:
    fixture, capture, manifest_path, _, metadata_path = finalized_release(tmp_path)
    alternate_bundle = tmp_path / "graph-rag-c9-9.9.9-quality-evidence.zip"
    entries = _bundle_entries(capture.bundle_path)
    release_commit, bundle_path = _synchronize_bundle(
        fixture=fixture,
        capture=capture,
        manifest_path=manifest_path,
        entries=entries,
        bundle_path=alternate_bundle,
    )

    with pytest.raises(ReleaseEvidenceVerificationError, match="bundle name.*release"):
        verify_release_evidence(
            VerifyInputs(
                repository_root=fixture.repository_root,
                manifest_path=manifest_path,
                release_commit=release_commit,
                tag="v0.4.0-rc.1",
                bundle_path=bundle_path,
                artifact_metadata_path=metadata_path,
            )
        )
