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
