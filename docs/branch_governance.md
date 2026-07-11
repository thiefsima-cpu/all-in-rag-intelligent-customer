# Branch Governance

GraphRAG C9 uses three long-lived branches:

- `development`: daily development integration; local `development` may direct fast-forward push.
- `production`: test and release-candidate acceptance; local `production` may direct fast-forward
  push through the administrator bypass, but must never force-push.
- `main`: formal release baseline; pull requests are required and there is no direct-push bypass.

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

The repository is single-maintainer. Normal promotions into main and production require pull
requests and CI but zero approving reviews. Development permits direct push but cannot be promoted
while CI is red.

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

## Failure and Rollback

A failed direct production push is repaired with a new fix or revert commit; do not create an RC
tag and never force-push. Synchronize the repair into development only after production push CI
passes. A failed development check is repaired with a new fix or revert commit, never a force-push.
A failed RC remains immutable and is replaced by a new RC number. A failed formal deployment rolls
back by redeploying the previous final tag; main and release tags are not reset. Production defects
use the documented hotfix and synchronization flow.
