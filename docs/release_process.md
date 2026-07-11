# Release Process

GraphRAG C9 releases are package-versioned from `[project].version` in
`pyproject.toml`. API and compatibility-removal versions remain separate axes and
must be called out explicitly when they change.

## Release Candidates

Release candidates use PEP 440 package versions and human-readable Git tags. For this release,
package version `0.3.0rc1` maps to Git tag `v0.3.0-rc.1`.

Every release candidate must:

- pass the complete release checklist through a pull request targeting `main`;
- create its signed or protected tag only after the checked pull request is merged;
- point the tag at the resulting `main` commit, never at the release branch;
- create a GitHub Release with the prerelease flag enabled; and
- keep the RC tag immutable when preparing the later final release.

The final `v0.3.0` release is a separate release operation. It must not move, replace, or reuse
`v0.3.0-rc.1`.

## Required GitHub Enforcement

Repository administrators should protect `main` with these required checks:

- `Quality Gates`
- `Secret Scan`
- `SBOM`

Enable "Require review from Code Owners" so `.github/CODEOWNERS` forces review
for public API contracts, quality corpus assets, and governance files.

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
   generation to pass on the release pull request.
6. Release artifact review: download and retain the CI SBOM artifact
   `graph-rag-c9-sbom`.
7. Tagging: create a signed or protected tag for the package version on the checked `main`
   commit. Final releases use tags such as `v0.3.0`; release-candidate mapping is defined above.
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
