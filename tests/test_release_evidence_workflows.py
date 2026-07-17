from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def workflow_text() -> str:
    return (ROOT / ".github/workflows/release-evidence.yml").read_text(encoding="utf-8")


def release_workflow_text() -> str:
    return (ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8")


def job_text(workflow: str, name: str, *, next_job: str | None = None) -> str:
    start = workflow.index(f"  {name}:")
    end = len(workflow) if next_job is None else workflow.index(f"\n  {next_job}:", start)
    return workflow[start:end]


def step_text(job: str, name: str) -> str:
    start = job.index(f"      - name: {name}")
    end = job.find("\n      - name:", start + 1)
    return job[start:] if end == -1 else job[start:end]


def run_text(step: str) -> str:
    marker = "\n        run:"
    assert marker in step
    return step.split(marker, maxsplit=1)[1]


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
        "Upload compact manifest for release pull request",
    ):
        step = step_text(capture, step_name)
        assert "\n        env:" not in step


def test_capture_and_finalize_cli_receive_required_evidence_identity() -> None:
    workflow = workflow_text()
    capture_job = job_text(workflow, "capture", next_job="verify")
    capture = step_text(capture_job, "Capture complete release evidence")
    capture_run = run_text(capture)
    finalize = step_text(capture_job, "Finalize compact evidence manifest")
    finalize_run = run_text(finalize)

    for binding in (
        "REPOSITORY: ${{ github.repository }}",
        "PACKAGE_VERSION: ${{ inputs.package_version }}",
        "RELEASE_TAG: ${{ inputs.tag }}",
        "EVALUATED_COMMIT: ${{ inputs.evaluated_commit }}",
        "RELEASE_EVIDENCE_OUTPUT_DIR: eval/reports/release_evidence/${{ inputs.package_version }}",
    ):
        assert binding in capture
    for argument in (
        "--repository-root .",
        '--repository "${REPOSITORY}"',
        '--package-version "${PACKAGE_VERSION}"',
        '--tag "${RELEASE_TAG}"',
        '--evaluated-commit "${EVALUATED_COMMIT}"',
        "--integration-policy eval/integration_gate.json",
        "--live-quality-policy eval/live_quality_gate.json",
        "--integration-report eval/reports/integration_gate/report.json",
        "--live-quality-report eval/reports/live_quality_gate/report.json",
        '--diagnostics-url "${LIVE_QUALITY_API_URL%/}/v1/diagnostics"',
        '--artifact-manifest "${RELEASE_EVIDENCE_ARTIFACT_MANIFEST_PATH}"',
        '--judge-model "${LIVE_QUALITY_JUDGE_MODEL}"',
        '--output-dir "${RELEASE_EVIDENCE_OUTPUT_DIR}"',
    ):
        assert argument in capture_run

    for binding in (
        "CAPTURE_RECEIPT: eval/reports/release_evidence/${{ inputs.package_version }}/capture-receipt.json",
        "WORKFLOW_HEAD_SHA: ${{ github.sha }}",
        "ARTIFACT_ID: ${{ steps.evidence-upload.outputs.artifact-id }}",
        "ARTIFACT_NAME: graph-rag-c9-${{ inputs.package_version }}-quality-evidence",
        "ARTIFACT_DIGEST: ${{ steps.evidence-upload.outputs.artifact-digest }}",
        "MANIFEST_OUTPUT: eval/reports/release_evidence/${{ inputs.package_version }}/evidence-manifest.json",
    ):
        assert binding in finalize
    for argument in (
        '--capture-receipt "${CAPTURE_RECEIPT}"',
        '--workflow-head-sha "${WORKFLOW_HEAD_SHA}"',
        '--artifact-id "${ARTIFACT_ID}"',
        '--artifact-name "${ARTIFACT_NAME}"',
        '--artifact-digest "${ARTIFACT_DIGEST}"',
        '--output "${MANIFEST_OUTPUT}"',
    ):
        assert argument in finalize_run
    assert "secrets." not in finalize


def test_run_scripts_do_not_inline_actions_expressions() -> None:
    workflow = workflow_text()

    for job in (
        job_text(workflow, "capture", next_job="verify"),
        job_text(workflow, "verify"),
    ):
        for raw_step in job.split("\n      - name:")[1:]:
            step = "      - name:" + raw_step
            if "\n        run:" in step:
                assert "${{" not in run_text(step)


def test_resolve_step_strictly_validates_manifest_before_safe_outputs() -> None:
    workflow = workflow_text()
    verify = job_text(workflow, "verify")
    resolve = step_text(verify, "Resolve selected artifact identity")
    run = run_text(resolve)

    assert "PACKAGE_VERSION: ${{ inputs.package_version }}" in resolve
    assert "EXPECTED_TAG: ${{ inputs.tag }}" in resolve
    assert "EXPECTED_EVALUATED_COMMIT: ${{ inputs.evaluated_commit }}" in resolve
    assert "EXPECTED_REPOSITORY: ${{ github.repository }}" in resolve
    for contract in (
        "from scripts.validate_release_tag import parse_release_tag",
        "from scripts.release_evidence.models import load_release_evidence_manifest",
        "parsed_tag = parse_release_tag(expected_tag)",
        "validated_version = parsed_tag.package_version",
        "if validated_version != package_version:",
        'manifest_path = Path("quality-evidence", "releases", validated_version,',
        "manifest = load_release_evidence_manifest(manifest_path)",
        'expected_artifact_name = f"graph-rag-c9-{validated_version}-quality-evidence"',
        'expected_bundle_name = f"{expected_artifact_name}.zip"',
        "if manifest.release.package_version != validated_version:",
        "if manifest.release.tag != expected_tag:",
        "if manifest.provenance.evaluated_commit != expected_evaluated_commit:",
        "if manifest.provenance.repository != expected_repository:",
        "if manifest.transport.artifact_name != expected_artifact_name:",
        "if manifest.bundle.name != expected_bundle_name:",
        'Path(os.environ["GITHUB_OUTPUT"]).open(',
        'f"artifact_id={manifest.transport.artifact_id}"',
        'f"run_id={manifest.transport.workflow_run_id}"',
        'f"artifact_name={expected_artifact_name}"',
        'f"bundle_name={expected_bundle_name}"',
    ):
        assert contract in run
    assert "json.load" not in run
    assert "echo " not in run


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
    resolve = step_text(verify, "Resolve selected artifact identity")
    query = step_text(verify, "Query selected artifact metadata")
    assert "GH_TOKEN: ${{ github.token }}" in query
    assert "ARTIFACT_ID: ${{ steps.evidence.outputs.artifact_id }}" in query
    assert 'actions/artifacts/${ARTIFACT_ID}"' in run_text(query)

    download = step_text(verify, "Download selected complete evidence")
    assert "GH_TOKEN: ${{ github.token }}" in download
    assert "RUN_ID: ${{ steps.evidence.outputs.run_id }}" in download
    assert "ARTIFACT_NAME: ${{ steps.evidence.outputs.artifact_name }}" in download
    assert 'gh run download "${RUN_ID}"' in run_text(download)
    assert '--name "${ARTIFACT_NAME}"' in run_text(download)
    assert verify.index(resolve) < verify.index(query) < verify.index(download)
    assert "manifest.provenance.repository != expected_repository" in run_text(resolve)

    verify_evidence = step_text(verify, "Verify release evidence before tagging")
    for binding in (
        "EVIDENCE_MANIFEST: ${{ steps.evidence.outputs.manifest }}",
        "RELEASE_COMMIT: ${{ inputs.release_commit }}",
        "RELEASE_TAG: ${{ inputs.tag }}",
        "EVIDENCE_BUNDLE: downloaded-evidence/${{ steps.evidence.outputs.bundle_name }}",
    ):
        assert binding in verify_evidence
    for argument in (
        '--manifest "${EVIDENCE_MANIFEST}"',
        '--release-commit "${RELEASE_COMMIT}"',
        '--tag "${RELEASE_TAG}"',
        '--bundle "${EVIDENCE_BUNDLE}"',
        "--artifact-metadata artifact-metadata.json",
    ):
        assert argument in run_text(verify_evidence)


def test_tag_workflow_verifies_evidence_before_build_and_draft_release() -> None:
    workflow = release_workflow_text()
    artifacts = job_text(workflow, "release-artifacts", next_job="publish-draft")
    publish = job_text(workflow, "publish-draft")

    provenance = artifacts.index("- name: Validate tag provenance")
    resolve = artifacts.index("- name: Resolve selected release evidence")
    verify = artifacts.index("python -m scripts.release_evidence verify")
    build = artifacts.index("python -m build --sdist --wheel")
    metadata = artifacts.index("scripts/verify_distribution_metadata.py")
    sbom = artifacts.index("anchore/sbom-action@v0")
    upload = artifacts.index("actions/upload-artifact@v7")
    draft = publish.index("gh release create")

    assert provenance < resolve < verify < build < metadata < sbom < upload
    assert draft > publish.index("gh run download")
    assert "pypa/gh-action-pypi-publish" not in workflow


def test_tag_workflow_separates_read_only_build_from_write_only_publication() -> None:
    workflow = release_workflow_text()
    artifacts = job_text(workflow, "release-artifacts", next_job="publish-draft")
    publish = job_text(workflow, "publish-draft")
    artifact_header, _artifact_steps = artifacts.split("    steps:", maxsplit=1)
    publish_header, publish_steps = publish.split("    steps:", maxsplit=1)

    assert "permissions: {}" in workflow.split("jobs:", maxsplit=1)[0]
    assert "group: release-${{ github.ref_name }}" in workflow
    assert "cancel-in-progress: false" in workflow
    assert "contents: read" in artifact_header
    assert "actions: read" in artifact_header
    assert "contents: write" not in artifact_header
    assert "needs: release-artifacts" in publish_header
    assert "contents: write" in publish_header
    assert "actions: read" in publish_header
    assert "uses:" not in publish_steps
    for forbidden in (
        "actions/checkout",
        "actions/setup-python",
        "anchore/sbom-action",
        "pip install",
        "python -m",
        "scripts/",
    ):
        assert forbidden not in publish_steps


def test_tag_workflow_strictly_resolves_committed_evidence_identity() -> None:
    workflow = release_workflow_text()
    artifacts = job_text(workflow, "release-artifacts", next_job="publish-draft")
    resolve = step_text(artifacts, "Resolve selected release evidence")
    run = run_text(resolve)

    assert "RELEASE_TAG: ${{ github.ref_name }}" in resolve
    assert "GITHUB_REPOSITORY: ${{ github.repository }}" in resolve
    for contract in (
        "from scripts.validate_release_tag import parse_release_tag",
        "from scripts.release_evidence.models import load_release_evidence_manifest",
        "parsed_tag = parse_release_tag(release_tag)",
        "validated_version = parsed_tag.package_version",
        'manifest_path = Path("quality-evidence", "releases", validated_version,',
        "manifest = load_release_evidence_manifest(manifest_path)",
        'expected_artifact_name = f"graph-rag-c9-{validated_version}-quality-evidence"',
        'expected_bundle_name = f"{expected_artifact_name}.zip"',
        "if manifest.release.package_version != validated_version:",
        "if manifest.release.tag != release_tag:",
        'if manifest.provenance.repository != os.environ["GITHUB_REPOSITORY"]:',
        "if manifest.transport.artifact_name != expected_artifact_name:",
        "if manifest.bundle.name != expected_bundle_name:",
        'Path(os.environ["GITHUB_OUTPUT"]).open(',
        'f"artifact_id={manifest.transport.artifact_id}',
        'f"run_id={manifest.transport.workflow_run_id}',
        'f"artifact_name={expected_artifact_name}',
        'f"bundle_name={expected_bundle_name}',
        'f"package_version={validated_version}',
        'f"release_tag={parsed_tag.tag}',
    ):
        assert contract in run
    assert "json.load" not in run
    assert "echo " not in run


def test_tag_workflow_requires_manifest_to_be_a_regular_tracked_blob_before_loading() -> None:
    workflow = release_workflow_text()
    artifacts = job_text(workflow, "release-artifacts", next_job="publish-draft")
    resolve = step_text(artifacts, "Resolve selected release evidence")
    run = run_text(resolve)

    tracked = run.index('["git", "ls-files", "--stage", "-z", "--",')
    lstat = run.index("manifest_path.lstat()")
    symlink = run.index("manifest_path.is_symlink()")
    resolved = run.index("manifest_path.resolve(strict=True)")
    load = run.index("load_release_evidence_manifest(manifest_path)")
    assert tracked < lstat < symlink < resolved < load
    for contract in (
        'if mode != "100644" or stage != "0":',
        're.fullmatch(r"[0-9a-f]{40}", object_id)',
        "stat.S_ISREG(manifest_stat.st_mode)",
        "manifest_resolved.relative_to(repository_root)",
        "if tracked_path != manifest_path.as_posix():",
    ):
        assert contract in run


def test_tag_workflow_queries_downloads_and_verifies_exact_selected_artifact() -> None:
    workflow = release_workflow_text()
    artifacts = job_text(workflow, "release-artifacts", next_job="publish-draft")

    query = step_text(artifacts, "Query selected evidence artifact")
    assert "GH_TOKEN: ${{ github.token }}" in query
    assert "GH_REPO: ${{ github.repository }}" in query
    assert "ARTIFACT_ID: ${{ steps.evidence.outputs.artifact_id }}" in query
    assert 'actions/artifacts/${ARTIFACT_ID}"' in run_text(query)

    download = step_text(artifacts, "Download selected evidence artifact")
    assert "GH_TOKEN: ${{ github.token }}" in download
    assert "GH_REPO: ${{ github.repository }}" in download
    assert "RUN_ID: ${{ steps.evidence.outputs.run_id }}" in download
    assert "ARTIFACT_NAME: ${{ steps.evidence.outputs.artifact_name }}" in download
    assert 'gh run download "${RUN_ID}"' in run_text(download)
    assert '--name "${ARTIFACT_NAME}"' in run_text(download)
    assert '--dir "downloaded-evidence"' in run_text(download)

    verify = step_text(artifacts, "Verify selected release evidence")
    assert "RELEASE_COMMIT: ${{ steps.provenance.outputs.tag_commit }}" in verify
    assert "RELEASE_TAG: ${{ steps.evidence.outputs.release_tag }}" in verify
    assert "EVIDENCE_MANIFEST: ${{ steps.evidence.outputs.manifest }}" in verify
    assert "EVIDENCE_BUNDLE: downloaded-evidence/${{" in verify
    for argument in (
        '--manifest "${EVIDENCE_MANIFEST}"',
        '--release-commit "${RELEASE_COMMIT}"',
        '--tag "${RELEASE_TAG}"',
        '--bundle "${EVIDENCE_BUNDLE}"',
        '--artifact-metadata "artifact-metadata.json"',
    ):
        assert argument in run_text(verify)


def test_tag_workflow_run_blocks_never_inline_actions_expressions() -> None:
    workflow = release_workflow_text()

    for job in (
        job_text(workflow, "release-artifacts", next_job="publish-draft"),
        job_text(workflow, "publish-draft"),
    ):
        for raw_step in job.split("\n      - name:")[1:]:
            step = "      - name:" + raw_step
            if "\n        run:" in step:
                assert "${{" not in run_text(step)


def test_tag_workflow_publishes_exact_current_run_payload_as_draft() -> None:
    workflow = release_workflow_text()
    artifacts = job_text(workflow, "release-artifacts", next_job="publish-draft")
    publish = job_text(workflow, "publish-draft")

    upload = step_text(artifacts, "Upload verified release payload")
    assert "path: release-payload-stage/" in upload
    assert "dist/*.whl" not in upload
    assert "downloaded-evidence/${{" not in upload
    assert "if-no-files-found: error" in upload
    assert "overwrite: true" in upload
    assert "retention-days: 90" in upload

    download = step_text(publish, "Download current run release payload")
    assert "CURRENT_RUN_ID: ${{ github.run_id }}" in download
    assert "GH_REPO: ${{ github.repository }}" in download
    assert "RELEASE_ARTIFACT_NAME: ${{ needs.release-artifacts.outputs.artifact_name }}" in download
    assert 'gh run download "${CURRENT_RUN_ID}"' in run_text(download)
    assert '--name "${RELEASE_ARTIFACT_NAME}"' in run_text(download)
    assert '--dir "release-payload"' in run_text(download)

    release = step_text(publish, "Create or update draft GitHub Release")
    release_run = run_text(release)
    for binding in (
        "RELEASE_TAG: ${{ needs.release-artifacts.outputs.release_tag }}",
        "WHEEL_NAME: ${{ needs.release-artifacts.outputs.wheel_name }}",
        "SDIST_NAME: ${{ needs.release-artifacts.outputs.sdist_name }}",
        "MANIFEST_PATH: ${{ needs.release-artifacts.outputs.manifest_path }}",
        "BUNDLE_NAME: ${{ needs.release-artifacts.outputs.bundle_name }}",
        "GH_REPO: ${{ github.repository }}",
    ):
        assert binding in release
    for asset in (
        "release-payload/dist/${WHEEL_NAME}",
        "release-payload/dist/${SDIST_NAME}",
        "release-payload/sbom.cdx.json",
        "release-payload/${MANIFEST_PATH}",
        "release-payload/downloaded-evidence/${BUNDLE_NAME}",
    ):
        assert asset in release_run
    assert 'test "${is_draft}" = "true"' in release_run
    assert 'gh release upload "${RELEASE_TAG}"' in release_run
    assert "--clobber" in release_run
    assert 'gh release create "${RELEASE_TAG}"' in release_run
    assert "--draft" in release_run
    assert "--verify-tag" in release_run
    assert "--prerelease" in release_run
    assert "shopt -s nullglob" in release_run
    assert 'test "${#wheels[@]}" -eq 1' in release_run
    assert 'test "${#sdists[@]}" -eq 1' in release_run
    assert 'test "${#assets[@]}" -eq 5' in release_run
    assert 'test ! -L "${asset}"' in release_run
    assert 'gh api --paginate "repos/${GH_REPO}/releases?per_page=100" --slurp' in release_run
    assert 'test "${release_count}" -le 1' in release_run
    assert 'test "${is_prerelease}" = "${PRERELEASE}"' in release_run
    assert 'test "${existing_tag}" = "${RELEASE_TAG}"' in release_run
    assert 'for expected_name in "${expected_names[@]}"' in release_run
    assert 'test "${matched}" = "true"' in release_run
    assert "gh api \"repos/${GH_REPO}/commits/${RELEASE_TAG}\" --jq '.sha'" in release_run
    assert 'test "${remote_tag_commit}" = "${TAG_COMMIT}"' in release_run
    assert (
        release_run.count('gh api --paginate "repos/${GH_REPO}/releases?per_page=100" --slurp') == 2
    )
    assert "repos/${GH_REPO}/releases/tags/${RELEASE_TAG}" not in release_run
    assert '"existing-releases.json" > "selected-releases.json"' in release_run
    assert '"final-releases.json" > "final-selected-releases.json"' in release_run
    assert 'test "${final_draft}" = "true"' in release_run
    assert 'test "${final_prerelease}" = "${PRERELEASE}"' in release_run
    assert 'test "${final_tag}" = "${RELEASE_TAG}"' in release_run
    assert 'test "${#final_assets[@]}" -eq 5' in release_run
    assert 'test "${match_count}" -eq 1' in release_run
    assert "declare -A" not in release_run


def test_tag_workflow_finally_reverifies_after_sbom_before_staging_and_upload() -> None:
    workflow = release_workflow_text()
    artifacts = job_text(workflow, "release-artifacts", next_job="publish-draft")
    freeze = step_text(artifacts, "Freeze and stage verified release payload")
    freeze_run = run_text(freeze)

    sbom = artifacts.index("- name: Generate CycloneDX SBOM")
    final_verify = artifacts.index("- name: Freeze and stage verified release payload")
    upload = artifacts.index("- name: Upload verified release payload")
    assert sbom < final_verify < upload
    assert artifacts.index("python -m scripts.release_evidence verify", final_verify) < upload
    assert artifacts.index("scripts/verify_distribution_metadata.py", final_verify) < upload
    for binding in (
        "RELEASE_COMMIT: ${{ steps.provenance.outputs.tag_commit }}",
        "RELEASE_TAG: ${{ steps.evidence.outputs.release_tag }}",
        "EVIDENCE_MANIFEST: ${{ steps.evidence.outputs.manifest }}",
        "EVIDENCE_BUNDLE: downloaded-evidence/${{ steps.evidence.outputs.bundle_name }}",
        "PACKAGE_VERSION: ${{ steps.evidence.outputs.package_version }}",
    ):
        assert binding in freeze
    for contract in (
        'test "$(git rev-parse HEAD)" = "${RELEASE_COMMIT}"',
        'test -z "$(git status --porcelain --untracked-files=no)"',
        '--artifact-metadata "artifact-metadata.json"',
        '--expected-version "${PACKAGE_VERSION}"',
    ):
        assert contract in freeze_run
    assert freeze_run.count('test "$(git rev-parse HEAD)" = "${RELEASE_COMMIT}"') == 2
    assert freeze_run.count('test -z "$(git status --porcelain --untracked-files=no)"') == 2


def test_tag_workflow_stages_exact_hashed_five_file_payload() -> None:
    workflow = release_workflow_text()
    artifacts = job_text(workflow, "release-artifacts", next_job="publish-draft")
    freeze = step_text(artifacts, "Freeze and stage verified release payload")
    run = run_text(freeze)

    for contract in (
        'stage_root = Path("release-payload-stage")',
        "os.path.lexists(stage_root)",
        "source_path.lstat()",
        "source_path.is_symlink()",
        "stat.S_ISREG(source_stat.st_mode)",
        "source_path.resolve(strict=True)",
        'stage_root / "dist" / wheel.name',
        'stage_root / "quality-evidence" / "releases" / package_version',
        'stage_root / "downloaded-evidence" / bundle.name',
        "shutil.copyfile(source_path, destination)",
        "source_sha256 = sha256_file(source_path)",
        "destination_sha256 = sha256_file(destination)",
        "if destination_sha256 != source_sha256:",
        "if actual_files != expected_files:",
        "if actual_directories != expected_directories:",
        "f\"wheel_sha256={hashes['wheel']}",
        "f\"sdist_sha256={hashes['sdist']}",
        "f\"sbom_sha256={hashes['sbom']}",
        "f\"manifest_sha256={hashes['manifest']}",
        "f\"bundle_sha256={hashes['bundle']}",
    ):
        assert contract in run

    header, _steps = artifacts.split("    steps:", maxsplit=1)
    for output in (
        "wheel_name: ${{ steps.payload.outputs.wheel_name }}",
        "sdist_name: ${{ steps.payload.outputs.sdist_name }}",
        "wheel_sha256: ${{ steps.payload.outputs.wheel_sha256 }}",
        "sdist_sha256: ${{ steps.payload.outputs.sdist_sha256 }}",
        "sbom_sha256: ${{ steps.payload.outputs.sbom_sha256 }}",
        "manifest_sha256: ${{ steps.payload.outputs.manifest_sha256 }}",
        "bundle_sha256: ${{ steps.payload.outputs.bundle_sha256 }}",
    ):
        assert output in header
    assert "Resolve distribution asset names" not in artifacts


def test_publish_job_verifies_all_five_downloaded_asset_hashes_before_release_api() -> None:
    workflow = release_workflow_text()
    publish = job_text(workflow, "publish-draft")
    identity = step_text(publish, "Validate publication identity")
    release = step_text(publish, "Create or update draft GitHub Release")
    release_run = run_text(release)

    for prefix in ("WHEEL", "SDIST", "SBOM", "MANIFEST", "BUNDLE"):
        assert f"{prefix}_SHA256: ${{{{ needs.release-artifacts.outputs." in identity
        assert f'[[ "${{{prefix}_SHA256}}" =~ ^[0-9a-f]{{64}}$ ]]' in run_text(identity)
        assert f"{prefix}_SHA256: ${{{{ needs.release-artifacts.outputs." in release
    assert "expected_hashes=(" in release_run
    assert 'actual_sha256="$(sha256sum -- "${asset}")"' in release_run
    assert 'test "${actual_sha256}" = "${expected_hashes[${asset_index}]}"' in release_run
    assert 'test "${regular_file_count}" -eq 5' in release_run
    first_release_api = release_run.index(
        'gh api --paginate "repos/${GH_REPO}/releases?per_page=100" --slurp'
    )
    assert release_run.index('test "${actual_sha256}"') < first_release_api


def test_tag_workflow_revalidates_publication_identity_and_remote_tag() -> None:
    workflow = release_workflow_text()
    artifacts = job_text(workflow, "release-artifacts", next_job="publish-draft")
    artifact_header, _artifact_steps = artifacts.split("    steps:", maxsplit=1)
    publish = job_text(workflow, "publish-draft")
    publish_header, _publish_steps = publish.split("    steps:", maxsplit=1)
    identity = step_text(publish, "Validate publication identity")
    identity_run = run_text(identity)

    for output in (
        "artifact_name: ${{ steps.evidence.outputs.release_artifact_name }}",
        "bundle_name: ${{ steps.evidence.outputs.bundle_name }}",
        "evidence_artifact_name: ${{ steps.evidence.outputs.artifact_name }}",
        "manifest_path: ${{ steps.evidence.outputs.manifest }}",
        "package_version: ${{ steps.evidence.outputs.package_version }}",
        "release_tag: ${{ steps.evidence.outputs.release_tag }}",
        "tag_commit: ${{ steps.provenance.outputs.tag_commit }}",
    ):
        assert output in artifact_header
    assert "needs: release-artifacts" in publish_header
    for binding in (
        "EVENT_TAG: ${{ github.ref_name }}",
        "PACKAGE_VERSION: ${{ needs.release-artifacts.outputs.package_version }}",
        "RELEASE_TAG: ${{ needs.release-artifacts.outputs.release_tag }}",
        "TAG_COMMIT: ${{ needs.release-artifacts.outputs.tag_commit }}",
        "EVIDENCE_ARTIFACT_NAME: ${{ needs.release-artifacts.outputs.evidence_artifact_name }}",
        "PAYLOAD_ARTIFACT_NAME: ${{ needs.release-artifacts.outputs.artifact_name }}",
    ):
        assert binding in identity
    for contract in (
        'test "${EVENT_TAG}" = "${RELEASE_TAG}"',
        "-rc\\.([1-9][0-9]*)$",
        'test "${PACKAGE_VERSION}" = "${expected_version}"',
        'test "${PRERELEASE}" = "${expected_prerelease}"',
        'test "${EVIDENCE_ARTIFACT_NAME}" = "graph-rag-c9-${expected_version}-quality-evidence"',
        'test "${BUNDLE_NAME}" = "${EVIDENCE_ARTIFACT_NAME}.zip"',
        'test "${PAYLOAD_ARTIFACT_NAME}" = "graph-rag-c9-${expected_version}-release-assets"',
        'test "${MANIFEST_PATH}" = "quality-evidence/releases/${expected_version}/evidence-manifest.json"',
        '[[ "${TAG_COMMIT}" =~ ^[0-9a-f]{40}$ ]]',
    ):
        assert contract in identity_run

    remote = step_text(publish, "Validate remote tag commit")
    assert "GH_TOKEN: ${{ github.token }}" in remote
    assert "GH_REPO: ${{ github.repository }}" in remote
    assert "EXPECTED_TAG_COMMIT: ${{ needs.release-artifacts.outputs.tag_commit }}" in remote
    assert "gh api \"repos/${GH_REPO}/commits/${RELEASE_TAG}\" --jq '.sha'" in run_text(remote)
    assert 'test "${remote_tag_commit}" = "${EXPECTED_TAG_COMMIT}"' in run_text(remote)

    release_run = run_text(step_text(publish, "Create or update draft GitHub Release"))
    assert 'test "${EVENT_TAG}" = "${RELEASE_TAG}"' in release_run
    assert 'test "${PACKAGE_VERSION}" = "${expected_version}"' in release_run
    assert (
        'test "${PAYLOAD_ARTIFACT_NAME}" = "graph-rag-c9-${expected_version}-release-assets"'
        in release_run
    )


def test_tag_workflow_scopes_write_token_to_gh_only() -> None:
    workflow = release_workflow_text()
    artifacts = job_text(workflow, "release-artifacts", next_job="publish-draft")
    publish = job_text(workflow, "publish-draft")

    for step_name in (
        "Check out tagged commit",
        "Set up Python",
        "Install build dependencies",
        "Generate CycloneDX SBOM",
        "Upload verified release payload",
    ):
        assert "GH_TOKEN:" not in step_text(artifacts, step_name)
    for step_name in (
        "Query selected evidence artifact",
        "Download selected evidence artifact",
    ):
        assert "GH_TOKEN: ${{ github.token }}" in step_text(artifacts, step_name)
    for step_name in (
        "Download current run release payload",
        "Validate remote tag commit",
        "Create or update draft GitHub Release",
    ):
        step = step_text(publish, step_name)
        assert "GH_TOKEN: ${{ github.token }}" in step
        assert "GH_REPO: ${{ github.repository }}" in step
        assert "gh " in run_text(step)
    assert "GH_TOKEN:" not in step_text(publish, "Validate publication identity")
