# Release Process

GraphRAG C9 releases are package-versioned from `[project].version` in
`pyproject.toml`. API and compatibility-removal versions remain separate axes and
must be called out explicitly when they change.

## Branch Promotion

The governed flow is `development -> production -> main`. Promotions use merge commits. After
each promotion, synchronize the target merge commit back into its source branch as documented in
`docs/branch_governance.md`.

### Production Direct-Push Exception

The single maintainer may direct fast-forward push a commit created on local `production`.
Production push CI must pass before synchronization or RC tagging. Every such change is merged
back through a `production -> development` pull request. `development -> production` remains a
checked pull request with a merge commit.

Do not create an RC tag when production push CI is pending or failed. Repair or revert with a new
commit; production history is never rewritten.

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

Main requires pull requests and all four checks without bypass. Production uses two active
rulesets: `Protect production history` blocks deletion and non-fast-forward updates without
bypass, while `Protect production` requires pull requests and the four checks but grants the
repository administrator an `always` bypass for local production fast-forward pushes. Required
approvals remain zero for the single-maintainer repository. Development permits direct pushes but
blocks deletion and force-push.

## Release Checklist

1. Version bump: update `[project].version` in `pyproject.toml`.
2. Dependency locks: run `.\scripts\compile_locks.ps1` with Python 3.11 when
   dependencies changed.
3. CHANGELOG.md: move `Unreleased` entries into a dated version section and add
   any migration notes, security notes, API contract notes, or compatibility
   removals.
4. Local verification: run `python scripts/local_gate.py`.
5. CI verification: require pytest coverage, incremental coverage, mypy, Ruff,
   `python scripts/release_gate.py`, `pip-audit`, secret scanning, and SBOM
   generation to pass on each promotion pull request.
6. Release artifact review: download and retain the CI SBOM artifact
   `graph-rag-c9-sbom`.
7. Tagging: create a protected RC tag on the checked `production` commit or a protected final tag
   on the checked `main` commit. The release-candidate and final mappings are defined above.
8. GitHub Release: create release notes from `CHANGELOG.md` and enable the prerelease flag for
   release candidates.

## Coverage Policy

The repository has a full-suite coverage baseline in `pyproject.toml`. Pull
requests also enforce incremental coverage with `diff-cover` against the target
branch. Raise the baseline when sustained coverage improves; do not lower it
without recording the reason in `CHANGELOG.md`.

## Security Response Releases

Security releases follow the same checklist, but the changelog entry may describe
impact and mitigation without exposing exploit details. If a vulnerable
dependency is fixed only in lock files, the release pull request still needs the
dependency audit and SBOM checks.
