# Branch Governance

GraphRAG C9 uses three long-lived branches:

- `development`: daily development integration; all changes arrive through checked pull requests.
- `production`: test and release-candidate acceptance; all changes arrive through checked pull
  requests.
- `main`: formal release baseline; all changes arrive through checked pull requests.

Normal promotion is `development -> production -> main`. Each promotion uses a merge commit.

After merging `development` to `production`, synchronize the new production merge commit through
a checked `production -> development` pull request. After merging `production` to `main`,
synchronize through checked `main -> production -> development` pull requests. These merge
commits keep all long-lived branches on a shared ancestry chain without direct pushes.

Required checks use the strict up-to-date policy. When a synchronization source does not already
contain the target tip, create `codex/sync-<source>-to-<target>` from the latest target, merge the
source into that short-lived branch, and open the checked pull request from the synchronization
branch. Only the `codex/sync-*` prefix may target `main` or `production`; ordinary `codex/*`
branches remain rejected. This preserves both histories without weakening checks or updating a
long-lived branch outside a pull request.

Release candidates use immutable tags such as `v0.4.0-rc.1` on accepted production commits and
GitHub prereleases. Formal deployments use immutable tags such as `v0.4.0` on main commits.
Branch tips are not deployment identifiers.

Hotfixes start from the latest deployed final tag on main. Create a `hotfix/` branch, merge the
checked pull request to main, create the patch tag, and synchronize through checked
`main -> production -> development` pull requests.

The repository is single-maintainer. Every long-lived branch requires pull requests,
zero approving reviews, resolved review conversations, and merge commits. `Branch Flow Policy`,
`Quality Gates`, `Secret Scan`, and `SBOM` must all pass before merge. All three branches block
deletion, force-push, and non-fast-forward updates without a bypass.

Every normal or emergency source branch must follow the paths enforced by
`scripts/check_branch_flow.py`. Urgency does not create an exception to pull-request or required
check enforcement.

## Failure and Rollback

A failed pull request is repaired with a new fix or revert commit on its source branch; never
force-push a long-lived branch. Do not create an RC or final tag while required checks are pending
or failed. A failed RC remains immutable and is replaced by a new RC number. A failed formal
deployment rolls back by redeploying the previous final tag; main and release tags are not reset.
Production defects use the documented `hotfix/` and synchronization flow.
