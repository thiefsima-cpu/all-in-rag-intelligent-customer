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


def test_main_and_production_require_pr_merge_and_checks() -> None:
    for branch in ("main", "production"):
        manifest = _manifest(branch)
        rules = _rules_by_type(manifest)

        assert manifest["name"] == f"Protect {branch}"
        assert manifest["target"] == "branch"
        assert manifest["enforcement"] == "active"
        assert manifest["bypass_actors"] == []
        assert manifest["conditions"]["ref_name"]["include"] == [f"refs/heads/{branch}"]
        assert {"deletion", "non_fast_forward", "pull_request", "required_status_checks"}.issubset(
            rules
        )
        assert "required_linear_history" not in rules

        pull_request = rules["pull_request"]["parameters"]
        assert pull_request["required_approving_review_count"] == 0
        assert pull_request["required_review_thread_resolution"] is True
        assert pull_request["allowed_merge_methods"] == ["merge"]

        checks = rules["required_status_checks"]["parameters"]
        assert checks["strict_required_status_checks_policy"] is True
        assert {item["context"] for item in checks["required_status_checks"]} == REQUIRED_CHECKS


def test_development_allows_direct_push_but_blocks_delete_and_force_push() -> None:
    manifest = _manifest("development")
    rules = _rules_by_type(manifest)

    assert manifest["name"] == "Protect development"
    assert manifest["conditions"]["ref_name"]["include"] == ["refs/heads/development"]
    assert set(rules) == {"deletion", "non_fast_forward"}
