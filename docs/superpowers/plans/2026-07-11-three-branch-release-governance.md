# Three-Branch Release Governance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Establish `development`, `production`, and `main` as governed long-lived branches, add reproducible CI/release controls, and migrate the latest refactor safely to `development` without changing the existing `0.3.0rc1` release.

**Architecture:** Bootstrap repository-side policy and tests on `main`, create clean long-lived branches from that verified baseline, create GitHub rulesets disabled before the first promotion and activate them after verified promotion, then migrate the local refactor as a clean development-only commit. Promotion merge commits are synchronized back to their source branches so all three branches retain shared ancestry.

**Tech Stack:** Python 3.11, pytest, GitHub Actions, GitHub repository rulesets REST API, PowerShell, Git, PEP 440 package versions, setuptools/build, CycloneDX SBOM.

## Global Constraints

- Use Python `>=3.11,<3.12`.
- Do not create `.worktrees`; use the current checkout and ordinary branches only.
- `development` permits direct push; `production` and `main` require pull requests.
- Long-lived branch promotion uses merge commits only; do not squash or rebase.
- After each promotion, synchronize the target merge commit back into the source branch before new work.
- RC tags match `vX.Y.Z-rc.N`, point to `production`, and are GitHub prereleases.
- Final tags match `vX.Y.Z`, point to `main`, and are the only formal deployment source.
- Do not move, delete, or recreate `v0.3.0-rc.1`.
- Do not track or migrate `agent/config.json`; only `agent/config.example.json` is allowed.
- Do not reuse the old candidate history as the base of a new long-lived branch.
- Do not enable automatic PyPI publication.
- Use the connected GitHub Connector for PR creation, check inspection, merge, and PR closure; the local `gh` token is invalid and must not be used.
- Preserve the local refactor commit `6d1995b9bb816a14887ee125e043e702e2f2dedb` until its expected content is verified on `development`.
- Run focused tests first, then `python scripts/local_gate.py` before each promotion PR.

## File Map

- Create `scripts/check_branch_flow.py`: pure branch-flow decision logic and CLI used by CI.
- Create `tests/test_branch_flow_policy.py`: decision table and CLI behavior tests.
- Create `.github/rulesets/main.json`: declarative target state for `Protect main`.
- Create `.github/rulesets/production.json`: declarative target state for `Protect production`.
- Create `.github/rulesets/development.json`: declarative target state for `Protect development`.
- Create `tests/test_branch_ruleset_manifests.py`: validates exact ruleset intent.
- Modify `.github/workflows/ci.yml`: three-branch triggers and `Branch Flow Policy` job.
- Modify `tests/test_enterprise_governance.py`: repository-level workflow and release-policy assertions.
- Create `docs/branch_governance.md`: operator-facing branch and synchronization rules.
- Modify `docs/release_process.md`: RC-from-production and final-from-main lifecycle.
- Modify `README.md`: link the public branch-governance workflow.
- Create `scripts/validate_release_tag.py`: tag grammar, version, and source-branch validation.
- Create `tests/test_release_tag_policy.py`: RC/final tag validation tests.
- Create `scripts/verify_distribution_metadata.py`: wheel and sdist version verification.
- Create `tests/test_distribution_metadata.py`: archive metadata tests.
- Create `.github/workflows/release.yml`: tag validation, build, SBOM, and artifact upload.
- Modify `pyproject.toml`: move `development` to `0.4.0.dev0` only after governance activation.
- Modify `tests/test_dependency_isolation.py`: import-boundary tests extracted from `6d1995b...`.
- Move five feature helpers into their canonical `rag_modules` packages, exactly as recorded in `6d1995b...`.

---

### Task 1: Implement the Branch-Flow Policy with TDD

**Files:**
- Create: `tests/test_branch_flow_policy.py`
- Create: `scripts/check_branch_flow.py`

**Interfaces:**
- Consumes: GitHub `base_ref`, `head_ref`, and `report|enforce` mode.
- Produces: `FlowDecision(allowed: bool, message: str)`, `evaluate_branch_flow(base: str, head: str)`, and CLI exit status `0|1`.

- [ ] **Step 1: Write the failing decision-table and CLI tests**

```python
from __future__ import annotations

import pytest

from scripts.check_branch_flow import evaluate_branch_flow, main


@pytest.mark.parametrize(
    ("base", "head"),
    [
        ("main", "production"),
        ("main", "hotfix/0.4.1"),
        ("production", "development"),
        ("production", "main"),
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


def test_enforce_mode_returns_nonzero_for_rejected_flow(capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = main(["--base", "main", "--head", "development", "--mode", "enforce"])
    assert exit_code == 1
    assert "development -> main" in capsys.readouterr().out


def test_report_mode_reports_but_does_not_block(capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = main(["--base", "main", "--head", "development", "--mode", "report"])
    assert exit_code == 0
    output = capsys.readouterr().out
    assert "development -> main" in output
    assert "report-only" in output
```

- [ ] **Step 2: Run the focused test and verify the expected import failure**

Run:

```powershell
python -m pytest tests/test_branch_flow_policy.py -q
```

Expected: collection fails with `ModuleNotFoundError: No module named 'scripts.check_branch_flow'`.

- [ ] **Step 3: Implement the pure policy and CLI**

```python
"""Validate allowed pull-request flows between governed branches."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from typing import Sequence

GOVERNED_TARGETS = {"development", "production", "main"}
EXACT_ALLOWED_SOURCES: dict[str, set[str]] = {
    "main": {"production"},
    "production": {"development", "main"},
    "development": {"production"},
}
PREFIX_ALLOWED_SOURCES: dict[str, tuple[str, ...]] = {
    "main": ("hotfix/",),
    "production": (),
    "development": ("feature/", "fix/", "hotfix/", "codex/", "dependabot/"),
}


@dataclass(frozen=True)
class FlowDecision:
    allowed: bool
    message: str


def _normalize_ref(ref: str) -> str:
    return ref.removeprefix("refs/heads/").strip()


def evaluate_branch_flow(base: str, head: str) -> FlowDecision:
    normalized_base = _normalize_ref(base)
    normalized_head = _normalize_ref(head)

    if normalized_base not in GOVERNED_TARGETS:
        return FlowDecision(
            allowed=True,
            message=f"allowed: {normalized_base} is not a governed target",
        )

    exact_sources = EXACT_ALLOWED_SOURCES[normalized_base]
    prefix_sources = PREFIX_ALLOWED_SOURCES[normalized_base]
    if normalized_head in exact_sources or normalized_head.startswith(prefix_sources):
        return FlowDecision(
            allowed=True,
            message=f"allowed: {normalized_head} -> {normalized_base}",
        )

    rendered_sources = sorted(exact_sources) + [f"{prefix}*" for prefix in prefix_sources]
    return FlowDecision(
        allowed=False,
        message=(
            f"rejected: {normalized_head} -> {normalized_base}; "
            f"allowed sources: {', '.join(rendered_sources)}"
        ),
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", required=True, help="Pull-request target branch.")
    parser.add_argument("--head", required=True, help="Pull-request source branch.")
    parser.add_argument("--mode", choices=("report", "enforce"), default="enforce")
    args = parser.parse_args(argv)

    decision = evaluate_branch_flow(args.base, args.head)
    suffix = " (report-only)" if args.mode == "report" and not decision.allowed else ""
    print(f"{decision.message}{suffix}")
    if decision.allowed or args.mode == "report":
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run focused tests and formatting**

Run:

```powershell
python -m pytest tests/test_branch_flow_policy.py -q
python -m ruff check scripts/check_branch_flow.py tests/test_branch_flow_policy.py
python -m ruff format --check scripts/check_branch_flow.py tests/test_branch_flow_policy.py
```

Expected: all policy tests pass and both Ruff commands exit `0`.

- [ ] **Step 5: Commit the policy unit**

```powershell
git add scripts/check_branch_flow.py tests/test_branch_flow_policy.py
git commit -m "feat: enforce governed branch flows"
```

---

### Task 2: Add Declarative Branch Ruleset Manifests

**Files:**
- Create: `.github/rulesets/main.json`
- Create: `.github/rulesets/production.json`
- Create: `.github/rulesets/development.json`
- Create: `tests/test_branch_ruleset_manifests.py`

**Interfaces:**
- Consumes: GitHub repository rulesets REST API request schema.
- Produces: three version-controlled active target-state payloads; bootstrap creation temporarily
  overrides enforcement to `disabled`, then activation applies the committed `active` state.

- [ ] **Step 1: Write the failing manifest tests**

```python
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
```

- [ ] **Step 2: Run the focused test and verify missing manifests**

Run:

```powershell
python -m pytest tests/test_branch_ruleset_manifests.py -q
```

Expected: failures report missing `.github/rulesets/*.json` files.

- [ ] **Step 3: Create `.github/rulesets/main.json`**

```json
{
  "name": "Protect main",
  "target": "branch",
  "enforcement": "active",
  "bypass_actors": [],
  "conditions": {
    "ref_name": {
      "include": ["refs/heads/main"],
      "exclude": []
    }
  },
  "rules": [
    {"type": "deletion"},
    {"type": "non_fast_forward"},
    {
      "type": "pull_request",
      "parameters": {
        "dismiss_stale_reviews_on_push": false,
        "require_code_owner_review": false,
        "require_last_push_approval": false,
        "required_approving_review_count": 0,
        "required_review_thread_resolution": true,
        "allowed_merge_methods": ["merge"]
      }
    },
    {
      "type": "required_status_checks",
      "parameters": {
        "do_not_enforce_on_create": false,
        "required_status_checks": [
          {"context": "Branch Flow Policy"},
          {"context": "Quality Gates"},
          {"context": "Secret Scan"},
          {"context": "SBOM"}
        ],
        "strict_required_status_checks_policy": true
      }
    }
  ]
}
```

- [ ] **Step 4: Create `.github/rulesets/production.json`**

```json
{
  "name": "Protect production",
  "target": "branch",
  "enforcement": "active",
  "bypass_actors": [],
  "conditions": {
    "ref_name": {
      "include": ["refs/heads/production"],
      "exclude": []
    }
  },
  "rules": [
    {"type": "deletion"},
    {"type": "non_fast_forward"},
    {
      "type": "pull_request",
      "parameters": {
        "dismiss_stale_reviews_on_push": false,
        "require_code_owner_review": false,
        "require_last_push_approval": false,
        "required_approving_review_count": 0,
        "required_review_thread_resolution": true,
        "allowed_merge_methods": ["merge"]
      }
    },
    {
      "type": "required_status_checks",
      "parameters": {
        "do_not_enforce_on_create": false,
        "required_status_checks": [
          {"context": "Branch Flow Policy"},
          {"context": "Quality Gates"},
          {"context": "Secret Scan"},
          {"context": "SBOM"}
        ],
        "strict_required_status_checks_policy": true
      }
    }
  ]
}
```

- [ ] **Step 5: Create `.github/rulesets/development.json`**

```json
{
  "name": "Protect development",
  "target": "branch",
  "enforcement": "active",
  "bypass_actors": [],
  "conditions": {
    "ref_name": {
      "include": ["refs/heads/development"],
      "exclude": []
    }
  },
  "rules": [
    {"type": "deletion"},
    {"type": "non_fast_forward"}
  ]
}
```

- [ ] **Step 6: Run manifest and governance tests**

```powershell
python -m pytest tests/test_branch_ruleset_manifests.py tests/test_enterprise_governance.py -q
python -m ruff check tests/test_branch_ruleset_manifests.py
```

Expected: all tests pass.

- [ ] **Step 7: Commit the declarative target state**

```powershell
git add .github/rulesets tests/test_branch_ruleset_manifests.py
git commit -m "chore: define long-lived branch rulesets"
```

---

### Task 3: Bootstrap Three-Branch CI and Public Governance Documentation

**Files:**
- Modify: `tests/test_enterprise_governance.py`
- Modify: `.github/workflows/ci.yml`
- Create: `docs/branch_governance.md`
- Modify: `docs/release_process.md`
- Modify: `README.md`

**Interfaces:**
- Consumes: `scripts/check_branch_flow.py` from Task 1 and the four stable job names used by Task 2.
- Produces: CI coverage for all long-lived branches with branch-flow checking initially in `report` mode.

- [ ] **Step 1: Add failing repository-governance assertions**

Add these tests to `tests/test_enterprise_governance.py`:

```python
import re


def test_ci_targets_all_long_lived_branches() -> None:
    workflow = _read(".github/workflows/ci.yml")

    assert workflow.count("      - development") == 2
    assert workflow.count("      - production") == 2
    assert workflow.count("      - main") == 2


def test_ci_exposes_stable_branch_flow_check_in_report_mode() -> None:
    workflow = _read(".github/workflows/ci.yml")

    assert "name: Branch Flow Policy" in workflow
    assert "python scripts/check_branch_flow.py" in workflow
    assert 'github.base_ref' in workflow
    assert 'github.head_ref' in workflow
    assert "--mode report" in workflow


def test_branch_governance_documents_promotion_and_synchronization() -> None:
    governance = _read("docs/branch_governance.md")

    assert "development -> production -> main" in governance
    assert "merge commit" in governance
    assert "fast-forward development" in governance
    assert "main -> production" in governance
    assert "v0.4.0-rc.1" in governance
    assert "v0.4.0" in governance
    assert "previous final tag" in governance
```

Replace the hard-coded current-version assertion in
`test_release_candidate_metadata_is_consistent` with a historical-release assertion:

```python
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
```

- [ ] **Step 2: Run tests and verify they fail on missing three-branch configuration**

```powershell
python -m pytest tests/test_enterprise_governance.py -q
```

Expected: failures mention missing branch filters, `Branch Flow Policy`, and
`docs/branch_governance.md`.

- [ ] **Step 3: Extend `.github/workflows/ci.yml` triggers**

Replace the current `on` block with:

```yaml
on:
  pull_request:
    branches:
      - development
      - production
      - main
  push:
    branches:
      - development
      - production
      - main
  workflow_dispatch:
```

Add this job before `quality-gates`:

```yaml
  branch-flow-policy:
    name: Branch Flow Policy
    if: github.event_name == 'pull_request'
    runs-on: ubuntu-latest
    timeout-minutes: 5

    steps:
      - name: Check out repository
        uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.11"

      - name: Validate branch flow
        run: >
          python scripts/check_branch_flow.py
          --base "${{ github.base_ref }}"
          --head "${{ github.head_ref }}"
          --mode report
```

- [ ] **Step 4: Create `docs/branch_governance.md`**

```markdown
# Branch Governance

GraphRAG C9 uses three long-lived branches:

- `development`: daily development integration; direct push is allowed.
- `production`: accepted release candidates; pull requests are required.
- `main`: formal release baseline; pull requests are required.

Normal promotion is `development -> production -> main`. Each promotion uses a merge commit.

After merging `development` to `production`, fast-forward development to the new production
merge commit before continuing work. After merging `production` to `main`, merge
`main -> production` through a synchronization pull request, then fast-forward development to
the synchronized production tip. These synchronization steps keep all long-lived branches on a
shared ancestry chain.

Release candidates use immutable tags such as `v0.4.0-rc.1` on accepted production commits and
GitHub prereleases. Formal deployments use immutable tags such as `v0.4.0` on main commits.
Branch tips are not deployment identifiers.

Hotfixes start from the latest deployed final tag on main. Merge the fix to main, create the patch
tag, synchronize main to production, and fast-forward development to production.

The repository is single-maintainer. Main and production require pull requests and CI but zero
approving reviews. Development permits direct push but cannot be promoted while CI is red.

## Failure and Rollback

A failed development check is repaired with a new fix or revert commit, never a force-push. A
failed RC remains immutable and is replaced by a new RC number. A failed formal deployment rolls
back by redeploying the previous final tag; main and release tags are not reset. Production defects
use the documented hotfix and synchronization flow.
```

- [ ] **Step 5: Replace the RC and enforcement sections of `docs/release_process.md`**

Use this exact policy text while retaining the existing coverage and security sections:

```markdown
## Branch Promotion

The governed flow is `development -> production -> main`. Promotions use merge commits. After
each promotion, synchronize the target merge commit back into its source branch as documented in
`docs/branch_governance.md`.

## Release Candidates

Release candidates use PEP 440 package versions and protected Git tags. Package version
`0.4.0rc1` maps to `v0.4.0-rc.1`. The RC tag must point to the accepted production tip and the
GitHub Release must be marked as a prerelease.

`0.3.0rc1` and `v0.3.0-rc.1` are a historical exception created before the three-branch model.
They remain immutable and are not recreated.

## Formal Releases

After acceptance, finalize the package version on development, promote it to production, then
promote production to main. A final tag such as `v0.4.0` points to the resulting main commit and
is the only formal deployment source. The final tag is never reused for an RC.

## Required GitHub Enforcement

Main and production require pull requests, merge commits, resolved conversations, and these
checks: `Branch Flow Policy`, `Quality Gates`, `Secret Scan`, and `SBOM`. Required approvals are
zero for the single-maintainer repository. Development permits direct pushes but blocks deletion
and force-push.
```

- [ ] **Step 6: Add the governance link to README**

Add this bullet beside the existing CI and release-process links:

```markdown
- [Branch governance](docs/branch_governance.md) defines development, pre-production, formal
  release, synchronization, and hotfix flows.
```

- [ ] **Step 7: Run focused tests and the encoding audit**

```powershell
python -m pytest tests/test_branch_flow_policy.py tests/test_branch_ruleset_manifests.py tests/test_enterprise_governance.py -q
python scripts/check_encoding.py
```

Expected: tests and encoding audit pass.

- [ ] **Step 8: Commit the bootstrap workflow and docs**

```powershell
git add .github/workflows/ci.yml tests/test_enterprise_governance.py docs/branch_governance.md docs/release_process.md README.md
git commit -m "ci: bootstrap three-branch governance"
```

---

### Task 4: Implement Release-Tag Provenance Validation with TDD

**Files:**
- Create: `tests/test_release_tag_policy.py`
- Create: `scripts/validate_release_tag.py`

**Interfaces:**
- Consumes: tag name, package version, peeled tag commit SHA, and expected branch tip SHA.
- Produces: `ReleaseTag(tag, package_version, branch, prerelease)`, validation errors, and CLI exit status.

- [ ] **Step 1: Write failing RC/final tag tests**

```python
from __future__ import annotations

import pytest

from scripts.validate_release_tag import parse_release_tag, validate_release_tag


def test_parse_release_candidate_tag() -> None:
    parsed = parse_release_tag("v0.4.0-rc.2")
    assert parsed.package_version == "0.4.0rc2"
    assert parsed.branch == "production"
    assert parsed.prerelease is True


def test_parse_final_tag() -> None:
    parsed = parse_release_tag("v0.4.0")
    assert parsed.package_version == "0.4.0"
    assert parsed.branch == "main"
    assert parsed.prerelease is False


@pytest.mark.parametrize(
    "tag",
    ["0.4.0", "v0.4", "v0.4.0rc1", "v0.4.0-rc.0", "v01.4.0", "v0.4.0-beta.1"],
)
def test_reject_invalid_tag_grammar(tag: str) -> None:
    with pytest.raises(ValueError, match="invalid release tag"):
        parse_release_tag(tag)


def test_validate_rejects_package_version_mismatch() -> None:
    errors = validate_release_tag(
        tag="v0.4.0-rc.1",
        package_version="0.4.0rc2",
        tag_commit="a" * 40,
        branch_commit="a" * 40,
    )
    assert errors == ["tag v0.4.0-rc.1 requires package version 0.4.0rc1, got 0.4.0rc2"]


def test_validate_rejects_wrong_branch_tip() -> None:
    errors = validate_release_tag(
        tag="v0.4.0",
        package_version="0.4.0",
        tag_commit="a" * 40,
        branch_commit="b" * 40,
    )
    assert errors == ["tag v0.4.0 must point to current main tip"]


def test_validate_accepts_matching_tag_version_and_branch() -> None:
    errors = validate_release_tag(
        tag="v0.4.0-rc.1",
        package_version="0.4.0rc1",
        tag_commit="a" * 40,
        branch_commit="a" * 40,
    )
    assert errors == []
```

- [ ] **Step 2: Run the test and verify the expected import failure**

```powershell
python -m pytest tests/test_release_tag_policy.py -q
```

Expected: `ModuleNotFoundError: No module named 'scripts.validate_release_tag'`.

- [ ] **Step 3: Implement the validator**

```python
"""Validate protected release tags against package metadata and branch provenance."""

from __future__ import annotations

import argparse
import re
from dataclasses import dataclass
from typing import Sequence

TAG_PATTERN = re.compile(
    r"^v(?P<major>0|[1-9]\d*)\."
    r"(?P<minor>0|[1-9]\d*)\."
    r"(?P<patch>0|[1-9]\d*)"
    r"(?:-rc\.(?P<rc>[1-9]\d*))?$"
)


@dataclass(frozen=True)
class ReleaseTag:
    tag: str
    package_version: str
    branch: str
    prerelease: bool


def parse_release_tag(tag: str) -> ReleaseTag:
    match = TAG_PATTERN.fullmatch(tag)
    if match is None:
        raise ValueError(f"invalid release tag: {tag}")

    core = ".".join(match.group(name) for name in ("major", "minor", "patch"))
    rc = match.group("rc")
    if rc is not None:
        return ReleaseTag(
            tag=tag,
            package_version=f"{core}rc{rc}",
            branch="production",
            prerelease=True,
        )
    return ReleaseTag(tag=tag, package_version=core, branch="main", prerelease=False)


def validate_release_tag(
    *,
    tag: str,
    package_version: str,
    tag_commit: str,
    branch_commit: str,
) -> list[str]:
    parsed = parse_release_tag(tag)
    errors: list[str] = []
    if package_version != parsed.package_version:
        errors.append(
            f"tag {tag} requires package version {parsed.package_version}, got {package_version}"
        )
    if tag_commit != branch_commit:
        errors.append(f"tag {tag} must point to current {parsed.branch} tip")
    return errors


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--package-version", required=True)
    parser.add_argument("--tag-commit", required=True)
    parser.add_argument("--branch-commit", required=True)
    args = parser.parse_args(argv)

    try:
        parsed = parse_release_tag(args.tag)
        errors = validate_release_tag(
            tag=args.tag,
            package_version=args.package_version,
            tag_commit=args.tag_commit,
            branch_commit=args.branch_commit,
        )
    except ValueError as exc:
        print(str(exc))
        return 1

    if errors:
        for error in errors:
            print(error)
        return 1
    release_kind = "prerelease" if parsed.prerelease else "final"
    print(f"validated {release_kind} {parsed.tag} from {parsed.branch}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run focused tests and Ruff**

```powershell
python -m pytest tests/test_release_tag_policy.py -q
python -m ruff check scripts/validate_release_tag.py tests/test_release_tag_policy.py
```

Expected: all tests pass and Ruff exits `0`.

- [ ] **Step 5: Commit the tag-policy unit**

```powershell
git add scripts/validate_release_tag.py tests/test_release_tag_policy.py
git commit -m "feat: validate release tag provenance"
```

---

### Task 5: Verify Distribution Metadata and Add the Tag Build Workflow

**Files:**
- Create: `tests/test_distribution_metadata.py`
- Create: `scripts/verify_distribution_metadata.py`
- Create: `.github/workflows/release.yml`
- Modify: `tests/test_enterprise_governance.py`

**Interfaces:**
- Consumes: a directory containing exactly one wheel and one sdist plus the expected PEP 440 version.
- Produces: verified wheel/sdist metadata and a read-only GitHub Actions artifact containing distributions and SBOM.

- [ ] **Step 1: Write failing archive-metadata tests**

```python
from __future__ import annotations

import io
import tarfile
import zipfile
from pathlib import Path

from scripts.verify_distribution_metadata import verify_distribution_metadata


def _write_wheel(path: Path, version: str) -> None:
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(
            "graph_rag_c9-0.dist-info/METADATA",
            f"Metadata-Version: 2.4\nName: graph-rag-c9\nVersion: {version}\n",
        )


def _write_sdist(path: Path, version: str) -> None:
    payload = f"Metadata-Version: 2.4\nName: graph-rag-c9\nVersion: {version}\n".encode()
    info = tarfile.TarInfo("graph_rag_c9-0/PKG-INFO")
    info.size = len(payload)
    with tarfile.open(path, "w:gz") as archive:
        archive.addfile(info, io.BytesIO(payload))


def test_distribution_metadata_matches_expected_version(tmp_path: Path) -> None:
    _write_wheel(tmp_path / "graph_rag_c9-0-py3-none-any.whl", "0.4.0rc1")
    _write_sdist(tmp_path / "graph_rag_c9-0.tar.gz", "0.4.0rc1")

    assert verify_distribution_metadata(tmp_path, "0.4.0rc1") == []


def test_distribution_metadata_reports_each_mismatch(tmp_path: Path) -> None:
    _write_wheel(tmp_path / "graph_rag_c9-0-py3-none-any.whl", "0.4.0rc2")
    _write_sdist(tmp_path / "graph_rag_c9-0.tar.gz", "0.4.0rc2")

    errors = verify_distribution_metadata(tmp_path, "0.4.0rc1")

    assert errors == [
        "wheel version 0.4.0rc2 does not match 0.4.0rc1",
        "sdist version 0.4.0rc2 does not match 0.4.0rc1",
    ]
```

- [ ] **Step 2: Run the test and verify the expected import failure**

```powershell
python -m pytest tests/test_distribution_metadata.py -q
```

Expected: `ModuleNotFoundError: No module named 'scripts.verify_distribution_metadata'`.

- [ ] **Step 3: Implement the archive verifier**

```python
"""Verify wheel and sdist metadata versions for a release build."""

from __future__ import annotations

import argparse
import tarfile
import zipfile
from email.parser import Parser
from pathlib import Path
from typing import Sequence


def _metadata_version(text: str) -> str:
    version = Parser().parsestr(text).get("Version")
    if not version:
        raise ValueError("distribution metadata has no Version field")
    return version


def _wheel_version(path: Path) -> str:
    with zipfile.ZipFile(path) as archive:
        names = [name for name in archive.namelist() if name.endswith(".dist-info/METADATA")]
        if len(names) != 1:
            raise ValueError(f"wheel must contain one METADATA file, found {len(names)}")
        return _metadata_version(archive.read(names[0]).decode("utf-8"))


def _sdist_version(path: Path) -> str:
    with tarfile.open(path) as archive:
        names = [name for name in archive.getnames() if name.endswith("/PKG-INFO")]
        if len(names) != 1:
            raise ValueError(f"sdist must contain one PKG-INFO file, found {len(names)}")
        extracted = archive.extractfile(names[0])
        if extracted is None:
            raise ValueError("sdist PKG-INFO is unreadable")
        return _metadata_version(extracted.read().decode("utf-8"))


def verify_distribution_metadata(directory: Path, expected_version: str) -> list[str]:
    wheels = sorted(directory.glob("*.whl"))
    sdists = sorted(directory.glob("*.tar.gz"))
    if len(wheels) != 1 or len(sdists) != 1:
        return [
            f"expected one wheel and one sdist, found wheels={len(wheels)} sdists={len(sdists)}"
        ]

    errors: list[str] = []
    wheel_version = _wheel_version(wheels[0])
    sdist_version = _sdist_version(sdists[0])
    if wheel_version != expected_version:
        errors.append(f"wheel version {wheel_version} does not match {expected_version}")
    if sdist_version != expected_version:
        errors.append(f"sdist version {sdist_version} does not match {expected_version}")
    return errors


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--expected-version", required=True)
    args = parser.parse_args(argv)

    try:
        errors = verify_distribution_metadata(args.directory, args.expected_version)
    except (OSError, ValueError, tarfile.TarError, zipfile.BadZipFile) as exc:
        print(str(exc))
        return 1
    if errors:
        for error in errors:
            print(error)
        return 1
    print(f"validated wheel and sdist version {args.expected_version}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Add failing workflow assertions**

Add to `tests/test_enterprise_governance.py`:

```python
def test_release_workflow_validates_and_archives_without_pypi_publish() -> None:
    workflow = _read(".github/workflows/release.yml")

    assert 'tags:' in workflow
    assert '"v*"' in workflow
    assert "scripts/validate_release_tag.py" in workflow
    assert "python -m build --sdist --wheel" in workflow
    assert "scripts/verify_distribution_metadata.py" in workflow
    assert "anchore/sbom-action" in workflow
    assert "actions/upload-artifact" in workflow
    assert "pypa/gh-action-pypi-publish" not in workflow
    assert "id-token: write" not in workflow
```

Run:

```powershell
python -m pytest tests/test_enterprise_governance.py::test_release_workflow_validates_and_archives_without_pypi_publish -q
```

Expected: failure because `.github/workflows/release.yml` does not exist.

- [ ] **Step 5: Create `.github/workflows/release.yml`**

```yaml
name: Release Artifacts

on:
  push:
    tags:
      - "v*"

permissions:
  contents: read

jobs:
  release-artifacts:
    name: Release Artifacts
    runs-on: ubuntu-latest
    timeout-minutes: 30

    steps:
      - name: Check out tagged commit
        uses: actions/checkout@v4
        with:
          fetch-depth: 0

      - name: Fetch governed branches
        run: >
          git fetch origin
          +refs/heads/main:refs/remotes/origin/main
          +refs/heads/production:refs/remotes/origin/production
          --tags

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.11"
          cache: pip
          cache-dependency-path: requirements-dev.txt

      - name: Install build dependencies
        run: python -m pip install -r requirements-dev.txt

      - name: Resolve tag provenance
        id: provenance
        shell: bash
        run: |
          if [[ "${GITHUB_REF_NAME}" == *-rc.* ]]; then
            branch=production
          else
            branch=main
          fi
          echo "branch=${branch}" >> "${GITHUB_OUTPUT}"
          echo "tag_commit=$(git rev-list -n 1 "${GITHUB_REF_NAME}")" >> "${GITHUB_OUTPUT}"
          echo "branch_commit=$(git rev-parse "origin/${branch}")" >> "${GITHUB_OUTPUT}"
          echo "package_version=$(python -c 'import tomllib; print(tomllib.load(open("pyproject.toml", "rb"))["project"]["version"])')" >> "${GITHUB_OUTPUT}"

      - name: Validate tag provenance
        run: >
          python scripts/validate_release_tag.py
          --tag "${{ github.ref_name }}"
          --package-version "${{ steps.provenance.outputs.package_version }}"
          --tag-commit "${{ steps.provenance.outputs.tag_commit }}"
          --branch-commit "${{ steps.provenance.outputs.branch_commit }}"

      - name: Build wheel and sdist
        run: python -m build --sdist --wheel --outdir dist

      - name: Verify distribution metadata
        run: >
          python scripts/verify_distribution_metadata.py
          --directory dist
          --expected-version "${{ steps.provenance.outputs.package_version }}"

      - name: Generate CycloneDX SBOM
        uses: anchore/sbom-action@v0
        with:
          path: .
          format: cyclonedx-json
          output-file: sbom.cdx.json

      - name: Upload release evidence
        uses: actions/upload-artifact@v4
        with:
          name: graph-rag-c9-${{ github.ref_name }}
          path: |
            dist/
            sbom.cdx.json
```

- [ ] **Step 6: Run focused workflow, archive, and governance tests**

```powershell
python -m pytest tests/test_distribution_metadata.py tests/test_release_tag_policy.py tests/test_enterprise_governance.py -q
python -m ruff check scripts/verify_distribution_metadata.py tests/test_distribution_metadata.py
python scripts/check_encoding.py
```

Expected: all checks pass.

- [ ] **Step 7: Commit release validation and artifact generation**

```powershell
git add scripts/verify_distribution_metadata.py tests/test_distribution_metadata.py .github/workflows/release.yml tests/test_enterprise_governance.py
git commit -m "ci: verify protected release artifacts"
```

---

### Task 6: Verify and Merge the Governance Bootstrap, Then Create Clean Branches

**Files:**
- No additional repository file changes.
- External state: governance PR, `production`, `development`, and three disabled rulesets.

**Interfaces:**
- Consumes: all repository-side governance commits from Tasks 1–5.
- Produces: a verified governance baseline on `main`, two clean branches at the same SHA, and
  ruleset IDs in `disabled` mode.

- [ ] **Step 1: Run the complete local gate and verify a clean diff**

```powershell
python scripts/local_gate.py
git status --short
git log --oneline origin/main..HEAD
```

Expected: local gate passes; status is clean; the log contains only the design, plan, and governance commits.

- [ ] **Step 2: Push the governance branch and open a ready PR to main**

```powershell
git push --set-upstream origin codex/three-branch-governance-design
```

Use the GitHub Connector `create_pull_request` operation with:

```json
{
  "repository_full_name": "thiefsima-cpu/all-in-rag-intelligent-customer",
  "base": "main",
  "head": "codex/three-branch-governance-design",
  "title": "chore: establish three-branch release governance",
  "body": "Bootstrap the approved three-branch governance design, tests, CI, ruleset manifests, and release validation workflow.",
  "draft": false
}
```

Expected: GitHub returns a PR URL. The `Branch Flow Policy` check reports the source as rejected but exits successfully because the bootstrap is in report-only mode; all other jobs must pass.

- [ ] **Step 3: Merge the bootstrap with a merge commit**

Use GitHub Connector PR metadata and workflow-job operations until `Branch Flow Policy`,
`Quality Gates`, `Secret Scan`, and `SBOM` all conclude `success`. Read the PR's current
`head_sha`, then call the connector merge operation with `merge_method: "merge"` and
`expected_head_sha` equal to that returned SHA.

Then run:

```powershell
git fetch origin --prune --tags
$mainSha = git rev-parse origin/main
git show --no-patch --format='%H %P %s' $mainSha
```

Expected: the merge commit has two parents and contains the governance files.

- [ ] **Step 4: Create both long-lived branches at exactly the verified main SHA**

```powershell
$mainSha = git rev-parse origin/main
git push origin "${mainSha}:refs/heads/production"
git push origin "${mainSha}:refs/heads/development"
git fetch origin --prune --tags
git rev-parse origin/main origin/production origin/development
```

Expected: all three printed SHAs are identical.

- [x] **Step 5: Create the three rulesets in disabled mode from the committed manifests**

GitHub returned HTTP 422 for `evaluate` because that enforcement level is unavailable on the
repository's plan. The user approved the one-time `disabled` to `active` alternative.

```powershell
$ErrorActionPreference = "Stop"
$credentialInput = "protocol=https`nhost=github.com`n`n"
$credentialOutput = $credentialInput | git credential fill
$passwordLine = $credentialOutput | Where-Object { $_ -like "password=*" } | Select-Object -First 1
if (-not $passwordLine) { throw "GitHub credential unavailable" }
$token = $passwordLine.Substring(9)
$headers = @{
  Accept = "application/vnd.github+json"
  Authorization = "Bearer $token"
  "X-GitHub-Api-Version" = "2022-11-28"
  "User-Agent" = "GraphRAG-C9-Governance"
}
$endpoint = "https://api.github.com/repos/thiefsima-cpu/all-in-rag-intelligent-customer/rulesets"
$existing = @(Invoke-RestMethod -Headers $headers -Uri $endpoint)
foreach ($path in @(
  ".github/rulesets/main.json",
  ".github/rulesets/production.json",
  ".github/rulesets/development.json"
)) {
  $payload = Get-Content -LiteralPath $path -Raw | ConvertFrom-Json
  if ($existing.name -contains $payload.name) { throw "ruleset already exists: $($payload.name)" }
  $payload.enforcement = "disabled"
  $body = $payload | ConvertTo-Json -Depth 20
  $created = Invoke-RestMethod -Method Post -Headers $headers -Uri $endpoint -Body $body -ContentType "application/json"
  [pscustomobject]@{ id = $created.id; name = $created.name; enforcement = $created.enforcement }
}
```

Expected: `Protect main`, `Protect production`, and `Protect development` are returned with unique
IDs and `disabled` enforcement. The existing `Protect release tags v*` remains active.

- [ ] **Step 6: Record the verified baseline**

```powershell
git ls-remote --heads origin main production development
git ls-remote --tags origin "refs/tags/v0.3.0-rc.1*"
```

Expected: all branch refs exist; `v0.3.0-rc.1` is unchanged.

---

### Task 7: Enable Strict Policy, Promote Governance, and Activate Rulesets

**Files:**
- Modify: `.github/workflows/ci.yml`
- Modify: `tests/test_enterprise_governance.py`
- External state: promotion/synchronization PRs and active rulesets.

**Interfaces:**
- Consumes: report-only branch policy and disabled rulesets.
- Produces: strict policy on all branches, synchronized merge ancestry, and active enforcement.

- [ ] **Step 1: Switch to development and write the failing strict-mode assertion**

```powershell
git switch --create development --track origin/development
```

Change the workflow assertion to:

```python
def test_ci_exposes_stable_branch_flow_check_in_enforce_mode() -> None:
    workflow = _read(".github/workflows/ci.yml")

    assert "name: Branch Flow Policy" in workflow
    assert "python scripts/check_branch_flow.py" in workflow
    assert 'github.base_ref' in workflow
    assert 'github.head_ref' in workflow
    assert "--mode enforce" in workflow
    assert "--mode report" not in workflow
```

Run:

```powershell
python -m pytest tests/test_enterprise_governance.py::test_ci_exposes_stable_branch_flow_check_in_enforce_mode -q
```

Expected: failure because the workflow still uses `--mode report`.

- [ ] **Step 2: Switch the workflow to enforce mode and commit only governance files**

Replace `--mode report` with `--mode enforce`, then run:

```powershell
python -m pytest tests/test_branch_flow_policy.py tests/test_enterprise_governance.py -q
git diff --name-only
git add .github/workflows/ci.yml tests/test_enterprise_governance.py
git commit -m "ci: enforce governed branch promotion"
git push origin development
```

Expected: only the two governance files changed; development CI passes.

- [ ] **Step 3: Promote development to production and fast-forward development back to the merge**

Use the GitHub Connector to create a ready PR with base `production`, head `development`, title
`chore: enable strict branch flow`, and body `Promote governance-only enforcement; no business
code.` Wait for all jobs to succeed, reread the head SHA, and merge with method `merge` plus that
exact expected head SHA.

Then run:

```powershell
git fetch origin --prune --tags
git switch development
git merge --ff-only origin/production
git push origin development
```

Expected: the PR uses a merge commit; development and production end at the same SHA after the fast-forward.

- [ ] **Step 4: Promote production to main**

Use the GitHub Connector to create a ready PR with base `main`, head `production`, title
`chore: promote strict branch governance`, and body `Promote the verified governance-only
baseline to main.` Wait for all jobs to succeed and merge with method `merge` plus the current
expected head SHA.

Then run:

```powershell
git fetch origin --prune --tags
```

Expected: all four required check names are green; main receives a merge commit.

- [ ] **Step 5: Synchronize main back to production, then fast-forward development**

Use the GitHub Connector to create a ready PR with base `production`, head `main`, title
`chore: synchronize main merge commit`, and body `Return the main promotion merge commit to
production.` Wait for all jobs to succeed and merge with method `merge` plus the current expected
head SHA.

Then run:

```powershell
git fetch origin --prune --tags
git switch development
git merge --ff-only origin/production
git push origin development
```

Expected: production contains main and development equals production.

- [ ] **Step 6: Patch the three rulesets to active target state**

```powershell
$ErrorActionPreference = "Stop"
$credentialInput = "protocol=https`nhost=github.com`n`n"
$credentialOutput = $credentialInput | git credential fill
$passwordLine = $credentialOutput | Where-Object { $_ -like "password=*" } | Select-Object -First 1
if (-not $passwordLine) { throw "GitHub credential unavailable" }
$token = $passwordLine.Substring(9)
$headers = @{
  Accept = "application/vnd.github+json"
  Authorization = "Bearer $token"
  "X-GitHub-Api-Version" = "2022-11-28"
  "User-Agent" = "GraphRAG-C9-Governance"
}
$endpoint = "https://api.github.com/repos/thiefsima-cpu/all-in-rag-intelligent-customer/rulesets"
$existing = @(Invoke-RestMethod -Headers $headers -Uri $endpoint)
foreach ($path in @(
  ".github/rulesets/main.json",
  ".github/rulesets/production.json",
  ".github/rulesets/development.json"
)) {
  $payload = Get-Content -LiteralPath $path -Raw | ConvertFrom-Json
  $match = @($existing | Where-Object { $_.name -eq $payload.name })
  if ($match.Count -ne 1) { throw "expected one ruleset named $($payload.name)" }
  $body = $payload | ConvertTo-Json -Depth 20
  $updated = Invoke-RestMethod -Method Put -Headers $headers -Uri "$endpoint/$($match[0].id)" -Body $body -ContentType "application/json"
  [pscustomobject]@{ id = $updated.id; name = $updated.name; enforcement = $updated.enforcement }
}
```

Expected: all three branch rulesets report `active`.

- [ ] **Step 7: Exercise one invalid GitHub PR and remove the temporary evidence branch**

```powershell
git switch development
git switch --create codex/branch-flow-negative
git commit --allow-empty -m "test: exercise rejected production flow"
git push --set-upstream origin codex/branch-flow-negative
```

Use the GitHub Connector to create a draft PR with base `production`, head
`codex/branch-flow-negative`, title `test: rejected branch flow`, and body
`Expected Branch Flow Policy failure; do not merge.` Confirm `Branch Flow Policy` concludes
`failure`, then close the PR through the connector without merging.

Clean up the branch:

```powershell
git switch development
git push origin --delete codex/branch-flow-negative
git branch -D codex/branch-flow-negative
```

Expected: `Branch Flow Policy` fails with `codex/branch-flow-negative -> production`; the PR is closed and the temporary branch is deleted. Treat the expected failed check as evidence, not as a release failure.

- [ ] **Step 8: Verify synchronized ancestry before business migration**

```powershell
git fetch origin --prune --tags
git merge-base --is-ancestor origin/main origin/production
git merge-base --is-ancestor origin/production origin/development
git rev-list --left-right --count origin/production...origin/development
```

Expected: both ancestry commands exit `0`; production and development counts are `0 0`.

---

### Task 8: Extract the Latest Refactor to Development Only

**Files:**
- Modify: `tests/test_dependency_isolation.py`
- Delete: `rag_modules/answer_evidence_builder.py`
- Delete: `rag_modules/entity_linker.py`
- Delete: `rag_modules/fusion.py`
- Delete: `rag_modules/parent_doc_enricher.py`
- Delete: `rag_modules/retrieval_cache.py`
- Create: `rag_modules/evidence_processing/answer_builder.py`
- Create: `rag_modules/graph/entity_linker.py`
- Create: `rag_modules/retrieval/cache.py`
- Create: `rag_modules/retrieval/fusion.py`
- Create: `rag_modules/retrieval/parent_doc_enricher.py`
- Modify: `pyproject.toml`
- Modify: `README.md`

**Interfaces:**
- Consumes: local source commit `6d1995b...`, its parent `935fe687...`, and synchronized `development`.
- Produces: a clean refactor commit and a separate `0.4.0.dev0` version commit on development only.

- [ ] **Step 1: Verify the migration source is still available and development is clean**

```powershell
git switch development
git status --short
git cat-file -e "6d1995b9bb816a14887ee125e043e702e2f2dedb^{commit}"
git rev-list --parents -n 1 6d1995b9bb816a14887ee125e043e702e2f2dedb
```

Expected: status is clean; the source exists; its parent is `935fe687817131ffd69baf088b376c4aec27417b`.

- [ ] **Step 2: Apply only the dependency-isolation test change**

```powershell
$testPatch = Join-Path $env:TEMP "graph-rag-c9-refactor-test.patch"
git diff --binary --output=$testPatch 935fe687817131ffd69baf088b376c4aec27417b 6d1995b9bb816a14887ee125e043e702e2f2dedb -- tests/test_dependency_isolation.py
git apply --index $testPatch
Remove-Item -LiteralPath $testPatch
python -m pytest tests/test_dependency_isolation.py -q
```

Expected: the new canonical-ownership tests fail because the old root helpers still exist and the canonical modules do not.

- [ ] **Step 3: Apply only the production module moves**

```powershell
$codePatch = Join-Path $env:TEMP "graph-rag-c9-refactor-code.patch"
git diff --binary --output=$codePatch 935fe687817131ffd69baf088b376c4aec27417b 6d1995b9bb816a14887ee125e043e702e2f2dedb -- rag_modules
git apply --index $codePatch
Remove-Item -LiteralPath $codePatch
python -m pytest tests/test_dependency_isolation.py -q
```

Expected: all dependency-isolation tests pass.

- [ ] **Step 4: Prove the selective extraction excluded credentials and unrelated files**

```powershell
$changed = @(git diff --cached --name-only)
$expected = @(
  "rag_modules/answer_evidence_builder.py",
  "rag_modules/entity_linker.py",
  "rag_modules/evidence_processing/answer_builder.py",
  "rag_modules/fusion.py",
  "rag_modules/graph/entity_linker.py",
  "rag_modules/parent_doc_enricher.py",
  "rag_modules/retrieval/cache.py",
  "rag_modules/retrieval/fusion.py",
  "rag_modules/retrieval/parent_doc_enricher.py",
  "rag_modules/retrieval_cache.py",
  "tests/test_dependency_isolation.py"
)
if (Compare-Object ($changed | Sort-Object) ($expected | Sort-Object)) { throw "unexpected migration paths" }
if ($changed -contains "agent/config.json") { throw "credential config entered migration" }
git diff --cached --check
```

Expected: no output and exit `0`.

- [ ] **Step 5: Run focused public-boundary and import tests**

```powershell
python -m pytest tests/test_dependency_isolation.py tests/test_public_surface_dependency_boundaries.py tests/test_public_api_manifest.py -q
```

Expected: all tests pass.

- [ ] **Step 6: Commit the clean refactor**

```powershell
git commit -m "refactor: move feature helpers to owning packages"
```

Expected: the commit contains exactly the eleven paths verified in Step 4.

- [ ] **Step 7: Move development to `0.4.0.dev0` and update its README version line**

Change:

```toml
version = "0.4.0.dev0"
```

In README's package-version bullet, replace only the current package-version token
`0.3.0rc1` with `0.4.0.dev0`; retain the historical RC references elsewhere.

Run:

```powershell
python -c "import tomllib; assert tomllib.load(open('pyproject.toml','rb'))['project']['version'] == '0.4.0.dev0'"
python -m pytest tests/test_enterprise_governance.py tests/test_entrypoints.py -q
git diff --check
git add pyproject.toml README.md
git commit -m "chore: start 0.4.0 development cycle"
```

Expected: tests pass and the version commit contains only `pyproject.toml` and `README.md`.

- [ ] **Step 8: Run the full development gate, push, and require green CI**

```powershell
python scripts/local_gate.py
git status --short
git push origin development
```

Expected: local gate passes, status is clean, and development's `Quality Gates`, `Secret Scan`, and `SBOM` jobs pass. Do not open a promotion PR for this refactor yet.

---

### Task 9: Retire Obsolete Branches and Perform the Final Governance Audit

**Files:**
- No repository file changes.
- External state: delete obsolete remote/local branch refs after evidence is complete.

**Interfaces:**
- Consumes: active governance, green development CI, and migrated refactor.
- Produces: only the three long-lived branches plus relevant short-lived dependency branches, with the old RC/candidate branch refs retired.

- [ ] **Step 1: Verify the migrated refactor and credential boundary**

```powershell
git fetch origin --prune --tags
git switch development
python -m pytest tests/test_dependency_isolation.py -q
git ls-files agent/config.json
git check-ignore agent/config.json
git diff --name-only origin/production..origin/development -- rag_modules tests/test_dependency_isolation.py pyproject.toml README.md
```

Expected: tests pass; `git ls-files` prints nothing; `git check-ignore` prints `agent/config.json`; the branch diff contains only the expected refactor, test, and development-version files.

- [ ] **Step 2: Verify the formal RC evidence did not move**

```powershell
$main = git rev-parse origin/main
$tag = git rev-list -n 1 v0.3.0-rc.1
git show --no-patch --format='%H %s' v0.3.0-rc.1
git ls-remote --tags origin "refs/tags/v0.3.0-rc.1*"
```

Expected: the tag still peels to `5e6f1ca2170ae06cbffca9de6cc9e41b2288b3c7`; the prerelease remains published and immutable.

- [ ] **Step 3: Verify active ruleset state through the authenticated API**

```powershell
$ErrorActionPreference = "Stop"
$credentialInput = "protocol=https`nhost=github.com`n`n"
$credentialOutput = $credentialInput | git credential fill
$passwordLine = $credentialOutput | Where-Object { $_ -like "password=*" } | Select-Object -First 1
if (-not $passwordLine) { throw "GitHub credential unavailable" }
$token = $passwordLine.Substring(9)
$headers = @{
  Accept = "application/vnd.github+json"
  Authorization = "Bearer $token"
  "X-GitHub-Api-Version" = "2022-11-28"
  "User-Agent" = "GraphRAG-C9-Governance"
}
$endpoint = "https://api.github.com/repos/thiefsima-cpu/all-in-rag-intelligent-customer/rulesets"
$rulesets = @(Invoke-RestMethod -Headers $headers -Uri $endpoint)
$required = @("Protect main", "Protect production", "Protect development", "Protect release tags v*")
foreach ($name in $required) {
  $match = @($rulesets | Where-Object { $_.name -eq $name })
  if ($match.Count -ne 1 -or $match[0].enforcement -ne "active") { throw "inactive or missing ruleset: $name" }
  [pscustomobject]@{ id = $match[0].id; name = $name; enforcement = $match[0].enforcement }
}
```

Expected: exactly four active rulesets are printed.

- [ ] **Step 4: Delete the obsolete remote branches only after Steps 1–3 pass**

```powershell
git push origin --delete codex/retrieval-candidate-source-resilience
git push origin --delete codex/release-0.3.0rc1
git push origin --delete codex/three-branch-governance-design
git ls-remote --heads origin codex/retrieval-candidate-source-resilience codex/release-0.3.0rc1 codex/three-branch-governance-design
```

Expected: deletion succeeds and the final `ls-remote` prints no matching refs. Closed PRs, the tag, and GitHub Release remain.

- [ ] **Step 5: Remove obsolete local refs after preserving the current branch**

```powershell
git switch development
git branch -D codex/release-0.3.0rc1
git branch -D codex/retrieval-candidate-source-resilience
git branch -D codex/three-branch-governance-design
git branch --list
```

Expected: `development`, `production`, and `main` remain; unrelated local task branches are untouched.

- [ ] **Step 6: Run the final local and remote verification**

```powershell
python scripts/local_gate.py
git status --short
git fetch origin --prune --tags
git merge-base --is-ancestor origin/main origin/production
git merge-base --is-ancestor origin/production origin/development
git log --graph --decorate --oneline --all -20
```

Expected:

- local gate passes;
- status is clean;
- both ancestry checks exit `0`;
- development alone contains the `0.4.0.dev0` refactor commits;
- production and main contain only the synchronized governance baseline;
- no existing tag moved; and
- no PyPI publication occurred.

## Operational Release Checklist After Migration

For the first `0.4.0` release cycle:

1. Freeze development and set `0.4.0rc1`.
2. Merge development to production with a merge commit.
3. Fast-forward development to the production merge commit.
4. Require all production CI and acceptance evidence.
5. Create protected `v0.4.0-rc.1` at the production tip.
6. Wait for `Release Artifacts` to validate wheel, sdist, and SBOM.
7. Create a GitHub prerelease and deploy the RC tag to pre-production.
8. For another RC, fix development first and issue a new immutable RC tag.
9. Set `0.4.0`, promote development to production, and synchronize development.
10. Promote production to main and create protected `v0.4.0` at the main tip.
11. Create the formal GitHub Release and deploy only the final tag.
12. Merge main back to production, fast-forward development, then set the next `.dev0` version.

## References

- Design: `docs/superpowers/specs/2026-07-11-three-branch-release-governance-design.md`
- GitHub rulesets API: `https://docs.github.com/en/rest/repos/rules`
- GitHub ruleset behavior: `https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/available-rules-for-rulesets`
- GitHub Python artifact guidance: `https://docs.github.com/en/actions/tutorials/build-and-test-code/python`
