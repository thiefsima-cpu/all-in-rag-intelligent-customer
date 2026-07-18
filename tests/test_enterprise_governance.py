from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_ci_workflow_enforces_engineering_and_release_gates() -> None:
    workflow = _read(".github/workflows/ci.yml")

    required_fragments = [
        "python -m ruff check",
        "python -m ruff format --check",
        "python -m mypy --config-file pyproject.toml",
        "python -m pytest",
        "scripts/release_gate.py",
    ]

    for fragment in required_fragments:
        assert fragment in workflow


def test_ci_workflow_enforces_coverage_security_and_sbom_gates() -> None:
    workflow = _read(".github/workflows/ci.yml")

    required_fragments = [
        "--cov=rag_modules",
        "--cov=scripts",
        "--cov-report=xml",
        "diff-cover coverage.xml",
        "python -m pip_audit",
        "gitleaks/gitleaks-action",
        "anchore/sbom-action",
    ]

    for fragment in required_fragments:
        assert fragment in workflow


def test_ci_enforces_package_and_risk_coverage_after_json_report() -> None:
    workflow = _read(".github/workflows/ci.yml")

    assert "--cov-report=json:coverage.json" in workflow
    assert "python scripts/check_coverage_policy.py" in workflow
    assert "python scripts/check_branch_coverage.py" not in workflow
    assert workflow.index("--cov-report=json:coverage.json") < workflow.index(
        "python scripts/check_coverage_policy.py"
    )


def test_project_config_declares_every_risk_module_with_dual_thresholds() -> None:
    pyproject = tomllib.loads(_read("pyproject.toml"))
    expected_risk_rules = [
        {
            "path": "rag_modules/retrieval/fusion.py",
            "combined_fail_under": 85,
            "branch_fail_under": 80,
        },
        {
            "path": "rag_modules/retrieval/adapters/constraint_retriever.py",
            "combined_fail_under": 85,
            "branch_fail_under": 80,
        },
        {
            "path": "rag_modules/retrieval/keyword_service.py",
            "combined_fail_under": 85,
            "branch_fail_under": 80,
        },
        {
            "path": "rag_modules/retrieval/adapters/bm25_retriever.py",
            "combined_fail_under": 85,
            "branch_fail_under": 80,
        },
        {
            "path": "rag_modules/retrieval/hybrid_driver_service.py",
            "combined_fail_under": 85,
            "branch_fail_under": 80,
        },
        {
            "path": "rag_modules/infra/milvus/schema.py",
            "combined_fail_under": 85,
            "branch_fail_under": 80,
        },
        {
            "path": "rag_modules/infra/milvus/client.py",
            "combined_fail_under": 85,
            "branch_fail_under": 80,
        },
        {
            "path": "rag_modules/app/composition/build_runtime_executor.py",
            "combined_fail_under": 85,
            "branch_fail_under": 80,
        },
        {
            "path": "rag_modules/runtime/build_jobs/locks.py",
            "combined_fail_under": 85,
            "branch_fail_under": 80,
        },
    ]
    coverage_policy = pyproject["tool"]["graph_rag"]["coverage"]

    assert pyproject["tool"]["coverage"]["report"]["fail_under"] == 75
    assert coverage_policy == {
        "package": {"path": "rag_modules", "branch_fail_under": 70},
        "risk_modules": expected_risk_rules,
    }


def test_readme_local_gate_chain_names_coverage_policy_between_pytest_and_release() -> None:
    readme = _read("README.md")
    before_policy_details = readme[: readme.index("The full suite writes")]
    chain = before_policy_details[before_policy_details.rindex("`pre-commit run --all-files`") :]

    pytest_position = chain.index("`python -m pytest -q`")
    coverage_step_position = chain.index("`coverage_policy`")
    coverage_position = chain.index("`python scripts/check_coverage_policy.py`")
    release_position = chain.index("`python scripts/release_gate.py`")

    assert pytest_position < coverage_step_position < coverage_position < release_position


def test_ci_targets_all_long_lived_branches() -> None:
    workflow = _read(".github/workflows/ci.yml")

    assert workflow.count("      - development") == 2
    assert workflow.count("      - production") == 2
    assert workflow.count("      - main") == 2


def test_dependabot_targets_development_for_all_ecosystems() -> None:
    dependabot = _read(".github/dependabot.yml")

    assert dependabot.count('target-branch: "development"') == 2
    assert 'package-ecosystem: "pip"' in dependabot
    assert 'package-ecosystem: "github-actions"' in dependabot


def test_workflows_use_node24_compatible_action_majors() -> None:
    ci = _read(".github/workflows/ci.yml")
    release = _read(".github/workflows/release.yml")
    evidence = _read(".github/workflows/release-evidence.yml")
    workflows = ci + release + evidence

    assert evidence.count("actions/checkout@v7") == 2
    assert evidence.count("actions/setup-python@v6") == 2
    assert evidence.count("actions/upload-artifact@v7") == 2

    assert ci.count("actions/checkout@v7") == 4
    assert release.count("actions/checkout@v7") == 1
    assert ci.count("actions/setup-python@v6") == 2
    assert release.count("actions/setup-python@v6") == 1
    assert ci.count("actions/upload-artifact@v7") == 1
    assert release.count("actions/upload-artifact@v7") == 1
    assert ci.count("gitleaks/gitleaks-action@v3") == 1

    for retired_action in (
        "actions/checkout@v4",
        "actions/setup-python@v5",
        "actions/upload-artifact@v4",
        "gitleaks/gitleaks-action@v2",
    ):
        assert retired_action not in workflows


def test_release_evidence_workflow_is_manual_and_environment_scoped() -> None:
    workflow = _read(".github/workflows/release-evidence.yml")

    assert "workflow_dispatch:" in workflow
    assert "environment: release-quality" in workflow
    assert "operation:" in workflow
    assert "capture" in workflow
    assert "verify" in workflow
    assert "actions/upload-artifact@v7" in workflow


def test_release_quality_evidence_is_documented_as_machine_traceable() -> None:
    environment = _read(".env.example")
    evidence_readme = _read("quality-evidence/README.md")
    live_quality = _read("docs/live_quality_gate.md")
    release_process = _read("docs/release_process.md")
    documentation = "\n".join((environment, evidence_readme, live_quality, release_process))
    normalized_live_quality = " ".join(live_quality.split()).lower()
    normalized_release_process = " ".join(release_process.split())

    assert "quality-evidence/releases/<package-version>/evidence-manifest.json" in evidence_readme
    assert "20260708-203513" in evidence_readme
    assert "historical failed attempt" in evidence_readme.lower()
    assert "graph-rag-release-evidence capture --help" in live_quality
    assert "graph-rag-release-evidence finalize --help" in live_quality
    assert "graph-rag-release-evidence verify --help" in live_quality
    assert "evaluated_commit" in live_quality
    assert "case_count=0" in documentation
    assert (
        "RELEASE_EVIDENCE_ARTIFACT_MANIFEST_PATH="
        "/srv/graph-rag/release-evidence/artifact_manifest.json"
    ) in environment
    assert "absolute" in normalized_live_quality
    assert "outside `GITHUB_WORKSPACE`" in live_quality
    assert "self-hosted Linux" in live_quality
    assert "hosted capture is rejected" in normalized_live_quality
    assert "verify mode may run on a hosted runner" in normalized_live_quality
    assert "pre-tag" in release_process.lower()
    assert "complete quality evidence ZIP" in release_process
    assert "draft GitHub Release" in normalized_release_process
    assert "wheel, sdist, SBOM, compact manifest, and complete quality evidence ZIP" in (
        normalized_release_process
    )


def test_ci_exposes_stable_branch_flow_check_in_enforce_mode() -> None:
    workflow = _read(".github/workflows/ci.yml")

    assert "name: Branch Flow Policy" in workflow
    assert "python scripts/check_branch_flow.py" in workflow
    assert "github.base_ref" in workflow
    assert "github.head_ref" in workflow
    assert "--mode enforce" in workflow
    assert "--mode report" not in workflow


def test_codeowners_protect_public_contracts_and_quality_corpus() -> None:
    owners = _read(".github/CODEOWNERS")

    required_rules = [
        "* @thiefsima-cpu",
        "/rag_modules/interfaces/api/ @thiefsima-cpu",
        "/rag_modules/contracts/ @thiefsima-cpu",
        "/rag_modules/public_surface_manifest.py @thiefsima-cpu",
        "/tests/fixtures/ @thiefsima-cpu",
        "/eval/ @thiefsima-cpu",
        "/.github/workflows/ @thiefsima-cpu",
    ]

    for rule in required_rules:
        assert rule in owners


def test_security_changelog_and_release_process_are_documented() -> None:
    security = _read("SECURITY.md")
    changelog = _read("CHANGELOG.md")
    release_process = _read("docs/release_process.md")

    assert "受支持版本" in security
    assert "漏洞报告" in security
    assert "未发布" in changelog
    assert "Keep a Changelog" in changelog
    assert "Version bump" in release_process
    assert "CHANGELOG.md" in release_process
    assert "SBOM" in release_process


def test_historical_release_candidate_metadata_is_consistent() -> None:
    changelog = _read("CHANGELOG.md")
    release_process = _read("docs/release_process.md")

    assert "## 0.3.0rc1 - 2026-07-11" in changelog
    assert "`0.3.0rc1`" in release_process
    assert "`v0.3.0-rc.1`" in release_process
    assert "historical exception" in release_process.lower()


def test_project_version_uses_supported_pep440_shape() -> None:
    pyproject = tomllib.loads(_read("pyproject.toml"))
    version = pyproject["project"]["version"]

    assert re.fullmatch(r"\d+\.\d+\.\d+(?:rc\d+|\.dev\d+)?", version)


def test_branch_governance_documents_promotion_and_synchronization() -> None:
    governance = _read("docs/branch_governance.md")

    assert "development -> production -> main" in governance
    assert "merge commit" in governance
    assert "main -> production" in governance
    assert "production -> development" in governance
    assert "v0.4.0-rc.1" in governance
    assert "v0.4.0" in governance
    assert "previous final tag" in governance


def test_long_lived_branches_are_pr_only_without_bypass() -> None:
    governance = _read("docs/branch_governance.md")
    release_process = _read("docs/release_process.md")
    current_policy = governance + release_process
    normalized_policy = " ".join(current_policy.split())

    for forbidden in (
        "Direct Production Changes",
        "Production Direct-Push Exception",
        "direct fast-forward push",
        "administrator bypass",
        "Development permits direct push",
    ):
        assert forbidden not in normalized_policy

    for required in (
        "development -> production -> main",
        "pull requests",
        "zero approving reviews",
        "Branch Flow Policy",
        "Quality Gates",
        "Secret Scan",
        "SBOM",
        "hotfix/",
        "main -> production -> development",
        "never force-push",
    ):
        assert required in normalized_policy


def test_release_workflow_validates_and_archives_without_pypi_publish() -> None:
    workflow = _read(".github/workflows/release.yml")

    assert "tags:" in workflow
    assert '"v*"' in workflow
    assert "scripts/validate_release_tag.py" in workflow
    assert "python -m build --sdist --wheel" in workflow
    assert "scripts/verify_distribution_metadata.py" in workflow
    assert "anchore/sbom-action" in workflow
    assert "actions/upload-artifact" in workflow
    assert "scripts.release_evidence verify" in workflow
    assert "gh release create" in workflow
    assert "--draft" in workflow
    assert "--verify-tag" in workflow
    assert "contents: write" in workflow
    assert "actions: read" in workflow
    assert "pypa/gh-action-pypi-publish" not in workflow
    assert "id-token: write" not in workflow


def test_agent_config_template_does_not_contain_credentials() -> None:
    gitignore = _read(".gitignore")
    template = json.loads(_read("agent/config.example.json"))

    assert "/agent/config.json" in gitignore.splitlines()
    assert template["kimi"]["api_key"] == ""


def test_generated_repository_metadata_is_ignored() -> None:
    ignored_paths = set(_read(".gitignore").splitlines())

    assert {
        ".pytest_*/",
        "*.egg-info/",
        "/.superpowers/",
    } <= ignored_paths


def test_pyproject_declares_ci_quality_tooling() -> None:
    pyproject = _read("pyproject.toml")

    required_fragments = [
        '"pytest-cov',
        '"diff-cover',
        '"pip-audit',
        "[tool.coverage.run]",
        "[tool.coverage.report]",
        "fail_under = ",
    ]

    for fragment in required_fragments:
        assert fragment in pyproject
