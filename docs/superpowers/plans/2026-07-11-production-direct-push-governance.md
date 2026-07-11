# Production Direct-Push Governance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Allow the single maintainer to fast-forward push local production commits while retaining unbypassable production history protection and checked pull-request promotions between long-lived branches.

**Architecture:** Split production protection into an unbypassable history ruleset and a pull-request/check ruleset with an administrator `always` bypass. Apply the repository change directly on production without promoting development-only business code, then synchronize it through main and development with checked merge commits.

**Tech Stack:** GitHub repository rulesets REST API, GitHub Actions, GitHub Connector, Git, PowerShell, Python 3.11, pytest.

## Global Constraints

- Execute serially in the current workspace; do not create a Git worktree or `.worktrees` directory.
- Preserve `development` at package version `0.4.0.dev0`; preserve `production` and `main` at `0.3.0rc1` during this governance-only change.
- Do not modify business code, dependencies, lock files, release tags, GitHub Releases, or deployment targets.
- Never print GitHub credentials; retrieve them in memory with `git credential fill` only for the API calls that need them.
- `Protect production history` must be active before the existing production ruleset is weakened.
- No actor may bypass production deletion or non-fast-forward protection.
- `development -> production`, `production -> main`, `main -> production`, and `production -> development` use GitHub pull requests and merge commits.
- A production direct push must be followed by green push CI before any RC tag or synchronization PR.
- Do not move or recreate `v0.3.0-rc.1`; its annotated object remains `9cd402c2588fa3ef7ff2fd3672906a2d11ee3b6c` and its peeled commit remains `5e6f1ca2170ae06cbffca9de6cc9e41b2288b3c7`.

---

### Task 1: Publish the Approved Planning Documents and Prepare Local Production

**Files:**
- Existing: `docs/superpowers/specs/2026-07-11-production-direct-push-governance-design.md`
- Existing: `docs/superpowers/plans/2026-07-11-production-direct-push-governance.md`

**Interfaces:**
- Consumes: local `development`, `origin/development`, and `origin/production`.
- Produces: green development documentation CI and a local `production` branch containing only cherry-picked governance documents ahead of `origin/production`.

- [ ] **Step 1: Verify the starting refs, versions, tag, and clean workspace**

Run:

```powershell
git status --short --branch
git fetch origin --prune --tags
git rev-parse development origin/development origin/production origin/main
git show development:pyproject.toml | Select-String '^version ='
git show origin/production:pyproject.toml | Select-String '^version ='
git show origin/main:pyproject.toml | Select-String '^version ='
git ls-remote --tags origin 'refs/tags/v0.3.0-rc.1*'
```

Expected: the workspace is clean; development is ahead only by the approved design and plan commits; versions are `0.4.0.dev0`, `0.3.0rc1`, and `0.3.0rc1`; both expected tag SHAs are unchanged.

- [ ] **Step 2: Verify the two documentation commits are the only unpublished development commits**

Run:

```powershell
git log --oneline origin/development..development
git diff --name-status origin/development..development
python scripts/check_encoding.py
```

Expected: exactly the design and implementation-plan files are changed; the encoding audit passes.

- [ ] **Step 3: Push development and require its push CI to pass**

Run:

```powershell
git push origin development
$developmentSha = git rev-parse development
$credentialInput = "protocol=https`nhost=github.com`n`n"
$credentialOutput = $credentialInput | git credential fill
$passwordLine = $credentialOutput | Where-Object { $_ -like 'password=*' } | Select-Object -First 1
if (-not $passwordLine) { throw 'GitHub credential unavailable' }
$token = $passwordLine.Substring(9)
$headers = @{
  Accept = 'application/vnd.github+json'
  Authorization = "Bearer $token"
  'X-GitHub-Api-Version' = '2022-11-28'
  'User-Agent' = 'GraphRAG-C9-Governance'
}
$actionsUri = "https://api.github.com/repos/thiefsima-cpu/all-in-rag-intelligent-customer/actions/runs?head_sha=$developmentSha&event=push&per_page=10"
$runResponse = Invoke-RestMethod -Headers $headers -Uri $actionsUri
$pushRuns = @($runResponse.workflow_runs | Where-Object { $_.head_sha -eq $developmentSha -and $_.event -eq 'push' })
if ($pushRuns.Count -ne 1) { throw 'expected exactly one development push workflow' }
Write-Output "$($pushRuns[0].id) $($pushRuns[0].status) $($pushRuns[0].conclusion)"
```

Call the GitHub Connector `fetch_workflow_run_jobs` operation with the returned run ID until all
jobs reach a completed state.

Expected: `Quality Gates`, `Secret Scan`, and `SBOM` conclude `success`; `Branch Flow Policy` concludes `skipped` because this is a push event.

- [ ] **Step 4: Capture the exact documentation commits**

Run:

```powershell
$designPath = 'docs/superpowers/specs/2026-07-11-production-direct-push-governance-design.md'
$planPath = 'docs/superpowers/plans/2026-07-11-production-direct-push-governance.md'
$designCommit = git log -1 --format='%H' development -- $designPath
$planCommit = git log -1 --format='%H' development -- $planPath
git show --no-patch --format='%H %s' $designCommit
git show --no-patch --format='%H %s' $planCommit
```

Expected: each path resolves to one distinct documentation commit.

- [ ] **Step 5: Create or refresh local production without a worktree**

Run:

```powershell
git show-ref --verify --quiet refs/heads/production
if ($LASTEXITCODE -eq 0) {
  git switch production
  git merge --ff-only origin/production
} else {
  git switch --create production --track origin/production
}
```

Expected: local production equals `origin/production` before cherry-picking.

- [ ] **Step 6: Cherry-pick only the approved design and plan documents**

Run:

```powershell
$designPath = 'docs/superpowers/specs/2026-07-11-production-direct-push-governance-design.md'
$planPath = 'docs/superpowers/plans/2026-07-11-production-direct-push-governance.md'
$designCommit = git log -1 --format='%H' development -- $designPath
$planCommit = git log -1 --format='%H' development -- $planPath
git cherry-pick $designCommit
git cherry-pick $planCommit
git diff --name-status origin/production..production
git show production:pyproject.toml | Select-String '^version ='
```

Expected: only the two governance documents differ from remote production and the version remains `0.3.0rc1`.

---

### Task 2: Define the Split Production Ruleset Manifests with TDD

**Files:**
- Create: `.github/rulesets/production-history.json`
- Modify: `.github/rulesets/production.json`
- Modify: `tests/test_branch_ruleset_manifests.py`

**Interfaces:**
- Consumes: GitHub repository-ruleset JSON schema and `REQUIRED_CHECKS` from the existing manifest test.
- Produces: `Protect production history` with no bypass and `Protect production` with exactly one admin `always` bypass.

- [ ] **Step 1: Replace the combined main/production test and add failing split-production tests**

In `tests/test_branch_ruleset_manifests.py`, retain `_manifest` and `_rules_by_type`, then replace `test_main_and_production_require_pr_merge_and_checks` with:

```python
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
```

- [ ] **Step 2: Run the focused test and observe the expected failure**

Run:

```powershell
python -m pytest tests/test_branch_ruleset_manifests.py -q
```

Expected: failure because `production-history.json` does not exist and the old production manifest has no admin bypass and still contains history rules.

- [ ] **Step 3: Create the unbypassable production history manifest**

Create `.github/rulesets/production-history.json` with exactly:

```json
{
  "name": "Protect production history",
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
    {"type": "non_fast_forward"}
  ]
}
```

- [ ] **Step 4: Replace the production change-governance manifest**

Replace `.github/rulesets/production.json` with exactly:

```json
{
  "name": "Protect production",
  "target": "branch",
  "enforcement": "active",
  "bypass_actors": [
    {
      "actor_id": 5,
      "actor_type": "RepositoryRole",
      "bypass_mode": "always"
    }
  ],
  "conditions": {
    "ref_name": {
      "include": ["refs/heads/production"],
      "exclude": []
    }
  },
  "rules": [
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

- [ ] **Step 5: Run the manifest and branch-flow tests**

Run:

```powershell
python -m pytest tests/test_branch_ruleset_manifests.py tests/test_branch_flow_policy.py -q
```

Expected: all tests pass; branch-flow behavior is unchanged.

- [ ] **Step 6: Commit the split manifest contract**

Run:

```powershell
git add .github/rulesets/production.json .github/rulesets/production-history.json tests/test_branch_ruleset_manifests.py
git diff --cached --check
git commit -m "chore: split production governance rulesets"
```

Expected: commit hooks pass and the commit contains only the two manifests and focused test.

---

### Task 3: Document Direct Production Push and Mandatory Back-Synchronization with TDD

**Files:**
- Modify: `tests/test_enterprise_governance.py`
- Modify: `docs/branch_governance.md`
- Modify: `docs/release_process.md`

**Interfaces:**
- Consumes: the split ruleset names and approved operating workflows from the design.
- Produces: executable repository guidance for direct production pushes, PR promotions, back-synchronization, and failure handling.

- [ ] **Step 1: Add a failing documentation contract test**

Append to `tests/test_enterprise_governance.py`:

```python
def test_production_direct_push_requires_ci_and_development_back_sync() -> None:
    governance = _read("docs/branch_governance.md")
    release_process = _read("docs/release_process.md")

    for fragment in (
        "local `production`",
        "direct fast-forward push",
        "production -> development",
        "administrator bypass",
        "Protect production history",
        "never force-push",
    ):
        assert fragment in governance

    for fragment in (
        "production push CI",
        "development -> production",
        "merge commit",
        "Do not create an RC tag",
    ):
        assert fragment in release_process
```

- [ ] **Step 2: Run the test and observe the expected failure**

Run:

```powershell
python -m pytest tests/test_enterprise_governance.py::test_production_direct_push_requires_ci_and_development_back_sync -q
```

Expected: failure on the first missing direct-push fragment.

- [ ] **Step 3: Update the branch governance workflow**

In `docs/branch_governance.md`, replace the opening branch list with:

```markdown
- `development`: daily development integration; local `development` may direct fast-forward push.
- `production`: test and release-candidate acceptance; local `production` may direct fast-forward
  push through the administrator bypass, but must never force-push.
- `main`: formal release baseline; pull requests are required and there is no direct-push bypass.
```

Add this section before `## Failure and Rollback`:

```markdown
## Direct Production Changes

`Protect production history` has no bypass and always blocks deletion and non-fast-forward
updates. The separate `Protect production` change-governance ruleset gives the repository
administrator an `always` bypass so local `production` commits can direct fast-forward push.

Before a direct push, fast-forward local production from the remote, run focused tests and
`python scripts/local_gate.py`, then push. Wait for production push CI to pass. Synchronize every
version-controlled direct production change through a checked `production -> development` pull
request; production-only source-code divergence is not allowed.

Normal `development -> production` promotion still uses a checked pull request and merge commit.
Do not use the administrator bypass for that promotion.
```

Replace the first sentence under `## Failure and Rollback` with:

```markdown
A failed direct production push is repaired with a new fix or revert commit; do not create an RC
tag and never force-push. Synchronize the repair into development only after production push CI
passes.
```

- [ ] **Step 4: Update the release process**

Add after `## Branch Promotion` in `docs/release_process.md`:

```markdown
### Production Direct-Push Exception

The single maintainer may direct fast-forward push a commit created on local `production`.
Production push CI must pass before synchronization or RC tagging. Every such change is merged
back through a `production -> development` pull request. `development -> production` remains a
checked pull request with a merge commit.

Do not create an RC tag when production push CI is pending or failed. Repair or revert with a new
commit; production history is never rewritten.
```

Replace the first paragraph under `## Required GitHub Enforcement` with:

```markdown
Main requires pull requests and all four checks without bypass. Production uses two active
rulesets: `Protect production history` blocks deletion and non-fast-forward updates without
bypass, while `Protect production` requires pull requests and the four checks but grants the
repository administrator an `always` bypass for local production fast-forward pushes. Required
approvals remain zero for the single-maintainer repository.
```

- [ ] **Step 5: Run governance tests**

Run:

```powershell
python -m pytest tests/test_enterprise_governance.py tests/test_branch_ruleset_manifests.py tests/test_branch_flow_policy.py -q
```

Expected: all governance tests pass.

- [ ] **Step 6: Commit the workflow documentation**

Run:

```powershell
git add docs/branch_governance.md docs/release_process.md tests/test_enterprise_governance.py
git diff --cached --check
git commit -m "docs: define production direct-push workflow"
```

Expected: commit hooks pass and no unrelated file is staged.

---

### Task 4: Complete Local Verification Before Changing GitHub Rulesets

**Files:**
- No new repository changes.

**Interfaces:**
- Consumes: local production governance commits from Tasks 1-3.
- Produces: a verified, clean local production tip and recorded remote rollback baseline.

- [ ] **Step 1: Run focused governance verification**

Run:

```powershell
python -m pytest tests/test_branch_ruleset_manifests.py tests/test_branch_flow_policy.py tests/test_enterprise_governance.py -q
```

Expected: all focused tests pass.

- [ ] **Step 2: Run the complete local gate**

Run:

```powershell
python scripts/local_gate.py
```

Expected: pre-commit, encoding audit, full pytest, and the 69-case release gate pass.

- [ ] **Step 3: Verify the production diff is governance-only**

Run:

```powershell
git status --short --branch
git diff --name-status origin/production..production
git diff origin/production..production -- rag_modules pyproject.toml requirements.txt requirements-dev.txt agent/config.json
git show production:pyproject.toml | Select-String '^version ='
```

Expected: status is clean; no business, dependency, credential, or version diff is printed; production remains `0.3.0rc1`.

- [ ] **Step 4: Record the rollback source and immutable tag baseline**

Run:

```powershell
$productionBefore = git rev-parse origin/production
Write-Output $productionBefore
git show origin/production:.github/rulesets/production.json | ConvertFrom-Json | Select-Object name,enforcement
git ls-remote --tags origin 'refs/tags/v0.3.0-rc.1*'
```

Expected: the production SHA is recorded, the old combined ruleset payload is available in memory, and both tag SHAs match the global constraints.

---

### Task 5: Activate the History Ruleset Before Adding the Direct-Push Bypass

**Files:**
- External state: create `Protect production history`; update existing `Protect production`.

**Interfaces:**
- Consumes: the two verified local JSON manifests and existing GitHub credentials.
- Produces: two active production rulesets, with history protection unbypassable and change governance bypassable only by repository admins.

- [ ] **Step 1: Initialize authenticated GitHub API access without printing the credential**

Run Steps 1-5 in one PowerShell session so the authenticated variables remain in memory:

```powershell
$ErrorActionPreference = 'Stop'
$credentialInput = "protocol=https`nhost=github.com`n`n"
$credentialOutput = $credentialInput | git credential fill
$passwordLine = $credentialOutput | Where-Object { $_ -like 'password=*' } | Select-Object -First 1
if (-not $passwordLine) { throw 'GitHub credential unavailable' }
$token = $passwordLine.Substring(9)
$headers = @{
  Accept = 'application/vnd.github+json'
  Authorization = "Bearer $token"
  'X-GitHub-Api-Version' = '2022-11-28'
  'User-Agent' = 'GraphRAG-C9-Governance'
}
$endpoint = 'https://api.github.com/repos/thiefsima-cpu/all-in-rag-intelligent-customer/rulesets'
```

Expected: no token value is written to output.

- [ ] **Step 2: Verify the old production ruleset exists and the history ruleset does not**

Run:

```powershell
$rulesets = Invoke-RestMethod -Headers $headers -Uri $endpoint
$productionMatches = @($rulesets | Where-Object { $_.name -eq 'Protect production' })
$historyMatches = @($rulesets | Where-Object { $_.name -eq 'Protect production history' })
if ($productionMatches.Count -ne 1) { throw 'expected exactly one Protect production ruleset' }
if ($historyMatches.Count -ne 0) { throw 'Protect production history already exists' }
$productionRuleset = $productionMatches[0]
Write-Output "$($productionRuleset.id) $($productionRuleset.name) $($productionRuleset.enforcement)"
```

Expected: exactly one active existing production ruleset is printed and no history ruleset exists.

- [ ] **Step 3: Create the active unbypassable history ruleset first**

Run:

```powershell
$historyBody = Get-Content -LiteralPath '.github/rulesets/production-history.json' -Raw
$historyRuleset = Invoke-RestMethod -Method Post -Headers $headers -Uri $endpoint -Body $historyBody -ContentType 'application/json'
if ($historyRuleset.enforcement -ne 'active') { throw 'history ruleset is not active' }
if (@($historyRuleset.bypass_actors).Count -ne 0) { throw 'history ruleset unexpectedly has bypass actors' }
if (@($historyRuleset.rules.type | Sort-Object) -join ',' -ne 'deletion,non_fast_forward') {
  throw 'history ruleset has unexpected rules'
}
Write-Output "$($historyRuleset.id) $($historyRuleset.name) $($historyRuleset.enforcement)"
```

Expected: `Protect production history active` is returned before any existing rule is weakened.

- [ ] **Step 4: Update only the existing production change-governance ruleset**

Run:

```powershell
$governanceBody = Get-Content -LiteralPath '.github/rulesets/production.json' -Raw
$governanceRuleset = Invoke-RestMethod -Method Put -Headers $headers -Uri "$endpoint/$($productionRuleset.id)" -Body $governanceBody -ContentType 'application/json'
if ($governanceRuleset.enforcement -ne 'active') { throw 'production governance is not active' }
Write-Output "$($governanceRuleset.id) $($governanceRuleset.name) $($governanceRuleset.enforcement)"
```

Expected: the existing ruleset ID is retained and enforcement remains active.

- [ ] **Step 5: Read both rulesets back and verify exact safety boundaries**

Run:

```powershell
$history = Invoke-RestMethod -Headers $headers -Uri "$endpoint/$($historyRuleset.id)"
$governance = Invoke-RestMethod -Headers $headers -Uri "$endpoint/$($productionRuleset.id)"

if (@($history.bypass_actors).Count -ne 0) { throw 'history bypass must remain empty' }
if (@($history.rules.type | Sort-Object) -join ',' -ne 'deletion,non_fast_forward') {
  throw 'history rules changed unexpectedly'
}

$expectedBypass = @($governance.bypass_actors | Where-Object {
  $_.actor_id -eq 5 -and $_.actor_type -eq 'RepositoryRole' -and $_.bypass_mode -eq 'always'
})
if ($expectedBypass.Count -ne 1 -or @($governance.bypass_actors).Count -ne 1) {
  throw 'production governance bypass is not exactly repository admin always'
}
if (@($governance.rules.type | Sort-Object) -join ',' -ne 'pull_request,required_status_checks') {
  throw 'production governance rules changed unexpectedly'
}
Write-Output 'production ruleset split verified'
```

Expected: verification completes without an exception.

- [ ] **Step 6: Stop safely if any API step failed**

If history creation fails, do not update the existing production ruleset. If the governance update fails, leave the newly active history ruleset in place and restore the old payload with:

```powershell
$oldProductionPayload = git show origin/production:.github/rulesets/production.json
Invoke-RestMethod -Method Put -Headers $headers -Uri "$endpoint/$($productionRuleset.id)" -Body $oldProductionPayload -ContentType 'application/json'
```

Expected: production remains at least as protected as before; do not continue to Task 6 until both intended rulesets verify successfully.

---

### Task 6: Prove Local Production Direct Fast-Forward Push and Audit the Bypass

**Files:**
- External state: fast-forward `origin/production` to the verified local governance tip.

**Interfaces:**
- Consumes: active split production rulesets and verified local production commits.
- Produces: a successful bypassed fast-forward push, green production push CI, and a matching Rule Suite audit record.

- [ ] **Step 1: Recheck fast-forward safety immediately before pushing**

Run:

```powershell
git fetch origin --prune --tags
git merge-base --is-ancestor origin/production production
if ($LASTEXITCODE -ne 0) { throw 'local production is not a fast-forward of origin/production' }
git status --short --branch
git log --oneline origin/production..production
```

Expected: clean local production is strictly ahead of remote production through governance-only commits.

- [ ] **Step 2: Push local production directly**

Run:

```powershell
git push origin production
$productionDirectPushSha = git rev-parse production
Write-Output $productionDirectPushSha
```

Expected: push succeeds without a pull request.

If it is rejected, do not force-push. Because the remote production ref did not move, restore the
old combined governance payload with this exact recovery command and stop:

```powershell
$credentialInput = "protocol=https`nhost=github.com`n`n"
$credentialOutput = $credentialInput | git credential fill
$passwordLine = $credentialOutput | Where-Object { $_ -like 'password=*' } | Select-Object -First 1
if (-not $passwordLine) { throw 'GitHub credential unavailable' }
$token = $passwordLine.Substring(9)
$headers = @{
  Accept = 'application/vnd.github+json'
  Authorization = "Bearer $token"
  'X-GitHub-Api-Version' = '2022-11-28'
  'User-Agent' = 'GraphRAG-C9-Governance'
}
$endpoint = 'https://api.github.com/repos/thiefsima-cpu/all-in-rag-intelligent-customer/rulesets'
$rulesets = Invoke-RestMethod -Headers $headers -Uri $endpoint
$productionMatches = @($rulesets | Where-Object { $_.name -eq 'Protect production' })
if ($productionMatches.Count -ne 1) { throw 'expected exactly one Protect production ruleset' }
$oldProductionPayload = git show origin/production:.github/rulesets/production.json
Invoke-RestMethod -Method Put -Headers $headers -Uri "$endpoint/$($productionMatches[0].id)" -Body $oldProductionPayload -ContentType 'application/json'
```

- [ ] **Step 3: Require production push CI to pass**

Run without printing the credential:

```powershell
$productionDirectPushSha = git rev-parse production
$credentialInput = "protocol=https`nhost=github.com`n`n"
$credentialOutput = $credentialInput | git credential fill
$passwordLine = $credentialOutput | Where-Object { $_ -like 'password=*' } | Select-Object -First 1
if (-not $passwordLine) { throw 'GitHub credential unavailable' }
$token = $passwordLine.Substring(9)
$headers = @{
  Accept = 'application/vnd.github+json'
  Authorization = "Bearer $token"
  'X-GitHub-Api-Version' = '2022-11-28'
  'User-Agent' = 'GraphRAG-C9-Governance'
}
$actionsUri = "https://api.github.com/repos/thiefsima-cpu/all-in-rag-intelligent-customer/actions/runs?head_sha=$productionDirectPushSha&event=push&per_page=10"
$runResponse = Invoke-RestMethod -Headers $headers -Uri $actionsUri
$pushRuns = @($runResponse.workflow_runs | Where-Object { $_.head_sha -eq $productionDirectPushSha -and $_.event -eq 'push' })
if ($pushRuns.Count -ne 1) { throw 'expected exactly one production push workflow' }
Write-Output "$($pushRuns[0].id) $($pushRuns[0].status) $($pushRuns[0].conclusion)"
```

Use the returned run ID with the GitHub Connector workflow-job operation.

Expected: `Quality Gates`, `Secret Scan`, and `SBOM` conclude `success`; `Branch Flow Policy` is `skipped`. If CI fails, add a fix or revert commit on production, rerun the local gate, push normally, and repeat this step; never rewrite history.

- [ ] **Step 4: Verify GitHub recorded a bypass for the direct production push**

Using `$headers` and `$productionDirectPushSha` initialized in Step 3, run:

```powershell
$encodedRef = [uri]::EscapeDataString('refs/heads/production')
$suiteUri = "https://api.github.com/repos/thiefsima-cpu/all-in-rag-intelligent-customer/rulesets/rule-suites?ref=$encodedRef&time_period=day&rule_suite_result=bypass&per_page=100"
$suites = Invoke-RestMethod -Headers $headers -Uri $suiteUri
$matchingSuite = @($suites | Where-Object { $_.after_sha -eq $productionDirectPushSha })
if ($matchingSuite.Count -ne 1) { throw 'direct production bypass audit record not found' }
Write-Output "$($matchingSuite[0].id) $($matchingSuite[0].result) $($matchingSuite[0].after_sha)"
```

Expected: exactly one suite prints `bypass` and the direct-push SHA.

---

### Task 7: Promote the Governance-Only Change from Production to Main

**Files:**
- External state: production-to-main pull request and merge commit.

**Interfaces:**
- Consumes: green production direct-push SHA.
- Produces: a checked main merge commit containing only governance changes and retaining `0.3.0rc1`.

- [ ] **Step 1: Create a ready production-to-main pull request**

Use the GitHub Connector create-pull-request operation with:

```json
{
  "repository_full_name": "thiefsima-cpu/all-in-rag-intelligent-customer",
  "base": "main",
  "head": "production",
  "title": "chore: allow guarded production direct pushes",
  "body": "Split production history protection from PR governance, add an audited administrator direct-push bypass, and document mandatory CI and development back-synchronization. Governance-only; no business or version changes.",
  "draft": false
}
```

Expected: GitHub returns an open, mergeable PR after checks initialize.

- [ ] **Step 2: Wait for all required PR jobs**

Call `fetch_commit_workflow_runs` with the PR `head_sha`, then call
`fetch_workflow_run_jobs` with the returned run ID until all jobs reach a completed state.

Expected: `Branch Flow Policy`, `Quality Gates`, `Secret Scan`, and `SBOM` all conclude `success`; Branch Flow reports `production -> main` allowed.

- [ ] **Step 3: Merge with an expected-head guard and merge commit**

Read current PR metadata immediately before merging. Call the GitHub Connector merge operation
with repository `thiefsima-cpu/all-in-rag-intelligent-customer`, `pr_number` equal to the `number`
returned by Step 1, `merge_method` equal to `merge`, and `expected_head_sha` equal to the current
`head_sha` returned by the metadata read.

Expected: merge succeeds and returns a new main merge SHA.

- [ ] **Step 4: Verify main is a two-parent governance-only merge**

Run:

```powershell
git fetch origin --prune --tags
git show --no-patch --format='%H %P %s' origin/main
git show origin/main:pyproject.toml | Select-String '^version ='
git diff --name-status origin/main^1..origin/main
```

Expected: main has two parents, version remains `0.3.0rc1`, and the diff is governance-only.

---

### Task 8: Synchronize Main Back to Production Through the Normal PR Path

**Files:**
- External state: main-to-production synchronization PR and merge commit.

**Interfaces:**
- Consumes: the new main governance merge commit.
- Produces: production containing main's promotion ancestry without using the direct-push bypass for synchronization.

- [ ] **Step 1: Create the main-to-production synchronization PR**

Use the GitHub Connector with:

```json
{
  "repository_full_name": "thiefsima-cpu/all-in-rag-intelligent-customer",
  "base": "production",
  "head": "main",
  "title": "chore: synchronize production governance ancestry",
  "body": "Synchronize the checked main governance merge commit back into production. Do not use the administrator direct-push bypass for this branch synchronization.",
  "draft": false
}
```

Expected: an open PR with no business-code diff.

- [ ] **Step 2: Wait for all four checks and merge normally**

Call `fetch_commit_workflow_runs` with the PR head SHA, then `fetch_workflow_run_jobs` with the
returned run ID until all four named jobs complete successfully. Read PR metadata again and call
`merge_pull_request` with the PR number, `merge_method: "merge"`, and the returned current
`head_sha` as `expected_head_sha`.

Expected: all checks succeed, Branch Flow reports `main -> production` allowed, and GitHub returns a production merge SHA.

- [ ] **Step 3: Verify main is an ancestor of production**

Run:

```powershell
git fetch origin --prune --tags
git merge-base --is-ancestor origin/main origin/production
if ($LASTEXITCODE -ne 0) { throw 'main is not an ancestor of production' }
git show --no-patch --format='%H %P %s' origin/production
```

Expected: the ancestry check returns zero and production has a two-parent synchronization merge commit.

---

### Task 9: Synchronize Production Governance into Development

**Files:**
- External state: production-to-development synchronization PR and merge commit.

**Interfaces:**
- Consumes: synchronized production and development's existing `0.4.0.dev0` refactor history.
- Produces: development containing the governed production ancestry without losing development-only business commits.

- [ ] **Step 1: Create the production-to-development synchronization PR**

Use the GitHub Connector with:

```json
{
  "repository_full_name": "thiefsima-cpu/all-in-rag-intelligent-customer",
  "base": "development",
  "head": "production",
  "title": "chore: synchronize production direct-push governance",
  "body": "Merge the production governance and main synchronization ancestry back into development while retaining the existing 0.4.0.dev0 refactor.",
  "draft": false
}
```

Expected: GitHub reports a mergeable PR; duplicate design/plan patches are recognized as already present on development.

- [ ] **Step 2: Wait for all four checks and merge with a merge commit**

Call `fetch_commit_workflow_runs` with the PR head SHA, then `fetch_workflow_run_jobs` with the
returned run ID until all four named jobs complete successfully. Read PR metadata again and call
`merge_pull_request` with the PR number, `merge_method: "merge"`, and the returned current
`head_sha` as `expected_head_sha`.

Expected: all checks succeed, Branch Flow reports `production -> development` allowed, and the PR merges.

- [ ] **Step 3: Fast-forward the local development branch to the remote merge**

Run:

```powershell
git fetch origin --prune --tags
git switch development
git merge --ff-only origin/development
git status --short --branch
```

Expected: local development fast-forwards cleanly and the workspace is clean.

---

### Task 10: Final Verification and Audit

**Files:**
- No further repository changes expected.

**Interfaces:**
- Consumes: all merged repository changes and active GitHub rulesets.
- Produces: final evidence that direct production push, PR promotions, version isolation, history protection, and immutable tags all satisfy the approved design.

- [ ] **Step 1: Run the complete local gate on synchronized development**

Run:

```powershell
python scripts/local_gate.py
```

Expected: all repository checks and the 69-case release gate pass.

- [ ] **Step 2: Verify final branch ancestry and version isolation**

Run:

```powershell
git fetch origin --prune --tags
git merge-base --is-ancestor origin/main origin/production
if ($LASTEXITCODE -ne 0) { throw 'main is not an ancestor of production' }
git merge-base --is-ancestor origin/production origin/development
if ($LASTEXITCODE -ne 0) { throw 'production is not an ancestor of development' }
Write-Output "main...production $(git rev-list --left-right --count origin/main...origin/production)"
Write-Output "production...development $(git rev-list --left-right --count origin/production...origin/development)"
Write-Output "main $((git show origin/main:pyproject.toml | Select-String '^version =').Line)"
Write-Output "production $((git show origin/production:pyproject.toml | Select-String '^version =').Line)"
Write-Output "development $((git show origin/development:pyproject.toml | Select-String '^version =').Line)"
```

Expected: both ancestry checks pass; main and production print `0.3.0rc1`; development prints `0.4.0.dev0`.

- [ ] **Step 3: Verify all five active rulesets and exact production boundaries**

Run:

```powershell
$credentialInput = "protocol=https`nhost=github.com`n`n"
$credentialOutput = $credentialInput | git credential fill
$passwordLine = $credentialOutput | Where-Object { $_ -like 'password=*' } | Select-Object -First 1
if (-not $passwordLine) { throw 'GitHub credential unavailable' }
$token = $passwordLine.Substring(9)
$headers = @{
  Accept = 'application/vnd.github+json'
  Authorization = "Bearer $token"
  'X-GitHub-Api-Version' = '2022-11-28'
  'User-Agent' = 'GraphRAG-C9-Governance'
}
$endpoint = 'https://api.github.com/repos/thiefsima-cpu/all-in-rag-intelligent-customer/rulesets'
$rulesets = Invoke-RestMethod -Headers $headers -Uri $endpoint
$expected = @(
  'Protect release tags v*',
  'Protect main',
  'Protect production',
  'Protect production history',
  'Protect development'
)
foreach ($name in $expected) {
  $matches = @($rulesets | Where-Object { $_.name -eq $name })
  if ($matches.Count -ne 1) { throw "missing or duplicate ruleset: $name" }
  $rule = Invoke-RestMethod -Headers $headers -Uri "$endpoint/$($matches[0].id)"
  if ($rule.enforcement -ne 'active') { throw "inactive ruleset: $name" }
  Write-Output "$($rule.id) $($rule.name) $($rule.enforcement)"
}

$historySummary = @($rulesets | Where-Object { $_.name -eq 'Protect production history' })[0]
$governanceSummary = @($rulesets | Where-Object { $_.name -eq 'Protect production' })[0]
$history = Invoke-RestMethod -Headers $headers -Uri "$endpoint/$($historySummary.id)"
$governance = Invoke-RestMethod -Headers $headers -Uri "$endpoint/$($governanceSummary.id)"
if (@($history.bypass_actors).Count -ne 0) { throw 'history bypass must be empty' }
if (@($history.rules.type | Sort-Object) -join ',' -ne 'deletion,non_fast_forward') {
  throw 'history rules are incorrect'
}
$adminBypass = @($governance.bypass_actors | Where-Object {
  $_.actor_id -eq 5 -and $_.actor_type -eq 'RepositoryRole' -and $_.bypass_mode -eq 'always'
})
if ($adminBypass.Count -ne 1 -or @($governance.bypass_actors).Count -ne 1) {
  throw 'governance bypass is incorrect'
}
if (@($governance.rules.type | Sort-Object) -join ',' -ne 'pull_request,required_status_checks') {
  throw 'governance rules are incorrect'
}
```

Expected names and enforcement:

```text
Protect release tags v* active
Protect main active
Protect production active
Protect production history active
Protect development active
```

Assert again that production history has zero bypass actors and exactly `deletion` plus `non_fast_forward`, while production governance has only `pull_request` plus `required_status_checks` and exactly the admin `always` bypass.

- [ ] **Step 4: Verify tag immutability and clean workspace**

Run:

```powershell
git ls-remote --tags origin 'refs/tags/v0.3.0-rc.1*'
git status --short --branch
git log -5 --oneline --decorate
```

Expected: tag SHAs remain exactly `9cd402c2588fa3ef7ff2fd3672906a2d11ee3b6c` and `5e6f1ca2170ae06cbffca9de6cc9e41b2288b3c7`; local development tracks remote development with no changes.

- [ ] **Step 5: Record the direct-push and PR evidence in the final handoff**

Report:

- the production direct-push SHA and green push workflow run URL;
- the matching bypass Rule Suite ID;
- all three synchronization/promotion PR URLs and merge SHAs;
- the new production-history ruleset ID and retained production-governance ruleset ID;
- focused test and full local-gate results;
- final branch SHAs, versions, ancestry counts, and unchanged RC tag SHAs.

Expected: the handoff contains sufficient evidence to reproduce and audit every external state change.
