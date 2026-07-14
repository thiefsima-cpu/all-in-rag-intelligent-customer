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


def test_ci_targets_all_long_lived_branches() -> None:
    workflow = _read(".github/workflows/ci.yml")

    assert workflow.count("      - development") == 2
    assert workflow.count("      - production") == 2
    assert workflow.count("      - main") == 2


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
    assert "pypa/gh-action-pypi-publish" not in workflow
    assert "id-token: write" not in workflow


def test_agent_config_template_does_not_contain_credentials() -> None:
    gitignore = _read(".gitignore")
    template = json.loads(_read("agent/config.example.json"))

    assert "/agent/config.json" in gitignore.splitlines()
    assert template["kimi"]["api_key"] == ""


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
