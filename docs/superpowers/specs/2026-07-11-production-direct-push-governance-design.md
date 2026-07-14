# Production Direct-Push Governance Design

**Date:** 2026-07-11

**Status:** Superseded

**Replacement:** `2026-07-14-strict-long-lived-branch-protection-design.md`; retained as
historical context

## 1. Goal

Allow the single repository maintainer to create commits on the local `production` branch and
fast-forward push them directly to `origin/production`, while retaining these promotion rules:

- local `development` may fast-forward push to `origin/development`;
- `development -> production` remains a GitHub pull request merged with a merge commit;
- `production -> main` remains a GitHub pull request merged with a merge commit;
- branch deletion, force-push, and release-tag mutation remain prohibited.

`production` is the test and release-candidate acceptance branch. `main` remains the only formal
release baseline.

## 2. Constraints and Platform Limitation

Git does not record the name of the local source branch in a pushed commit. GitHub can evaluate
the target ref, commits, actor, rulesets, and check results, but cannot distinguish a commit made
while the maintainer had local `production` checked out from a commit fast-forwarded from local
`development`.

GitHub rulesets support bypass actors. A pull-request-only bypass does not permit direct pushes,
so the maintainer requires an `always` bypass on the ruleset that requires pull requests. An
`always` bypass applies to all rules in that ruleset. History protections must therefore live in
a separate ruleset without bypass access.

Reference: [Creating rulesets for a repository](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/creating-rulesets-for-a-repository).

The requirement that `development -> production` use a pull request is consequently enforced by
the documented operating procedure, pull-request CI, and ruleset audit records rather than by an
unbypassable proof of the local source branch.

## 3. Ruleset Architecture

### 3.1 Protect Production History

Create an active `Protect production history` ruleset targeting `refs/heads/production`.

It contains:

- deletion protection;
- non-fast-forward protection;
- no bypass actors.

This ruleset applies to direct pushes and pull-request merges. The maintainer cannot bypass it.

### 3.2 Govern Production Changes

Retain the active `Protect production` ruleset, but limit it to change-governance rules:

- require a pull request;
- require resolved review conversations;
- require merge commits;
- require zero approvals for the single-maintainer repository;
- require `Branch Flow Policy`, `Quality Gates`, `Secret Scan`, and `SBOM`.

Add the repository-administrator role as an `always` bypass actor. This permits the maintainer's
direct fast-forward production pushes while preserving the normal checked pull-request path.

### 3.3 Unchanged Rules

- `Protect main` remains pull-request-only with all required checks.
- `Protect development` continues to permit direct fast-forward pushes while blocking deletion
  and non-fast-forward updates.
- `Protect release tags v*` remains active and continues to block tag updates and deletions.
- `Branch Flow Policy` continues to allow `development -> production`, `production -> main`,
  `main -> production`, and `production -> development` synchronization paths.

## 4. Operating Workflows

### 4.1 Direct Production Commit

1. Switch to local `production`.
2. Fast-forward it from `origin/production` with `git pull --ff-only`.
3. Make and commit the test-branch change.
4. Run focused tests and `python scripts/local_gate.py`.
5. Fast-forward push local `production` to `origin/production` using the maintainer bypass.
6. Wait for production push CI to pass.
7. Open a `production -> development` pull request and merge it after checks pass.

No version-controlled production change may remain permanently absent from `development`.

### 4.2 Development Promotion

1. Confirm all earlier production direct commits have been synchronized into `development`.
2. Open a `development -> production` pull request.
3. Wait for all four required checks to pass.
4. Merge with a merge commit.
5. Fast-forward `development` to the resulting production merge commit.

The administrator bypass is not used for this promotion.

### 4.3 Formal Promotion and Synchronization

1. Promote `production -> main` through a checked pull request and merge commit.
2. Create formal release tags only on the resulting main commit.
3. Synchronize `main -> production` through a checked pull request.
4. Synchronize the resulting production history into `development`.

Release-candidate tags may be created only on a production commit whose push or pull-request CI
has passed. Formal tags remain restricted to main.

## 5. Failure Handling

- If a direct production push fails CI, do not create an RC tag.
- Repair it with a new production commit or a revert commit; never rewrite production history.
- After CI passes, synchronize the repair into development through a pull request.
- If a development promotion fails, repair development and update the pull request.
- A failed RC tag remains immutable and is replaced with the next RC number.
- Rule Insights and the repository audit trail distinguish bypassed direct pushes from normal
  pull-request merges.

## 6. Repository Changes

Implementation will:

- add `.github/rulesets/production-history.json`;
- update `.github/rulesets/production.json` with the administrator `always` bypass and only the
  pull-request/check rules;
- update ruleset manifest tests;
- update `docs/branch_governance.md` and `docs/release_process.md`;
- retain the existing CI branch triggers and pull-request flow checker.

No business behavior, dependency, package version, release tag, or deployment target changes are
part of this governance adjustment.

## 7. Safe Rollout

Because `development` currently contains `0.4.0.dev0` business changes that have not reached
production, the governance change must not be promoted from development as a bulk change.

The one-time rollout order is:

1. Create `Protect production history` as active before weakening the existing production
   ruleset.
2. Update `Protect production` to the approved governance-only payload with the administrator
   bypass.
3. Commit the repository governance files directly on local production and fast-forward push the
   commit. This is the real direct-push acceptance test.
4. Require the production push CI to pass.
5. Promote the governance-only commit through `production -> main`.
6. Synchronize `main -> production`.
7. Synchronize `production -> development`, preserving the existing development-only refactor.

There must be no interval in which production lacks deletion and non-fast-forward protection.

## 8. Verification

Repository verification includes:

- focused ruleset-manifest tests;
- Branch Flow Policy tests;
- governance documentation contract tests;
- `python scripts/local_gate.py`;
- the real production fast-forward push CI;
- all checks on the synchronization pull requests.

Remote verification includes:

- both production rulesets are active;
- the history ruleset has no bypass actor;
- the governance ruleset has exactly the approved administrator `always` bypass;
- production deletion and non-fast-forward rules remain effective;
- main, production, and development retain the expected ancestry;
- main and production remain on the release baseline while development retains `0.4.0.dev0`;
- existing protected tags are unchanged.

## 9. Acceptance Criteria

The adjustment is complete only when:

- a local production commit has been fast-forward pushed successfully;
- its production push CI is green;
- `development -> production` remains documented and tested as a pull-request merge path;
- the direct production commit has been synchronized into development;
- main remains pull-request-only;
- production deletion and force-push remain impossible for the maintainer;
- all four repository rulesets plus the additional production history ruleset are active;
- the workspace and all three remote long-lived branches are in the audited expected state.
