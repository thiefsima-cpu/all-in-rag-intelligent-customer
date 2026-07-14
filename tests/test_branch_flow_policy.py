from __future__ import annotations

import pytest

from scripts.check_branch_flow import evaluate_branch_flow, main


@pytest.mark.parametrize(
    ("base", "head"),
    [
        ("main", "production"),
        ("main", "hotfix/0.4.1"),
        ("main", "codex/sync-production-to-main"),
        ("production", "development"),
        ("production", "main"),
        ("production", "codex/sync-main-to-production"),
        ("development", "feature/query-cache"),
        ("development", "fix/timeout"),
        ("development", "codex/refactor-runtime"),
        ("development", "dependabot/pip/fastapi-0.139.0"),
        ("development", "production"),
    ],
)
def test_allowed_branch_flows(base: str, head: str) -> None:
    decision = evaluate_branch_flow(base, head)
    assert decision.allowed is True
    assert decision.message.startswith("allowed:")


@pytest.mark.parametrize(
    ("base", "head"),
    [
        ("main", "development"),
        ("main", "feature/direct-to-main"),
        ("production", "feature/direct-to-production"),
        ("production", "hotfix/0.4.1"),
        ("main", "dependabot/pip/fastapi-0.139.0"),
        ("main", "codex/feature-direct-to-main"),
        ("production", "codex/feature-direct-to-production"),
    ],
)
def test_rejected_branch_flows(base: str, head: str) -> None:
    decision = evaluate_branch_flow(base, head)
    assert decision.allowed is False
    assert f"{head} -> {base}" in decision.message
    assert "allowed sources" in decision.message


def test_unmanaged_target_is_not_blocked() -> None:
    decision = evaluate_branch_flow("docs-preview", "feature/docs")
    assert decision.allowed is True
    assert decision.message == "allowed: docs-preview is not a governed target"


def test_enforce_mode_returns_nonzero_for_rejected_flow(
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = main(["--base", "main", "--head", "development", "--mode", "enforce"])
    assert exit_code == 1
    assert "development -> main" in capsys.readouterr().out


def test_report_mode_reports_but_does_not_block(capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = main(["--base", "main", "--head", "development", "--mode", "report"])
    assert exit_code == 0
    output = capsys.readouterr().out
    assert "development -> main" in output
    assert "report-only" in output
