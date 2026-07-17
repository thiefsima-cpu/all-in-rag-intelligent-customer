from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def workflow_text() -> str:
    return (ROOT / ".github/workflows/release-evidence.yml").read_text(encoding="utf-8")


def test_capture_workflow_runs_gates_before_upload_and_finalize() -> None:
    workflow = workflow_text()
    integration = workflow.index("python -m scripts.integration_gate")
    live_quality = workflow.index("python -m scripts.live_quality_gate")
    capture = workflow.index("python -m scripts.release_evidence capture")
    upload = workflow.index("id: evidence-upload")
    finalize = workflow.index("python -m scripts.release_evidence finalize")

    assert integration < live_quality < capture < upload < finalize
    assert workflow.count("retention-days: 90") == 2
    assert "LIVE_QUALITY_JUDGE_MODEL" in workflow
    assert "RELEASE_EVIDENCE_ARTIFACT_MANIFEST_PATH" in workflow


def test_manual_workflow_declares_complete_auditable_dispatch_contract() -> None:
    workflow = workflow_text()

    for input_name in (
        "operation",
        "evaluated_commit",
        "release_commit",
        "package_version",
        "tag",
        "runner",
    ):
        assert f"      {input_name}:" in workflow

    assert "if: inputs.operation == 'capture'" in workflow
    assert "runs-on: ${{ inputs.runner }}" in workflow
    assert "environment: release-quality" in workflow
    assert "if: inputs.operation == 'verify'" in workflow
    assert "ref: ${{ inputs.evaluated_commit }}" in workflow
    assert "ref: ${{ inputs.release_commit }}" in workflow


def test_capture_and_finalize_cli_receive_required_evidence_identity() -> None:
    workflow = workflow_text()

    for argument in (
        "--repository-root .",
        '--repository "${{ github.repository }}"',
        '--package-version "${{ inputs.package_version }}"',
        '--tag "${{ inputs.tag }}"',
        '--evaluated-commit "${{ inputs.evaluated_commit }}"',
        "--integration-policy eval/integration_gate.json",
        "--live-quality-policy eval/live_quality_gate.json",
        "--integration-report eval/reports/integration_gate/report.json",
        "--live-quality-report eval/reports/live_quality_gate/report.json",
        '--diagnostics-url "${LIVE_QUALITY_API_URL%/}/v1/diagnostics"',
        '--artifact-manifest "${RELEASE_EVIDENCE_ARTIFACT_MANIFEST_PATH}"',
        '--judge-model "${LIVE_QUALITY_JUDGE_MODEL}"',
        '--artifact-id "${{ steps.evidence-upload.outputs.artifact-id }}"',
        '--artifact-digest "${{ steps.evidence-upload.outputs.artifact-digest }}"',
    ):
        assert argument in workflow

    finalize = workflow[workflow.index("python -m scripts.release_evidence finalize") :]
    assert "secrets." not in finalize


def test_verify_workflow_queries_and_downloads_selected_artifact() -> None:
    workflow = workflow_text()

    assert "gh api" in workflow
    assert "gh run download" in workflow
    assert "python -m scripts.release_evidence verify" in workflow
    assert "actions: read" in workflow
    for argument in (
        '--manifest "${{ steps.evidence.outputs.manifest }}"',
        '--release-commit "${{ inputs.release_commit }}"',
        '--tag "${{ inputs.tag }}"',
        '--bundle "downloaded-evidence/${{ steps.evidence.outputs.bundle_name }}"',
        "--artifact-metadata artifact-metadata.json",
    ):
        assert argument in workflow
