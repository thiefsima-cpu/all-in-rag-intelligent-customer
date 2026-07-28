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
   API. Capture requires the canonical schema-v2 live-quality policy and a
   schema-v2 live report with the 52-case baseline, five customer-service
   grounded-answer cases, rerank coverage, and all interaction SLO checks.
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
new live evidence run. Recapture on every candidate commit; do not reuse the
manifest or ZIP after such a change. The release-evidence capture receipt and
the final version-named manifest use evidence schema v2, so a pre-v2 live
report or evidence bundle cannot establish release eligibility.

## PostgreSQL Build-job Control Plane

The production baseline uses PostgreSQL 16+ for the Build API and external workers. The file
backend is development-only and scans V3 directories; it remains the explicit default in
`profiles/dev.toml` and the Compose `api` profile. When PostgreSQL is selected, missing DSN,
connectivity, pool, or schema compatibility fails closed with no automatic fallback. Runtime
startup never migrates or imports, so a rollout must use the one-shot CLI before starting the new
API or workers.

### Configuration

Store `BUILD_JOB_POSTGRES_DSN` in the deployment secret manager and do not print it in logs,
scripts, tickets, or release evidence. Configure:

- `API_BUILD_JOB_REPOSITORY_BACKEND=postgresql`;
- `BUILD_JOB_POSTGRES_DSN` for the dedicated PostgreSQL database;
- `API_BUILD_JOB_POSTGRES_POOL_MIN_SIZE` (default `1`),
  `API_BUILD_JOB_POSTGRES_POOL_MAX_SIZE` (default `10`), and
  `API_BUILD_JOB_POSTGRES_POOL_TIMEOUT_SECONDS` (default `5`);
- `API_BUILD_JOB_RETENTION_LIMIT` (default `100`) for operationally visible terminal jobs; and
- `API_BUILD_JOB_AUDIT_RETENTION_DAYS` (default `90`) for 90-day audit retention before physical
  purge.

Operational retention archives excess terminal jobs while preserving their events and
idempotency ownership. A later retention pass physically purges archived events and jobs only
after audit expiry. Size backups for the complete audit window, not only the visible job limit.

### One-shot commands and output contracts

Run these commands from the candidate application image/environment so packaged migrations match
the code being deployed:

```powershell
graph-rag-build-job-db status --json
graph-rag-build-job-db migrate --json
graph-rag-build-job-db import-file --source storage/indexes/build_jobs.json --dry-run --json
graph-rag-build-job-db import-file --source storage/indexes/build_jobs.json --json
```

`status` is read-only. `status` and `migrate` JSON reports
`current_version`, `required_version`, `pending_versions`, and `ready`; ready/success returns exit
code `0`, while not-ready or failure returns exit code `1`. `import-file` JSON reports
`scanned_jobs`, `scanned_events`, `imported_jobs`, `skipped_jobs`, `conflicts`, and `dry_run`;
success returns exit code `0`, and corruption, destination conflict, or database failure returns
exit code `1`. Errors are intentionally stable and omit DSNs, SQL, source payloads, and raw
exceptions. Always save the JSON report as release evidence, but never capture the process
environment.

For local integration, `docker compose --profile postgres up -d build-job-postgres` starts only the
optional persistent database. Invoke the same explicit one-shot command from the application
image, for example:

```powershell
docker compose run --rm --no-deps build-api graph-rag-build-job-db status --json
docker compose run --rm --no-deps build-api graph-rag-build-job-db migrate --json
```

Do not add migration/import commands to API or worker startup, a container entrypoint, or a
restart policy.

### Initial file-to-PostgreSQL cutover

1. Provision PostgreSQL 16+ with durable storage, monitoring, backups, and a least-privilege
   runtime identity. Verify restore procedures before cutover.
2. Deploy the candidate application image to an operator environment with the secret DSN. Run
   `graph-rag-build-job-db status`; on a new database it may return exit code `1` as not ready.
3. Run `graph-rag-build-job-db migrate`, then rerun `status` and require `ready=true`.
4. Back up PostgreSQL and the complete source V3 directory (`build_jobs.json` plus its sibling
   `build_jobs.d`). Retain the earlier `build_jobs.v2.backup` when present.
5. Run
   `graph-rag-build-job-db import-file --source storage/indexes/build_jobs.json --dry-run` and
   resolve every validation or destination conflict. A dry-run never writes.
6. Stop the Build API and every build worker before switching the backend. This freezes file
   history; run the dry-run again, then execute the same command without `--dry-run`.
7. Set the backend, DSN, pool, operational-retention, and audit-retention variables on both Build
   API and every worker. Never configure one process to use files while another uses PostgreSQL.
8. Start workers and the Build API. Require readiness, PostgreSQL diagnostics with `ready=true`,
   and bounded repository/claim/error/archive/purge metrics before accepting traffic.
9. Retain the source V3 directory, import reports, and pre-cutover database backup for the full
   rollback window. Do not delete file history merely because cutover succeeded.

### Upgrade, backup, and rollback order

For every application release containing a packaged migration: drain submissions; stop the Build
API and every worker; take and verify a database backup; deploy the new one-shot CLI; run `status`,
then `migrate`, then `status` again; start workers/API; and verify diagnostics and metrics. Never
run old application processes against a newly upgraded schema unless that version combination was
explicitly certified.

If schema migration fails, leave API/workers stopped, preserve the failure JSON, restore the
pre-upgrade database backup when the migration transaction did not leave a certified state, and
redeploy the prior application version. For backend rollback, stop the Build API and every build
worker before switching the backend to `file`, restore the retained V3 directory, reconcile or
explicitly abandon jobs accepted only in PostgreSQL, and then start the prior processes. A backend
switch never copies data automatically, and startup has no automatic fallback.

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
