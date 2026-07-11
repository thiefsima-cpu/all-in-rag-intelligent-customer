# Three-Branch Release Governance Design

## 1. Purpose

This document defines the branch, CI, release, deployment-source, hotfix, and migration
governance for `thiefsima-cpu/all-in-rag-intelligent-customer`.

The target model has three long-lived branches:

- `development` for daily development integration;
- `production` for release candidates and pre-production acceptance; and
- `main` for the formal release baseline.

Formal deployments must use immutable final tags on `main`. Pre-production deployments must use
immutable release-candidate tags on `production`. Branch tips are not deployment identifiers.

## 2. Confirmed Constraints

- The repository is maintained by one person.
- `development` may receive direct pushes.
- `production` and `main` must only receive changes through pull requests.
- Promotions between long-lived branches must use merge commits, not squash or rebase merges.
- Release-candidate tags use forms such as `v0.4.0-rc.1` and point to accepted `production`
  commits.
- Final tags use forms such as `v0.4.0` and point to formal `main` commits.
- Hotfixes start from the current final tag on `main` and are synchronized back to the other
  long-lived branches after release.
- The local refactor at `6d1995b9bb816a14887ee125e043e702e2f2dedb` must seed the new
  `development` branch, excluding `agent/config.json`.
- The migration must not create `.worktrees`.
- Automatic PyPI publication is outside this design and remains disabled unless separately
  authorized.

## 3. Current Repository State

At design time:

- GitHub's default branch is `main`.
- `main` points to the merged `0.3.0rc1` release commit
  `5e6f1ca2170ae06cbffca9de6cc9e41b2288b3c7`.
- `v0.3.0-rc.1` is an immutable protected tag and has a GitHub prerelease.
- The active tag ruleset `Protect release tags v*` matches `refs/tags/v*` and blocks tag update
  and deletion.
- No branch ruleset protects `main`, `production`, or `development`.
- `.github/workflows/ci.yml` runs only for pull requests targeting `main`, pushes to `main`, and
  manual dispatches.
- `production` and `development` do not exist.
- Remote `codex/retrieval-candidate-source-resilience` has diverged from `main`: it is 52 commits
  ahead and 3 commits behind because the RC history was rebuilt safely.
- Remote `codex/release-0.3.0rc1` is the clean PR head and is one merge commit behind `main`.
- Local commit `6d1995b9bb816a14887ee125e043e702e2f2dedb` contains the desired module-boundary refactor,
  its dependency-isolation test, and an unwanted change to `agent/config.json`.

The old candidate branches are therefore migration inputs, not acceptable long-lived branch
bases.

## 4. Branch Architecture

### 4.1 Long-Lived Branches

| Branch | Responsibility | Allowed write path | Deployment use |
| --- | --- | --- | --- |
| `development` | Daily development integration and newest business code | Direct push or PR | Development environment |
| `production` | Stable release candidate and acceptance baseline | PR only | Pre-production, through RC tags |
| `main` | Formal release and master baseline | PR only | Production, through final tags |

Optional short-lived branches:

- `feature/*` and `fix/*` start from `development` and normally return to `development`.
- `hotfix/*` starts from the latest formal tag on `main` and returns to `main` through a PR.
- One-time governance or migration branches use the `codex/` prefix.

### 4.2 Normal Promotion

```text
feature/* or direct push
          |
          v
    development --merge commit--> production --merge commit--> main
                                            |                    |
                                  vX.Y.Z-rc.N tag          vX.Y.Z tag
                                  pre-production           production
```

Normal allowed pull-request paths are:

- `feature/*` or `fix/*` to `development`;
- `development` to `production`; and
- `production` to `main`.

The following are prohibited:

- `development` directly to `main`;
- feature branches directly to `production` or `main`;
- direct pushes to `production` or `main`;
- force-pushes to any long-lived branch; and
- squash or rebase promotion between long-lived branches.

### 4.3 Hotfix Flow

1. Create `hotfix/X.Y.Z` from the currently deployed final tag on `main`.
2. Implement and verify the smallest safe fix.
3. Merge `hotfix/X.Y.Z` to `main` through a PR and a merge commit.
4. Create and deploy the immutable patch tag from the new `main` tip.
5. Back-merge `main` to `production` through a PR.
6. Back-merge `production` to `development`, normally through a PR even though direct pushes are
   permitted on `development`.

The back-merges preserve ancestry and prevent the next normal promotion from dropping the hotfix.

## 5. GitHub Rulesets

### 5.1 `Protect main`

- Target: `refs/heads/main`
- Enforcement: `active`
- Block deletion.
- Block force-push.
- Require a pull request.
- Required approving reviews: `0`.
- Require all pull-request conversations to be resolved.
- Allowed merge method: merge commit only.
- Require the pull-request head to be up to date with `main`.
- Required checks:
  - `Branch Flow Policy`
  - `Quality Gates`
  - `Secret Scan`
  - `SBOM`

### 5.2 `Protect production`

The rule configuration matches `Protect main`. The branch-flow check allows only:

- `development` to `production` for normal promotion; and
- `main` to `production` for hotfix back-synchronization.

### 5.3 `Protect development`

- Target: `refs/heads/development`
- Enforcement: `active`
- Block deletion.
- Block force-push.
- Do not require a pull request.
- Do not require approvals.

CI still runs after every direct push. A red `development` commit is not eligible for promotion.

### 5.4 Bypass and Signing

No standing direct-push bypass is configured for `main` or `production`. An emergency ruleset
change must be made by the repository administrator, must remain visible in GitHub audit/history,
and must be reverted immediately after recovery.

Signed commits are not required in the first rollout because commit signing is not currently
configured. Signing may be introduced later as a separate governance change.

### 5.5 Tags

The existing active `Protect release tags v*` ruleset remains unchanged. It protects RC and final
tags against update and deletion.

## 6. CI and Branch-Flow Enforcement

### 6.1 CI Triggers

`.github/workflows/ci.yml` must cover all long-lived branches:

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

The existing quality jobs remain mandatory:

- Ruff lint and format checks;
- Mypy;
- pytest with branch coverage;
- incremental coverage on pull requests;
- offline release gate;
- dependency vulnerability audit;
- Gitleaks secret scan; and
- CycloneDX SBOM generation.

### 6.2 Branch Flow Policy

A small repository script with focused tests evaluates `GITHUB_BASE_REF` and `GITHUB_HEAD_REF`.
The workflow exposes it as the stable check name `Branch Flow Policy`.

Rules:

- Base `main`: allow head `production` or `hotfix/*`.
- Base `production`: allow head `development` or `main`.
- Base `development`: allow feature/fix branches and `production` for back-synchronization.
- Other target branches are outside long-lived branch governance.

The check reports the rejected source and the permitted alternatives. It has no repository write
permissions.

During the one-time bootstrap PR, the checker and tests are installed in report-only mode. Strict
enforcement is enabled on `development` after the three branches exist, then promoted through
`production` to `main`. This avoids creating a permanent bootstrap exception.

## 7. Version, Tag, and Release Lifecycle

### 7.1 Development Version

During ordinary development, `[project].version` uses the next planned PEP 440 development
version, for example `0.4.0.dev0`. Individual development builds are distinguished by commit SHA;
`.devN` is not incremented for every commit.

### 7.2 Release Candidates

1. Temporarily freeze `development` to changes required for the current release.
2. Set the version to `X.Y.Zrc1` and move the corresponding changelog entries out of Unreleased.
3. Promote `development` to `production` with a merge commit.
4. Run the complete CI and acceptance process.
5. Create `vX.Y.Z-rc.1` at the accepted `production` tip.
6. Create a GitHub prerelease and deploy that exact tag to pre-production.

If acceptance finds a defect, fix it first on `development`, promote again, increment the version
to `rc.N+1`, and create a new immutable RC tag. An existing RC tag is never moved or reused.

### 7.3 Final Release

1. On `development`, set the version to `X.Y.Z` and finalize release notes.
2. Promote the finalization commit to `production` and rerun all gates.
3. Promote `production` to `main` with a merge commit.
4. Create `vX.Y.Z` at the resulting `main` tip.
5. Create the formal GitHub Release.
6. Deploy production only from that final tag.
7. Advance `development` to the next planned development version.

### 7.4 Tag Validation Workflow

A dedicated release workflow validates any `v*` tag before producing release artifacts:

- `vX.Y.Z-rc.N` must point to the current accepted `production` commit.
- Its package version must normalize to `X.Y.ZrcN`.
- It may create only a GitHub prerelease and pre-production deployment.
- `vX.Y.Z` must point to the current accepted `main` commit.
- Its package version must equal `X.Y.Z`.
- Only a final tag is eligible for formal deployment.
- Wheel, sdist, package metadata, and SBOM are built and verified.

The workflow does not publish to PyPI without separate explicit authorization.

### 7.5 Existing RC Exception

`v0.3.0-rc.1` points to `main` because it predates this governance model. It remains an immutable
historical exception. It is not moved, deleted, or recreated. The new RC-origin policy starts with
the `0.4.0` cycle.

## 8. One-Time Migration

### 8.1 Bootstrap Governance

1. Verify the remote `main` SHA, `v0.3.0-rc.1`, GitHub prerelease, and tag ruleset.
2. Create a clean one-time governance branch from remote `main` without a worktree.
3. Add the multi-branch CI triggers, branch-flow checker in report-only mode, tests, and governance
   documentation.
4. Run `python scripts/local_gate.py`.
5. Open and merge the one-time governance PR to `main` under the pre-migration policy.

### 8.2 Create Clean Long-Lived Branches

1. Create `production` from the updated remote `main` tip.
2. Create `development` from exactly the same commit.
3. Verify both branches have the expected merge base and identical initial trees.

Neither branch is created from an existing `codex/*` branch.

### 8.3 Activate Governance

1. Create the three branch rulesets in `evaluate` mode.
2. Exercise valid and invalid promotion PR paths.
3. Enable strict branch-flow enforcement on `development` without adding business changes.
4. Promote that governance-only change `development` to `production` to `main` with merge commits.
5. Confirm all required check names are stable and visible on both protected targets.
6. Switch the three branch rulesets from `evaluate` to `active`.
7. Re-run the path tests against active enforcement.

### 8.4 Migrate the Latest Refactor

Only after governance is active on all three long-lived branches:

1. Extract from `6d1995b9bb816a14887ee125e043e702e2f2dedb` only the `rag_modules/` module moves and
   `tests/test_dependency_isolation.py`.
2. Exclude `agent/config.json` and every other local credential file.
3. Apply the extracted change to `development` as a new clean commit.
4. Set the development version to `0.4.0.dev0` in a focused commit.
5. Run focused dependency-isolation tests, the complete local gate, and Gitleaks.
6. Push `development` and require its GitHub CI to pass.
7. Do not promote this business refactor to `production` until the first `0.4.0` RC is prepared.

### 8.5 Retire Obsolete Branches

After all acceptance checks pass:

- delete the remote `codex/retrieval-candidate-source-resilience` branch;
- delete the remote `codex/release-0.3.0rc1` branch;
- retain their closed PR records, the immutable RC tag, and the GitHub prerelease;
- verify the migrated refactor exists on `development`; and
- only then remove obsolete local refs that held the migration source.

Deleting the old branch refs reduces accidental reuse of the pre-remediation history. No old
branch is deleted before its required content and audit evidence have been verified.

## 9. Security Boundaries

- `agent/config.json` must not be tracked on any new long-lived branch.
- `agent/config.example.json` is the only tracked agent configuration template.
- New branches are based on the remediated `main`, not the old candidate history.
- Gitleaks scans complete history on every protected promotion PR.
- Real credentials, customer data, and local runtime state remain excluded.
- Existing protected release tags are never rewritten.
- New long-lived branches are created by ordinary ref creation, not force-push.

## 10. Failure Handling and Rollback

- Failed `development` CI: add a corrective or revert commit; do not rewrite history.
- Failed RC acceptance: retain the failed RC tag and issue a new `rc.N+1` after fixes.
- Failed `production` to `main` gate: stop the release and return fixes through `development`.
- Failed formal deployment: redeploy the previous final tag; do not reset `main` or move tags.
- Formal defect: execute the hotfix flow and then back-merge the repair.
- Misconfigured ruleset: make an audited administrative adjustment, repair the rule, and restore
  active enforcement immediately.

## 11. Acceptance Criteria

The migration is complete only when all of the following are true:

- `production` was created from the verified post-governance `main` tip.
- `development` is a descendant of `production`.
- The latest module-boundary refactor exists on `development` as a clean commit.
- The refactor migration does not include `agent/config.json`.
- CI runs on pushes and pull requests for all three long-lived branches.
- Valid promotion paths pass `Branch Flow Policy`.
- Invalid promotion paths fail `Branch Flow Policy` with an actionable message.
- `main` and `production` require PRs, merge commits, and the four required checks.
- `development` permits direct push but blocks deletion and force-push.
- The complete local gate passes.
- GitHub Quality Gates, Secret Scan, and SBOM jobs pass.
- Gitleaks finds no credential in the new long-lived branch histories.
- `v0.3.0-rc.1` and its GitHub prerelease remain unchanged.
- No automatic PyPI publication occurs.

## 12. Non-Goals

- This design does not select or implement a production hosting platform.
- It does not enable automatic PyPI publication.
- It does not require commit signing in the first rollout.
- It does not introduce parallel version-specific release branches.
- It does not rewrite `main` or an existing release tag.
