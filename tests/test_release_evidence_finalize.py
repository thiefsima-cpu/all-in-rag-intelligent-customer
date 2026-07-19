from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from scripts.release_evidence.capture import CaptureInputs, capture_release_evidence
from scripts.release_evidence.finalize import (
    ReleaseEvidenceFinalizeError,
    finalize_release_evidence,
)
from scripts.release_evidence.models import (
    ReleaseEvidenceManifest,
    TransportIdentity,
    load_capture_receipt,
    load_release_evidence_manifest,
)
from tests.release_evidence_fixtures import make_release_evidence_fixture


def captured(tmp_path: Path):
    fixture = make_release_evidence_fixture(tmp_path)
    outputs = capture_release_evidence(
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
    return fixture, outputs


def test_finalize_preserves_capture_core_and_adds_transport(tmp_path: Path) -> None:
    fixture, outputs = captured(tmp_path)
    output_path = tmp_path / "evidence-manifest.json"
    transport = TransportIdentity(
        provider="github-actions",
        workflow_run_id=123,
        workflow_head_sha=fixture.evaluated_commit,
        artifact_id=456,
        artifact_name="graph-rag-c9-0.4.0rc1-quality-evidence",
        artifact_digest="sha256:" + "a" * 64,
    )

    finalized = finalize_release_evidence(outputs.receipt_path, transport, output_path)

    receipt = load_capture_receipt(outputs.receipt_path)
    manifest = load_release_evidence_manifest(output_path)
    assert finalized == manifest
    assert manifest.transport == transport
    assert manifest.model_dump(exclude={"schema_version", "transport"}) == receipt.model_dump(
        exclude={"schema_version"}
    )


def test_manifest_model_rejects_v1_schema(tmp_path: Path) -> None:
    fixture, outputs = captured(tmp_path)
    receipt = load_capture_receipt(outputs.receipt_path)
    payload = receipt.model_dump()
    payload.update(
        {
            "schema_version": "graph-rag-release-evidence-v1",
            "transport": {
                "provider": "github-actions",
                "workflow_run_id": 123,
                "workflow_head_sha": fixture.evaluated_commit,
                "artifact_id": 456,
                "artifact_name": "graph-rag-c9-0.4.0rc1-quality-evidence",
                "artifact_digest": "sha256:" + "a" * 64,
            },
        }
    )

    with pytest.raises(ValidationError):
        ReleaseEvidenceManifest.model_validate(payload)


def test_finalize_rejects_workflow_head_mismatch(tmp_path: Path) -> None:
    _, outputs = captured(tmp_path)
    transport = TransportIdentity(
        provider="github-actions",
        workflow_run_id=123,
        workflow_head_sha="b" * 40,
        artifact_id=456,
        artifact_name="graph-rag-c9-0.4.0rc1-quality-evidence",
        artifact_digest="sha256:" + "a" * 64,
    )

    with pytest.raises(ReleaseEvidenceFinalizeError, match="workflow head"):
        finalize_release_evidence(outputs.receipt_path, transport, tmp_path / "manifest.json")


def test_finalize_rejects_artifact_name_mismatch(tmp_path: Path) -> None:
    fixture, outputs = captured(tmp_path)
    transport = TransportIdentity(
        provider="github-actions",
        workflow_run_id=123,
        workflow_head_sha=fixture.evaluated_commit,
        artifact_id=456,
        artifact_name="graph-rag-c9-other-quality-evidence",
        artifact_digest="sha256:" + "a" * 64,
    )

    with pytest.raises(ReleaseEvidenceFinalizeError, match="artifact name"):
        finalize_release_evidence(outputs.receipt_path, transport, tmp_path / "manifest.json")
