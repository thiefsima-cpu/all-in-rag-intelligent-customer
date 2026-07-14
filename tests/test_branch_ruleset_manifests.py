from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
REQUIRED_CHECKS = {"Branch Flow Policy", "Quality Gates", "Secret Scan", "SBOM"}
LONG_LIVED_BRANCHES = ("development", "production", "main")
STRICT_RULE_TYPES = {
    "deletion",
    "non_fast_forward",
    "pull_request",
    "required_status_checks",
}


def _manifest(branch: str) -> dict:
    path = ROOT / ".github" / "rulesets" / f"{branch}.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _rules_by_type(manifest: dict) -> dict[str, dict]:
    return {rule["type"]: rule for rule in manifest["rules"]}


def _assert_strict_branch_manifest(branch: str) -> None:
    manifest = _manifest(branch)
    rules = _rules_by_type(manifest)

    assert manifest["name"] == f"Protect {branch}"
    assert manifest["target"] == "branch"
    assert manifest["enforcement"] == "active"
    assert manifest["bypass_actors"] == []
    assert manifest["conditions"]["ref_name"]["include"] == [f"refs/heads/{branch}"]
    assert set(rules) == STRICT_RULE_TYPES

    pull_request = rules["pull_request"]["parameters"]
    assert pull_request["required_approving_review_count"] == 0
    assert pull_request["required_review_thread_resolution"] is True
    assert pull_request["allowed_merge_methods"] == ["merge"]

    checks = rules["required_status_checks"]["parameters"]
    assert checks["do_not_enforce_on_create"] is False
    assert checks["strict_required_status_checks_policy"] is True
    assert {item["context"] for item in checks["required_status_checks"]} == REQUIRED_CHECKS


@pytest.mark.parametrize("branch", LONG_LIVED_BRANCHES)
def test_long_lived_branch_requires_pr_merge_and_checks_without_bypass(branch: str) -> None:
    _assert_strict_branch_manifest(branch)


def test_production_history_split_is_retired() -> None:
    path = ROOT / ".github" / "rulesets" / "production-history.json"
    assert not path.exists()
