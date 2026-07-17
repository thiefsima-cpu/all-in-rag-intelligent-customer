# Release Process

GraphRAG C9 releases are package-versioned from `[project].version` in
`pyproject.toml`. API and compatibility-removal versions remain separate axes and
must be called out explicitly when they change.

## Branch Promotion

The governed flow is `development -> production -> main`. Promotions use merge commits. After
each promotion, synchronize the target merge commit back through checked pull requests as
documented in `docs/branch_governance.md`. The complete synchronization path after a formal
promotion is `main -> production -> development`.

If the source of a promotion or synchronization pull request is behind its target, create a
`codex/sync-*` branch from the latest target and merge the source into it before opening the pull
request. Do not disable the strict up-to-date check and do not update a long-lived source branch
outside its own pull request.

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

`development`, `production`, and `main` each require pull requests, resolved review
conversations, merge commits, and the same four checks without bypass: `Branch Flow Policy`,
`Quality Gates`, `Secret Scan`, and `SBOM`. Required approvals remain zero for the
single-maintainer repository. All three branches block deletion and non-fast-forward updates.

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
7. Evidence capture: run the `Release Quality Evidence` workflow in `capture`
   mode on the prepared candidate commit. Its `evaluated_commit` must be the
   exact commit exercised by the live gates, and the configured artifact
   manifest must identify the active ready knowledge base used by the serving
   API.
8. Evidence review and finalization: review the complete quality evidence ZIP,
   download the finalized compact manifest artifact, and commit that manifest
   only at
   `quality-evidence/releases/<package-version>/evidence-manifest.json`.
9. Pre-tag verification: run the same workflow in `verify` mode against the
   manifest commit, the original `evaluated_commit`, and the planned protected
   tag. Treat `case_count=0` as ineligible for success evidence.
10. Tagging: create the protected RC tag on the checked `production` commit or
   the protected final tag on the checked `main` commit only while pre-tag
   verification is green and its selected Actions artifact is unexpired. The
   release-candidate and final mappings are defined above.
11. Draft release: require the protected tag workflow to create a draft GitHub
    Release containing exactly the wheel, sdist, SBOM, compact manifest, and
    complete quality evidence ZIP. The ZIP is both the verified Actions
    artifact and a GitHub Release asset; the workflow does not publish to PyPI.
12. Publication review: review the draft assets and release notes before
    publishing, and enable the prerelease flag for release candidates.

Any code, profile, policy, prompt, dependency, or corpus change after the
`evaluated_commit` invalidates the capture for release selection and requires a
new live evidence run. Do not reuse the manifest or ZIP after such a change.

## Coverage Policy

The full suite writes `coverage.json` and then runs
`python scripts/check_coverage_policy.py`. Coverage is enforced at three levels: 75% repository
combined coverage, 70% `rag_modules` branch coverage, and 85% combined plus 80% branch coverage
for every exact file listed under `tool.graph_rag.coverage.risk_modules`. Add a new risk file by
adding an explicit TOML entry; directory aggregation and inherited thresholds are not supported.

Protected risk files:

- `rag_modules/retrieval/fusion.py`
- `rag_modules/retrieval/adapters/constraint_retriever.py`
- `rag_modules/retrieval/keyword_service.py`
- `rag_modules/retrieval/adapters/bm25_retriever.py`
- `rag_modules/retrieval/hybrid_driver_service.py`
- `rag_modules/infra/milvus/schema.py`
- `rag_modules/infra/milvus/client.py`
- `rag_modules/app/composition/build_runtime_executor.py`
- `rag_modules/runtime/build_jobs/locks.py`

Pull requests continue to enforce 80% incremental coverage with `diff-cover`. Raise a baseline
only after full-suite results remain stable; do not lower a baseline without recording the reason
in `CHANGELOG.md`.

## Security Response Releases

Security releases follow the same checklist, but the changelog entry may describe
impact and mitigation without exposing exploit details. If a vulnerable
dependency is fixed only in lock files, the release pull request still needs the
dependency audit and SBOM checks.

Urgent fixes use checked `hotfix/ -> main -> production -> development` pull requests; urgency
does not permit direct push or bypass required checks.
