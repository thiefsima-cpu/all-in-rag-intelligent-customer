from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REQUIRED_CHECKS = {"Branch Flow Policy", "Quality Gates", "Secret Scan", "SBOM"}


def _manifest(branch: str) -> dict:
    path = ROOT / ".github" / "rulesets" / f"{branch}.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _rules_by_type(manifest: dict) -> dict[str, dict]:
    return {rule["type"]: rule for rule in manifest["rules"]}


ADMIN_ALWAYS_BYPASS = [
    {
        "actor_id": 5,
        "actor_type": "RepositoryRole",
        "bypass_mode": "always",
    }
]


def _assert_pr_and_checks(rules: dict[str, dict]) -> None:
    assert set(rules) == {"pull_request", "required_status_checks"}
    pull_request = rules["pull_request"]["parameters"]
    assert pull_request["required_approving_review_count"] == 0
    assert pull_request["required_review_thread_resolution"] is True
    assert pull_request["allowed_merge_methods"] == ["merge"]

    checks = rules["required_status_checks"]["parameters"]
    assert checks["strict_required_status_checks_policy"] is True
    assert {item["context"] for item in checks["required_status_checks"]} == REQUIRED_CHECKS


def test_main_requires_pr_merge_and_checks_without_bypass() -> None:
    manifest = _manifest("main")
    rules = _rules_by_type(manifest)

    assert manifest["name"] == "Protect main"
    assert manifest["bypass_actors"] == []
    assert manifest["conditions"]["ref_name"]["include"] == ["refs/heads/main"]
    assert {"deletion", "non_fast_forward"}.issubset(rules)
    _assert_pr_and_checks(
        {key: value for key, value in rules.items() if key not in {"deletion", "non_fast_forward"}}
    )


def test_production_change_governance_has_admin_always_bypass() -> None:
    manifest = _manifest("production")
    rules = _rules_by_type(manifest)

    assert manifest["name"] == "Protect production"
    assert manifest["target"] == "branch"
    assert manifest["enforcement"] == "active"
    assert manifest["bypass_actors"] == ADMIN_ALWAYS_BYPASS
    assert manifest["conditions"]["ref_name"]["include"] == ["refs/heads/production"]
    _assert_pr_and_checks(rules)


def test_production_history_blocks_delete_and_force_push_without_bypass() -> None:
    manifest = _manifest("production-history")
    rules = _rules_by_type(manifest)

    assert manifest["name"] == "Protect production history"
    assert manifest["target"] == "branch"
    assert manifest["enforcement"] == "active"
    assert manifest["bypass_actors"] == []
    assert manifest["conditions"]["ref_name"]["include"] == ["refs/heads/production"]
    assert set(rules) == {"deletion", "non_fast_forward"}


def test_development_allows_direct_push_but_blocks_delete_and_force_push() -> None:
    manifest = _manifest("development")
    rules = _rules_by_type(manifest)

    assert manifest["name"] == "Protect development"
    assert manifest["conditions"]["ref_name"]["include"] == ["refs/heads/development"]
    assert set(rules) == {"deletion", "non_fast_forward"}
