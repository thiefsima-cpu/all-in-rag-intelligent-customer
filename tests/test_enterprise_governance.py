from __future__ import annotations

import json
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


def test_release_candidate_metadata_is_consistent() -> None:
    pyproject = tomllib.loads(_read("pyproject.toml"))
    changelog = _read("CHANGELOG.md")
    release_process = _read("docs/release_process.md")

    assert pyproject["project"]["version"] == "0.3.0rc1"
    assert "## 0.3.0rc1 - 2026-07-11" in changelog
    assert "`0.3.0rc1`" in release_process
    assert "`v0.3.0-rc.1`" in release_process
    assert "prerelease" in release_process.lower()


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
