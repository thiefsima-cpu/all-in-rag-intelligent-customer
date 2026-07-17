from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def workflow_text() -> str:
    return (ROOT / ".github/workflows/release-evidence.yml").read_text(encoding="utf-8")


def job_text(workflow: str, name: str, *, next_job: str | None = None) -> str:
    start = workflow.index(f"  {name}:")
    end = len(workflow) if next_job is None else workflow.index(f"\n  {next_job}:", start)
    return workflow[start:end]


def step_text(job: str, name: str) -> str:
    start = job.index(f"      - name: {name}")
    end = job.find("\n      - name:", start + 1)
    return job[start:] if end == -1 else job[start:end]


def secret_names(fragment: str) -> set[str]:
    return set(re.findall(r"\$\{\{ secrets\.([A-Z0-9_]+) \}\}", fragment))


def test_capture_workflow_runs_gates_before_upload_and_finalize() -> None:
    workflow = workflow_text()
    preflight = workflow.index("- name: Validate capture request")
    checkout = workflow.index("- name: Check out evaluated commit")
    setup = workflow.index("- name: Set up Python")
    install = workflow.index("- name: Install dependencies")
    integration = workflow.index("python -m scripts.integration_gate")
    live_quality = workflow.index("python -m scripts.live_quality_gate")
    capture = workflow.index("python -m scripts.release_evidence capture")
    upload = workflow.index("id: evidence-upload")
    finalize = workflow.index("python -m scripts.release_evidence finalize")

    assert preflight < checkout < setup < install < integration
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
    assert "inputs.runner == 'self-hosted'" in workflow
    assert 'fromJSON(\'["self-hosted", "linux"]\')' in workflow
    assert "environment: release-quality" in workflow
    assert "if: inputs.operation == 'verify'" in workflow
    assert "ref: ${{ inputs.evaluated_commit }}" in workflow
    assert "ref: ${{ inputs.release_commit }}" in workflow


def test_capture_preflight_binds_event_sha_and_external_manifest_before_checkout() -> None:
    workflow = workflow_text()
    capture = job_text(workflow, "capture", next_job="verify")
    header, _steps = capture.split("    steps:", maxsplit=1)
    preflight = step_text(capture, "Validate capture request")

    assert "\n    env:" not in header
    assert "secrets." not in header
    assert "defaults:" in header
    assert "shell: bash" in header
    assert "WORKFLOW_HEAD_SHA: ${{ github.sha }}" in preflight
    assert "EVALUATED_COMMIT: ${{ inputs.evaluated_commit }}" in preflight
    assert 'test "${WORKFLOW_HEAD_SHA}" = "${EVALUATED_COMMIT}"' in preflight
    assert "REQUESTED_RUNNER: ${{ inputs.runner }}" in preflight
    assert 'if [[ "${REQUESTED_RUNNER}" != "self-hosted" ]]' in preflight
    assert "RELEASE_EVIDENCE_ARTIFACT_MANIFEST_PATH: ${{" in preflight
    assert 'test -n "${RELEASE_EVIDENCE_ARTIFACT_MANIFEST_PATH}"' in preflight
    assert '[[ "${RELEASE_EVIDENCE_ARTIFACT_MANIFEST_PATH}" == /* ]]' in preflight
    assert 'test -f "${RELEASE_EVIDENCE_ARTIFACT_MANIFEST_PATH}"' in preflight
    assert 'realpath "${RELEASE_EVIDENCE_ARTIFACT_MANIFEST_PATH}"' in preflight
    assert 'realpath "${GITHUB_WORKSPACE}"' in preflight
    assert '"${workspace_path}"/*' in preflight
    assert "secrets." not in preflight


def test_capture_job_scopes_secrets_to_only_the_steps_that_need_them() -> None:
    workflow = workflow_text()
    capture = job_text(workflow, "capture", next_job="verify")
    integration = step_text(capture, "Run real-dependency integration gate")
    live_quality = step_text(capture, "Run live quality gate")
    evidence = step_text(capture, "Capture complete release evidence")

    assert secret_names(integration) == {
        "INTEGRATION_GATE_API_URL",
        "INTEGRATION_GATE_API_TOKEN",
        "NEO4J_URI",
        "NEO4J_USER",
        "NEO4J_PASSWORD",
    }
    assert secret_names(live_quality) == {
        "LIVE_QUALITY_API_URL",
        "LIVE_QUALITY_API_TOKEN",
        "LIVE_QUALITY_JUDGE_API_URL",
        "LIVE_QUALITY_JUDGE_API_KEY",
    }
    assert secret_names(evidence) == {
        "LIVE_QUALITY_API_URL",
        "LIVE_QUALITY_API_TOKEN",
    }
    assert "vars.RELEASE_EVIDENCE_ARTIFACT_MANIFEST_PATH" in evidence

    for step_name in (
        "Check out evaluated commit",
        "Set up Python",
        "Install dependencies",
        "Verify evaluated checkout",
        "Upload complete evidence bundle",
        "Finalize compact evidence manifest",
        "Upload compact manifest for release pull request",
    ):
        step = step_text(capture, step_name)
        assert "secrets." not in step

    for step_name in (
        "Check out evaluated commit",
        "Set up Python",
        "Install dependencies",
        "Upload complete evidence bundle",
        "Finalize compact evidence manifest",
        "Upload compact manifest for release pull request",
    ):
        step = step_text(capture, step_name)
        assert "\n        env:" not in step


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

    capture = job_text(workflow, "capture", next_job="verify")
    finalize = step_text(capture, "Finalize compact evidence manifest")
    assert '--workflow-head-sha "${{ github.sha }}"' in finalize
    assert "inputs.evaluated_commit" not in finalize
    assert "secrets." not in finalize


def test_verify_workflow_queries_and_downloads_selected_artifact() -> None:
    workflow = workflow_text()
    verify = job_text(workflow, "verify")
    header, _steps = verify.split("    steps:", maxsplit=1)
    preflight = step_text(verify, "Validate verify request")
    checkout = step_text(verify, "Check out release commit")

    assert "gh api" in workflow
    assert "gh run download" in workflow
    assert "python -m scripts.release_evidence verify" in workflow
    assert "actions: read" in workflow
    assert "defaults:" in header
    assert "shell: bash" in header
    assert "\n    env:" not in header
    assert "RELEASE_COMMIT: ${{ inputs.release_commit }}" in preflight
    assert 'test -n "${RELEASE_COMMIT}"' in preflight
    assert verify.index("- name: Validate verify request") < verify.index(
        "- name: Check out release commit"
    )
    assert "ref: ${{ inputs.release_commit }}" in checkout
    assert "github.token" not in header + preflight + checkout
    assert "GH_TOKEN: ${{ github.token }}" in step_text(verify, "Query selected artifact metadata")
    assert "GH_TOKEN: ${{ github.token }}" in step_text(
        verify, "Download selected complete evidence"
    )
    for argument in (
        '--manifest "${{ steps.evidence.outputs.manifest }}"',
        '--release-commit "${{ inputs.release_commit }}"',
        '--tag "${{ inputs.tag }}"',
        '--bundle "downloaded-evidence/${{ steps.evidence.outputs.bundle_name }}"',
        "--artifact-metadata artifact-metadata.json",
    ):
        assert argument in workflow
