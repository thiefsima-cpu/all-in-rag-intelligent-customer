# Release Process

GraphRAG C9 releases are package-versioned from `[project].version` in
`pyproject.toml`. API and compatibility-removal versions remain separate axes and
must be called out explicitly when they change.

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
7. Tagging: create a signed or protected tag matching the package version, such
   as `v0.3.0`.

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
