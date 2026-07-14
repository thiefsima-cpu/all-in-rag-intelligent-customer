# Strict Long-Lived Branch Protection Design

**Date:** 2026-07-14

**Status:** Approved for implementation planning

## 1. Goal

Require every change to `development`, `production`, and `main` to arrive through a checked pull
request. No repository role has a standing direct-push bypass for any long-lived branch.

The final policy must preserve the existing three-branch release model:

- `development` is the daily feature-integration branch;
- `production` is the release-candidate and pre-production acceptance branch;
- `main` is the formal release baseline;
- release-candidate tags point to accepted `production` commits;
- final release tags point to checked `main` commits.

This change affects repository governance only. It does not change application behavior,
dependencies, package versions, release tags, or deployment targets.

## 2. Chosen Approach

The repository will use one active ruleset per long-lived branch. Each ruleset has the same
history and change-governance rules, while `scripts/check_branch_flow.py` continues to enforce the
different allowed source branches.

This approach was selected over two alternatives:

1. Keeping the separate `Protect production history` ruleset after removing the production
   bypass. That is a smaller patch but leaves an unnecessary split that can drift.
2. Replacing all branch rulesets with one multi-branch ruleset. That is more compact but weakens
   branch-specific auditability and makes later policy changes harder to isolate.

The selected model keeps branch ownership explicit without retaining bypass-driven complexity.

## 3. Target Ruleset Architecture

`Protect development`, `Protect production`, and `Protect main` each target exactly one branch
and contain:

- deletion protection;
- non-fast-forward protection;
- no bypass actors;
- required pull requests;
- zero required approving reviews for the single-maintainer repository;
- required resolution of review conversations;
- merge commits as the only allowed merge method;
- strict required status checks;
- `Branch Flow Policy`;
- `Quality Gates`;
- `Secret Scan`;
- `SBOM`.

The existing `Protect production history` ruleset becomes redundant after `Protect production`
contains deletion and non-fast-forward rules without a bypass. Its repository manifest and remote
ruleset will be deleted only after the consolidated production ruleset is active and verified.

The protected `v*` tag ruleset remains unchanged.

## 4. Allowed Branch Flows

The existing branch-flow policy remains authoritative:

- `feature/*`, `fix/*`, `hotfix/*`, `codex/*`, and `dependabot/*` may target `development`;
- `development` may target `production`;
- `production` may target `main`;
- `main` may target `production` for post-release synchronization;
- `production` may target `development` for synchronization;
- `hotfix/*` may target `main`.

Direct pushes to all three long-lived branches are prohibited. Force-pushes and branch deletion
remain prohibited.

## 5. Normal and Emergency Workflows

Normal development starts from the latest `development` commit, uses a short-lived branch, and
targets `development` through a pull request. Release promotion remains
`development -> production -> main`, with merge commits and all four required checks at every
promotion.

An emergency production defect starts from the latest deployed final tag or current `main`, uses
a `hotfix/*` branch, and targets `main` through a checked pull request. After the fix is merged and
tagged, it is synchronized through `main -> production -> development`. Emergency urgency does
not create a direct-push exception.

## 6. Repository Changes

Implementation will:

- add pull-request and required-check rules to `.github/rulesets/development.json`;
- remove the administrator bypass from `.github/rulesets/production.json`;
- add deletion and non-fast-forward rules to `.github/rulesets/production.json`;
- delete `.github/rulesets/production-history.json` after its rules are consolidated;
- retain `.github/rulesets/main.json` as the reference strict shape;
- update `tests/test_branch_ruleset_manifests.py` to require the strict shape for all three
  long-lived branches;
- update `tests/test_enterprise_governance.py` to reject documented direct-push exceptions;
- update `docs/branch_governance.md` and `docs/release_process.md`;
- mark the superseded direct-push design as historical without deleting it;
- retain `.github/workflows/ci.yml` and `scripts/check_branch_flow.py` unless a test exposes a
  real policy mismatch.

## 7. Safe Rollout

`development` contains changes that have not been promoted to `production` or `main`. The
governance update must therefore start from the current remote `main` baseline and move through
the synchronization path without promoting unrelated development work.

The rollout order is:

1. Create `hotfix/strict-long-lived-branch-protection` from the latest `origin/main`.
2. Add the approved specification, tests, manifests, and documentation on that branch.
3. Run focused governance tests and `python scripts/local_gate.py`.
4. Push the branch and open a checked pull request to `main`.
5. Merge the checked hotfix pull request to `main` with a merge commit.
6. Open and merge a checked `main -> production` synchronization pull request.
7. Update the remote `Protect production` ruleset from the consolidated production manifest.
8. Verify that production has no bypass and contains deletion, non-fast-forward, pull-request,
   and required-check rules.
9. Delete the remote `Protect production history` ruleset.
10. Update remote `Protect development` to the strict manifest.
11. Open and merge a checked `production -> development` synchronization pull request.
12. Verify repository files, remote rulesets, branch ancestry, CI results, and protected tags.

There must be no interval in which `production` lacks deletion or non-fast-forward protection.
The old production-history ruleset is deleted only after its replacement rules are confirmed.

## 8. Failure Handling

- If the hotfix pull request fails, repair the hotfix branch and rerun its checks.
- If a synchronization pull request fails, add a new fix commit through the same checked path;
  do not bypass the target branch.
- If the consolidated production ruleset cannot be verified, keep `Protect production history`
  active and stop the rollout.
- If deleting the redundant production-history ruleset fails, leave the duplicate protection in
  place until it can be removed safely.
- If strict development protection cannot be applied, do not use the still-available direct-push
  path; repair the ruleset first.
- Never force-push, reset a long-lived branch, reuse a release tag, or weaken tag protection as a
  recovery mechanism.

## 9. Testing and Verification

Repository verification proceeds test-first:

1. Change manifest and documentation contract tests so they fail against the old policy.
2. Update the manifests and documentation until the focused tests pass.
3. Run `tests/test_branch_ruleset_manifests.py`, `tests/test_branch_flow_policy.py`, and the
   governance slice in `tests/test_enterprise_governance.py`.
4. Run Ruff and formatting checks for touched files.
5. Run `python scripts/local_gate.py`.
6. Require all four GitHub checks on every rollout pull request.

Remote verification uses the authenticated GitHub rulesets API to prove:

- each long-lived branch has exactly one active strict branch ruleset;
- every long-lived branch has zero bypass actors;
- all four rule types are effective on each branch;
- the required check names match the CI job names exactly;
- `Protect production history` is absent only after consolidation;
- the protected `v*` tag ruleset is unchanged.

## 10. Acceptance Criteria

The governance change is complete only when:

- `development`, `production`, and `main` are pull-request-only;
- all three long-lived branches reject deletion and non-fast-forward updates;
- no long-lived branch ruleset has a bypass actor;
- all three branches require `Branch Flow Policy`, `Quality Gates`, `Secret Scan`, and `SBOM`;
- all three branches allow merge commits only;
- `.github/rulesets/production-history.json` and its remote ruleset are absent;
- the governance commit is present in `main`, `production`, and `development` through checked
  merge commits;
- all rollout pull requests have green required checks;
- branch ancestry remains synchronized and no development-only feature is promoted accidentally;
- protected release tags and their ruleset remain unchanged.
