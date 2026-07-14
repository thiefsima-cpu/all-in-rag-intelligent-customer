# Strict Long-Lived Branch Protection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `development`, `production`, and `main` pull-request-only with identical strict
history protection and required checks, then synchronize the governance change across all three
branches without promoting development-only application changes.

**Architecture:** Keep one active ruleset per long-lived branch and keep branch-specific source
policy in `scripts/check_branch_flow.py`. Implement the repository contract on a hotfix branch from
`origin/main`, promote it through `main -> production -> development`, and change remote rulesets
only after the matching tracked manifest has reached the relevant long-lived branch.

**Tech Stack:** Python 3.11, pytest, GitHub Actions, GitHub repository rulesets REST API, GitHub
CLI, Git, PowerShell, JSON, Markdown.

**Status:** Approved for execution

## Global Constraints

- Use Python `>=3.11,<3.12`.
- Work in the main checkout on `hotfix/strict-long-lived-branch-protection`; do not create a
  `.worktrees` checkout.
- Do not change application behavior, dependencies, package versions, release tags, or deployment
  targets.
- Do not manually edit `requirements.txt` or `requirements-dev.txt`.
- Never directly push, force-push, delete, or reset `development`, `production`, or `main`.
- Keep `Protect release tags v*` unchanged.
- Require exactly `Branch Flow Policy`, `Quality Gates`, `Secret Scan`, and `SBOM` on every
  long-lived branch.
- Keep zero required approvals, require resolved review conversations, and allow merge commits
  only.
- Do not delete `Protect production history` until consolidated production deletion and
  non-fast-forward protection is active and verified.
- Keep `.github/workflows/ci.yml` and `scripts/check_branch_flow.py` unchanged unless the focused
  tests expose a policy mismatch.
- Treat `python scripts/local_gate.py` plus green GitHub checks as required evidence, not optional
  diagnostics.

---

### Task 1: Make the tracked ruleset manifests strict through a red-green test cycle

**Files:**
- Modify: `tests/test_branch_ruleset_manifests.py`
- Modify: `.github/rulesets/development.json`
- Modify: `.github/rulesets/production.json`
- Delete: `.github/rulesets/production-history.json`
- Reference: `.github/rulesets/main.json`

**Interfaces:**
- Consumes: GitHub repository-ruleset manifest shape and the four CI job names.
- Produces: one strict tracked manifest for each of `development`, `production`, and `main`, with
  no tracked production-history split.

- [ ] **Step 1: Replace policy-specific manifest tests with one strict long-lived-branch contract**

Add `import pytest`, delete `ADMIN_ALWAYS_BYPASS`, and replace the four existing tests with:

```python
LONG_LIVED_BRANCHES = ("development", "production", "main")
STRICT_RULE_TYPES = {
    "deletion",
    "non_fast_forward",
    "pull_request",
    "required_status_checks",
}


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
```

- [ ] **Step 2: Run the manifest test and verify the expected red state**

Run:

```powershell
python -m pytest tests/test_branch_ruleset_manifests.py -q
```

Expected: failures show that `development` lacks pull-request/check rules, `production` has an
administrator bypass and lacks history rules, and `production-history.json` still exists.

- [ ] **Step 3: Replace the development manifest with the strict target payload**

Set `.github/rulesets/development.json` to:

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

- [ ] **Step 4: Consolidate production into one strict target payload**

Set `.github/rulesets/production.json` to the same shape as the development payload, changing
only the ruleset name and included ref to `Protect production` and `refs/heads/production`.
Delete `.github/rulesets/production-history.json` with `apply_patch` after the deletion and
non-fast-forward entries are present in `production.json`.

- [ ] **Step 5: Run the manifest test and verify the green state**

Run:

```powershell
python -m pytest tests/test_branch_ruleset_manifests.py -q
```

Expected: `4 passed` because the parameterized strict test covers three branches and the fourth
test proves the production-history manifest is absent.

- [ ] **Step 6: Commit the tracked ruleset contract**

```powershell
git add tests/test_branch_ruleset_manifests.py `
  .github/rulesets/development.json `
  .github/rulesets/production.json `
  .github/rulesets/production-history.json
git diff --cached --check
git commit -m "chore: require PRs on long-lived branches"
```

Expected: the commit contains only the manifest test, the two modified manifests, and the deleted
production-history manifest.

---

### Task 2: Replace direct-push documentation with a tested PR-only operating contract

**Files:**
- Modify: `tests/test_enterprise_governance.py`
- Modify: `docs/branch_governance.md`
- Modify: `docs/release_process.md`
- Reference: `docs/superpowers/specs/2026-07-14-strict-long-lived-branch-protection-design.md`

**Interfaces:**
- Consumes: the strict manifest policy from Task 1 and existing branch-flow directions.
- Produces: current operating documentation that contains no development or production direct-push
  exception and documents the checked hotfix synchronization path.

- [ ] **Step 1: Replace the direct-production documentation test with a PR-only contract**

Replace `test_production_direct_push_requires_ci_and_development_back_sync` with:

```python
def test_long_lived_branches_are_pr_only_without_bypass() -> None:
    governance = _read("docs/branch_governance.md")
    release_process = _read("docs/release_process.md")
    current_policy = governance + release_process

    for forbidden in (
        "Direct Production Changes",
        "Production Direct-Push Exception",
        "direct fast-forward push",
        "administrator bypass",
        "Development permits direct push",
    ):
        assert forbidden not in current_policy

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
        assert required in current_policy
```

- [ ] **Step 2: Run the documentation contract and verify the expected red state**

Run:

```powershell
python -m pytest tests/test_enterprise_governance.py::test_long_lived_branches_are_pr_only_without_bypass -q
```

Expected: FAIL because the current governance and release documents still describe development
and production direct pushes and do not list all four required check names in the PR-only policy.

- [ ] **Step 3: Rewrite the current branch-governance operating policy**

Update `docs/branch_governance.md` so its current-policy sections state:

```markdown
- `development`: daily development integration; all changes arrive through checked pull requests.
- `production`: test and release-candidate acceptance; all changes arrive through checked pull requests.
- `main`: formal release baseline; all changes arrive through checked pull requests.

Every long-lived branch requires zero approving reviews for the single-maintainer repository,
resolved review conversations, merge commits, and Branch Flow Policy, Quality Gates, Secret Scan,
and SBOM. All three branches block deletion, force-push, and non-fast-forward updates without a
bypass.
```

Remove the `Direct Production Changes` section. Document hotfix recovery as
`hotfix/* -> main -> production -> development`, with a checked pull request and green required
checks at every arrow. Keep immutable RC/final tag behavior and state that failed checks are
repaired with a new commit or revert, never force-push.

- [ ] **Step 4: Rewrite the current release enforcement policy**

Remove `Production Direct-Push Exception` from `docs/release_process.md`. Replace the required
GitHub enforcement paragraph with:

```markdown
## Required GitHub Enforcement

`development`, `production`, and `main` each require pull requests, resolved review
conversations, merge commits, and the same four checks without bypass: `Branch Flow Policy`,
`Quality Gates`, `Secret Scan`, and `SBOM`. Required approvals remain zero for the
single-maintainer repository. All three branches block deletion and non-fast-forward updates.
```

Add one sentence under security releases stating that urgent fixes use
`hotfix/* -> main -> production -> development`; urgency does not permit direct push.

- [ ] **Step 5: Run the focused documentation and branch-flow tests**

Run:

```powershell
python -m pytest `
  tests/test_enterprise_governance.py::test_branch_governance_documents_promotion_and_synchronization `
  tests/test_enterprise_governance.py::test_long_lived_branches_are_pr_only_without_bypass `
  tests/test_branch_flow_policy.py `
  -q
```

Expected: all selected tests pass, including allowed hotfix and synchronization paths.

- [ ] **Step 6: Commit the PR-only operating documentation**

```powershell
git add tests/test_enterprise_governance.py docs/branch_governance.md docs/release_process.md
git diff --cached --check
git commit -m "docs: require PR-only branch governance"
```

Expected: the commit contains the governance contract test and the two current policy documents.

---

### Task 3: Prove local readiness and record the remote safety baseline

**Files:**
- Verify: all files changed since `origin/main`
- Verify: `.github/workflows/ci.yml`
- Verify: `scripts/check_branch_flow.py`

**Interfaces:**
- Consumes: Tasks 1 and 2 commits plus the approved specification and this plan.
- Produces: complete local gate evidence, clean diff evidence, current branch SHAs, and the remote
  ruleset-name/ID baseline required for safe external changes.

- [ ] **Step 1: Run the complete focused governance slice**

```powershell
python -m pytest `
  tests/test_branch_ruleset_manifests.py `
  tests/test_branch_flow_policy.py `
  tests/test_enterprise_governance.py `
  -q
```

Expected: all governance tests pass.

- [ ] **Step 2: Run formatting and lint checks on touched Python files**

```powershell
python -m ruff check tests/test_branch_ruleset_manifests.py tests/test_enterprise_governance.py
python -m ruff format --check tests/test_branch_ruleset_manifests.py tests/test_enterprise_governance.py
```

Expected: both commands exit `0` without modifying files.

- [ ] **Step 3: Run the authoritative local gate**

```powershell
python scripts/local_gate.py
```

Expected: pre-commit, encoding audit, full pytest, and offline release gate all exit `0`.

- [ ] **Step 4: Refresh refs and record the long-lived-branch baseline**

```powershell
git fetch origin main production development --tags --prune
git rev-parse origin/main
git rev-parse origin/production
git rev-parse origin/development
git update-ref refs/codex-audit/pre-main origin/main
git update-ref refs/codex-audit/pre-production origin/production
git update-ref refs/codex-audit/pre-development origin/development
git rev-list --left-right --count origin/main...HEAD
git status --short --branch
```

Expected: the three printed SHAs are preserved in local audit refs; `HEAD` is ahead of
`origin/main` with no `origin/main`-only commits, and the working tree is clean.

- [ ] **Step 5: Record and validate the five-rule remote baseline**

```powershell
$repoApi = "repos/thiefsima-cpu/all-in-rag-intelligent-customer"
$rulesetsJson = gh api "$repoApi/rulesets"
$parsedRulesets = $rulesetsJson | Out-String | ConvertFrom-Json
$rulesets = @()
foreach ($item in $parsedRulesets) {
  $rulesets += $item
}
$expected = @(
  "Protect main",
  "Protect production",
  "Protect production history",
  "Protect development",
  "Protect release tags v*"
)
foreach ($name in $expected) {
  $match = @($rulesets | Where-Object name -eq $name)
  if ($match.Count -ne 1 -or $match[0].enforcement -ne "active") {
    throw "missing, duplicate, or inactive ruleset: $name"
  }
  "$name=$($match[0].id)"
}
$tag = @($rulesets | Where-Object name -eq "Protect release tags v*")
git config --local codex.audit.preTagRulesetId "$($tag[0].id)"
```

Expected: five unique active ruleset names and IDs are printed. The tag ruleset ID is preserved in
local Git config; no ruleset is changed in this step.

- [ ] **Step 6: Verify scope before publication**

```powershell
git diff --check origin/main...HEAD
git diff --name-status origin/main...HEAD
git log --oneline origin/main..HEAD
```

Expected: only the approved specs, plan, ruleset manifests, governance tests, and current policy
documents are changed. No application, dependency, lock, version, workflow, tag, or deployment
file appears.

---

### Task 4: Publish and merge the checked hotfix into main

**Files:**
- Publish: current `hotfix/strict-long-lived-branch-protection` branch
- Target: remote `main`

**Interfaces:**
- Consumes: clean local-gate evidence from Task 3.
- Produces: a checked merge commit on `main` containing only the governance scope.

- [ ] **Step 1: Confirm GitHub authentication and push only the hotfix branch**

```powershell
gh auth status
git push -u origin hotfix/strict-long-lived-branch-protection
```

Expected: authentication succeeds and only the short-lived hotfix branch is updated.

- [ ] **Step 2: Create the hotfix pull request to main**

```powershell
$repo = "thiefsima-cpu/all-in-rag-intelligent-customer"
$prUrl = gh pr create `
  --repo $repo `
  --base main `
  --head hotfix/strict-long-lived-branch-protection `
  --title "chore: require PR-only long-lived branches" `
  --body "Require PRs and four checks on development, production, and main; remove the production administrator bypass; consolidate production history protection; retain tag protection; verified with python scripts/local_gate.py."
$prUrl
```

Expected: one non-draft pull request targets `main` from the exact hotfix branch.

- [ ] **Step 3: Wait for and verify all four required checks**

```powershell
$pr = gh pr view $prUrl --repo $repo --json number --jq .number
gh pr checks $pr --repo $repo --required --watch --interval 10
$checksJson = gh pr checks $pr --repo $repo --json name,state
$parsedChecks = $checksJson | Out-String | ConvertFrom-Json
$checks = @()
foreach ($item in $parsedChecks) {
  $checks += $item
}
$required = @("Branch Flow Policy", "Quality Gates", "Secret Scan", "SBOM")
foreach ($name in $required) {
  $match = @($checks | Where-Object name -eq $name)
  if ($match.Count -ne 1 -or $match[0].state -ne "SUCCESS") {
    throw "required check is not successful: $name"
  }
}
```

Expected: each required name appears exactly once with state `SUCCESS`.

- [ ] **Step 4: Merge with the verified head SHA**

```powershell
$headSha = gh pr view $pr --repo $repo --json headRefOid --jq .headRefOid
gh pr merge $pr --repo $repo --merge --match-head-commit $headSha
git fetch origin main --prune
git merge-base --is-ancestor $headSha origin/main
```

Expected: the PR is merged with a merge commit and the verified hotfix head is an ancestor of
`origin/main`.

---

### Task 5: Synchronize main to production and consolidate live production protection

**Files:**
- Source branch: remote `main`
- Target branch: remote `production`
- Remote payload: `.github/rulesets/production.json`
- Remote deletion target: `Protect production history`

**Interfaces:**
- Consumes: checked governance merge on `main` and the still-active production-history ruleset.
- Produces: checked `main -> production` merge, one strict live production ruleset, and no remote
  production-history split.

- [ ] **Step 1: Create and merge the main-to-production synchronization PR**

Because required checks use the strict up-to-date policy, use the dedicated target-based sync
branch. Create `codex/sync-main-to-production` from the latest `origin/production`, merge
`origin/main` into it, and run the full local gate before publishing the short-lived branch.

```powershell
$repo = "thiefsima-cpu/all-in-rag-intelligent-customer"
git fetch origin main production --prune
git switch -C codex/sync-main-to-production origin/production
git merge --no-ff origin/main -m "Merge branch 'main' into codex/sync-main-to-production"
python scripts/local_gate.py
git push -u origin codex/sync-main-to-production
$syncUrl = gh pr create `
  --repo $repo `
  --base production `
  --head codex/sync-main-to-production `
  --title "chore: synchronize strict branch protection to production" `
  --body "Synchronize the checked governance-only main merge to production before changing the live production ruleset."
$syncPr = gh pr view $syncUrl --repo $repo --json number --jq .number
gh pr checks $syncPr --repo $repo --required --watch --interval 10
$syncHead = gh pr view $syncPr --repo $repo --json headRefOid --jq .headRefOid
gh pr merge $syncPr --repo $repo --merge --match-head-commit $syncHead
git fetch origin main production --prune
git merge-base --is-ancestor origin/main origin/production
```

Expected: all required checks pass, the PR is merged, and `origin/main` is an ancestor of
`origin/production`.

- [ ] **Step 2: Update Protect production from the tracked consolidated payload**

```powershell
$repoApi = "repos/thiefsima-cpu/all-in-rag-intelligent-customer"
$rulesetsJson = gh api "$repoApi/rulesets"
$parsedRulesets = $rulesetsJson | Out-String | ConvertFrom-Json
$rulesets = @()
foreach ($item in $parsedRulesets) {
  $rulesets += $item
}
$production = @($rulesets | Where-Object name -eq "Protect production")
if ($production.Count -ne 1) { throw "expected exactly one Protect production ruleset" }
gh api `
  --method PUT `
  "$repoApi/rulesets/$($production[0].id)" `
  --input ".github/rulesets/production.json"
```

Expected: the API returns active `Protect production` with an empty bypass list.

- [ ] **Step 3: Verify consolidated production protection before deleting anything**

```powershell
$productionDetailJson = gh api "$repoApi/rulesets/$($production[0].id)"
$productionDetail = $productionDetailJson | Out-String | ConvertFrom-Json
if (@($productionDetail.bypass_actors).Count -ne 0) { throw "production bypass remains" }
$types = @($productionDetail.rules.type | Sort-Object)
if (($types -join ",") -ne "deletion,non_fast_forward,pull_request,required_status_checks") {
  throw "production rules are incomplete: $($types -join ',')"
}
$effectiveJson = gh api "$repoApi/rules/branches/production"
$parsedEffective = $effectiveJson | Out-String | ConvertFrom-Json
$effective = @()
foreach ($item in $parsedEffective) {
  $effective += $item
}
$effectiveTypes = @($effective.type | Sort-Object -Unique)
if (($effectiveTypes -join ",") -ne "deletion,non_fast_forward,pull_request,required_status_checks") {
  throw "effective production rules are incomplete: $($effectiveTypes -join ',')"
}
```

Expected: detailed and effective production rules both contain all four rule types and no bypass.

- [ ] **Step 4: Delete only the now-redundant production-history ruleset**

```powershell
$rulesetsJson = gh api "$repoApi/rulesets"
$parsedRulesets = $rulesetsJson | Out-String | ConvertFrom-Json
$rulesets = @()
foreach ($item in $parsedRulesets) {
  $rulesets += $item
}
$history = @($rulesets | Where-Object name -eq "Protect production history")
if ($history.Count -ne 1) { throw "expected exactly one Protect production history ruleset" }
gh api --method DELETE "$repoApi/rulesets/$($history[0].id)"
$remainingJson = gh api "$repoApi/rulesets"
$parsedRemaining = $remainingJson | Out-String | ConvertFrom-Json
$remaining = @()
foreach ($item in $parsedRemaining) {
  $remaining += $item
}
if (@($remaining | Where-Object name -eq "Protect production history").Count -ne 0) {
  throw "Protect production history still exists"
}
$effectiveJson = gh api "$repoApi/rules/branches/production"
$parsedEffective = $effectiveJson | Out-String | ConvertFrom-Json
$effective = @()
foreach ($item in $parsedEffective) {
  $effective += $item
}
if (@($effective.type | Sort-Object -Unique).Count -ne 4) {
  throw "production lost protection after redundant ruleset deletion"
}
```

Expected: only the redundant ruleset is deleted and production still reports four effective rule
types.

---

### Task 6: Harden development and synchronize production without losing development work

**Files:**
- Remote payload: `.github/rulesets/development.json`
- Source branch: remote `production`
- Target branch: remote `development`

**Interfaces:**
- Consumes: strict checked production state from Task 5 and the pre-rollout development SHA from
  Task 3.
- Produces: strict live development protection and a checked production-to-development merge that
  retains all earlier development commits.

- [ ] **Step 1: Update Protect development from the tracked strict payload**

```powershell
$repoApi = "repos/thiefsima-cpu/all-in-rag-intelligent-customer"
$rulesetsJson = gh api "$repoApi/rulesets"
$parsedRulesets = $rulesetsJson | Out-String | ConvertFrom-Json
$rulesets = @()
foreach ($item in $parsedRulesets) {
  $rulesets += $item
}
$development = @($rulesets | Where-Object name -eq "Protect development")
if ($development.Count -ne 1) { throw "expected exactly one Protect development ruleset" }
gh api `
  --method PUT `
  "$repoApi/rulesets/$($development[0].id)" `
  --input ".github/rulesets/development.json"
$detailJson = gh api "$repoApi/rulesets/$($development[0].id)"
$detail = $detailJson | Out-String | ConvertFrom-Json
if (@($detail.bypass_actors).Count -ne 0) { throw "development bypass exists" }
$types = @($detail.rules.type | Sort-Object)
if (($types -join ",") -ne "deletion,non_fast_forward,pull_request,required_status_checks") {
  throw "development rules are incomplete: $($types -join ',')"
}
```

Expected: development immediately becomes PR-only with no bypass and all four rule types.

- [ ] **Step 2: Create the production-to-development synchronization PR**

```powershell
$repo = "thiefsima-cpu/all-in-rag-intelligent-customer"
git fetch origin production development --prune
git switch -C codex/sync-production-to-development origin/development
git merge --no-ff origin/production `
  -m "Merge branch 'production' into codex/sync-production-to-development"
python scripts/local_gate.py
git push -u origin codex/sync-production-to-development
$syncUrl = gh pr create `
  --repo $repo `
  --base development `
  --head codex/sync-production-to-development `
  --title "chore: synchronize strict branch protection to development" `
  --body "Synchronize the checked governance change from production while preserving all existing development-only commits."
$syncPr = gh pr view $syncUrl --repo $repo --json number --jq .number
gh pr checks $syncPr --repo $repo --required --watch --interval 10
```

Expected: the PR targets development from the dedicated sync branch and all four required checks
succeed.

- [ ] **Step 3: Merge and prove both ancestry directions required by the rollout**

```powershell
$syncHead = gh pr view $syncPr --repo $repo --json headRefOid --jq .headRefOid
gh pr merge $syncPr --repo $repo --merge --match-head-commit $syncHead
git fetch origin production development --prune
git merge-base --is-ancestor origin/production origin/development
$preDevelopment = git rev-parse refs/codex-audit/pre-development
git merge-base --is-ancestor $preDevelopment origin/development
```

Expected: both ancestry commands exit `0`, proving production is synchronized and earlier
development work remains.

If creating the target-based sync branch produces a merge conflict, stop before publishing it,
resolve only the named conflicts, and rerun the full local gate.

---

### Task 7: Audit the final GitHub and Git state against the acceptance criteria

**Files:**
- Verify: `.github/rulesets/main.json`
- Verify: `.github/rulesets/production.json`
- Verify: `.github/rulesets/development.json`
- Verify absence: `.github/rulesets/production-history.json`
- Verify unchanged: protected `v*` tag ruleset

**Interfaces:**
- Consumes: all merged branches and live rulesets from Tasks 4 through 6.
- Produces: final ruleset, CI, ancestry, scope, and clean-workspace evidence.

- [ ] **Step 1: Verify the final active ruleset inventory**

```powershell
$repoApi = "repos/thiefsima-cpu/all-in-rag-intelligent-customer"
$rulesetsJson = gh api "$repoApi/rulesets"
$parsedRulesets = $rulesetsJson | Out-String | ConvertFrom-Json
$rulesets = @()
foreach ($item in $parsedRulesets) {
  $rulesets += $item
}
$expectedNames = @(
  "Protect main",
  "Protect production",
  "Protect development",
  "Protect release tags v*"
)
$activeNames = @($rulesets | Where-Object enforcement -eq "active" | ForEach-Object name | Sort-Object)
if (($activeNames -join "|") -ne (($expectedNames | Sort-Object) -join "|")) {
  throw "unexpected final active rulesets: $($activeNames -join ', ')"
}
```

Expected: exactly four active rulesets remain: three branches and the protected tag ruleset.

- [ ] **Step 2: Verify exact branch rule details and required check names**

```powershell
$requiredChecks = @("Branch Flow Policy", "Quality Gates", "Secret Scan", "SBOM") | Sort-Object
foreach ($branch in @("development", "production", "main")) {
  $summary = @($rulesets | Where-Object name -eq "Protect $branch")
  if ($summary.Count -ne 1) { throw "missing or duplicate branch ruleset: $branch" }
  $detailJson = gh api "$repoApi/rulesets/$($summary[0].id)"
  $detail = $detailJson | Out-String | ConvertFrom-Json
  if (@($detail.bypass_actors).Count -ne 0) { throw "$branch has a bypass actor" }
  $types = @($detail.rules.type | Sort-Object)
  if (($types -join ",") -ne "deletion,non_fast_forward,pull_request,required_status_checks") {
    throw "$branch has unexpected rules: $($types -join ',')"
  }
  $checkRule = @($detail.rules | Where-Object type -eq "required_status_checks")
  $actualChecks = @($checkRule[0].parameters.required_status_checks.context | Sort-Object)
  if (($actualChecks -join "|") -ne ($requiredChecks -join "|")) {
    throw "$branch required checks differ: $($actualChecks -join ',')"
  }
}
```

Expected: every branch has zero bypass actors, four exact rule types, and four exact check names.

- [ ] **Step 3: Verify tag protection identity and branch ancestry**

```powershell
$tag = @($rulesets | Where-Object name -eq "Protect release tags v*")
$preTagRulesetId = [long](git config --local --get codex.audit.preTagRulesetId)
if ($tag.Count -ne 1 -or [long]$tag[0].id -ne $preTagRulesetId) {
  throw "protected tag ruleset identity changed"
}
git fetch origin main production development --tags --prune
git merge-base --is-ancestor origin/main origin/production
git merge-base --is-ancestor origin/production origin/development
$preDevelopment = git rev-parse refs/codex-audit/pre-development
git merge-base --is-ancestor $preDevelopment origin/development
```

Expected: the tag ruleset ID is unchanged and all ancestry checks exit `0`.

- [ ] **Step 4: Verify tracked manifests on all long-lived branches**

```powershell
foreach ($branch in @("main", "production", "development")) {
  foreach ($path in @(
    ".github/rulesets/main.json",
    ".github/rulesets/production.json",
    ".github/rulesets/development.json",
    "docs/branch_governance.md",
    "docs/release_process.md"
  )) {
    git cat-file -e "origin/${branch}:$path"
    if ($LASTEXITCODE -ne 0) { throw "$branch is missing $path" }
  }
  git cat-file -e "origin/${branch}:.github/rulesets/production-history.json" 2>$null
  if ($LASTEXITCODE -eq 0) { throw "$branch still contains production-history.json" }
}
```

Expected: all current governance files exist on all three branches and the retired manifest is
absent everywhere.

- [ ] **Step 5: Return the local checkout to synchronized development**

```powershell
git switch development
git pull --ff-only origin development
git update-ref -d refs/codex-audit/pre-main
git update-ref -d refs/codex-audit/pre-production
git update-ref -d refs/codex-audit/pre-development
git config --local --unset codex.audit.preTagRulesetId
git status --short --branch
```

Expected: local development equals `origin/development` and the working tree is clean. Report the
three rollout PR URLs, merge SHAs, four ruleset IDs, required check results, and ancestry evidence.

## Plan Self-Review

- Task 1 covers strict manifests, no bypass, merge-only PRs, required checks, and retirement of the
  production-history manifest.
- Task 2 covers current policy documentation, emergency hotfix flow, and failure semantics.
- Task 3 covers focused tests, Ruff, the authoritative local gate, scope, and pre-change evidence.
- Tasks 4 through 6 preserve the `main -> production -> development` governance-only path and
  sequence remote changes without a production history-protection gap.
- Task 7 covers the complete design acceptance criteria, including tag-rule identity and retention
  of pre-rollout development history.
