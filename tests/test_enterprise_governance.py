from __future__ import annotations

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

    assert "Supported Versions" in security
    assert "Reporting a Vulnerability" in security
    assert "Unreleased" in changelog
    assert "Keep a Changelog" in changelog
    assert "Version bump" in release_process
    assert "CHANGELOG.md" in release_process
    assert "SBOM" in release_process


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
