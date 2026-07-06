# Build Job Repository Reliability Design

**Date:** 2026-06-29

**Status:** Approved for implementation planning

## Goal

Make asynchronous build-job state reliable under retries, restarts, large job histories, and
partially corrupted local state. The build API should support idempotent submissions, paginated
history reads, configurable retention, and safe corruption warnings without repeatedly rewriting
one large build-job document.

## Scope

This design covers:

- Build API job submission and job-listing contracts.
- Build-job persistence under `rag_modules/interfaces/api/build_jobs/`.
- Recovery of existing `build_jobs.json` state.
- Configuration for listing limits and retention.
- Safe diagnostics for corrupted build-job storage records.
- README and local environment example updates for operators.

This design does not change the knowledge-base build workflow itself, artifact manifest semantics,
Milvus or Neo4j build behavior, serving API routes, or the public answer response contract.

## Current Risks

- `PersistentBuildJobRegistry` currently reloads all jobs from `build_jobs.json` and rewrites the
  whole document for every state transition and log append.
- A large job history makes ordinary progress updates more expensive than necessary.
- A malformed `build_jobs.json` can hide all stored jobs because the whole file is the unit of
  recovery.
- Submitting through an unreliable client has no idempotency contract, so clients cannot safely
  retry after connection failures.
- `GET /jobs` returns an unbounded list, which does not scale with retained job history.
- There is no explicit retention policy, so successful and failed terminal jobs accumulate
  indefinitely.

## Chosen Approach

Introduce a directory-backed `BuildJobRepository` as the persistence boundary for build-job state.
Each job is stored in its own JSON file, and idempotency keys are stored as separate hashed index
records. Build-job state changes update only the affected job file and the small index files needed
for the operation.

The repository keeps the existing JSON-based operational style and avoids a new runtime
dependency. SQLite was rejected because it would make persistence more opaque for local operators
and would be a larger migration from the current artifact format. JSONL journaling was rejected
because pagination, retention, corruption recovery, and compaction would require more moving parts
than this slice needs.

## Storage Layout

The configured `storage.build_job_store_path` remains the compatibility anchor. If it points to
`storage/indexes/build_jobs.json`, the repository directory is derived as
`storage/indexes/build_jobs.d`.

The repository owns this layout:

```text
build_jobs.d/
  metadata.json
  jobs/
    <job_id>.json
  idempotency/
    <sha256-key>.json
```

`metadata.json` stores the repository schema version and migration markers. Job files store the
same safe public fields exposed today, plus an optional `idempotency_key_hash`. Idempotency index
files store only the key hash, the job ID, the job type, and timestamps. The raw
`Idempotency-Key` header is never persisted.

The existing cross-process store lock and build-flight lock remain file-lock based. The store lock
protects repository metadata, job writes, idempotency index writes, migration, and retention. The
build-flight lock continues to ensure only one active build or rebuild runs across service
instances.

## Repository Boundary

`BuildJobRepository` owns durable behavior and exposes methods shaped around service needs:

- `create_or_active(job_id, request_id, job_type, message, idempotency_key)`
- `active()`
- `get(job_id)`
- `list_page(limit, cursor)`
- `append_log(job_id, message)`
- `mark_running(job_id, message)`
- `mark_succeeded(job_id, result)`
- `mark_failed(job_id, result)`
- `corruption_summary()`

`GraphRAGBuildApiService` delegates persistence to the repository. It still owns runtime
coordination, executor submission, progress callbacks, and build/rebuild execution. The FastAPI
route layer handles HTTP headers and query parameters, then calls service methods using typed
values.

The existing `FileBuildJobStore` and `PersistentBuildJobRegistry` names remain available through
the compatibility facade during the migration. Their implementation can delegate to the repository
so existing tests and imports continue to work while the storage behavior changes.

## Idempotent Submission Contract

Build and rebuild submission routes read the `Idempotency-Key` HTTP header. Missing keys preserve
the current non-idempotent behavior.

Accepted idempotency keys are 1 to 128 visible ASCII characters, excluding control characters and
path separators. Invalid keys return `400 INVALID_REQUEST` with a safe validation reason. The
repository hashes accepted keys with SHA-256 and stores only the hash.

Submission behavior is:

- Same key and same `job_type`: return the original job payload with HTTP 202.
- Same key and different `job_type`: return `409 BUILD_JOB_CONFLICT`, with safe details pointing
  to the original job ID and job type.
- No key while another build job is active: preserve the current `409 BUILD_JOB_CONFLICT` behavior.
- New key while another build job is active: also return `409 BUILD_JOB_CONFLICT`; no idempotency
  mapping is created for a job that was not accepted.
- New key while no build job is active: create the job and its idempotency index in the same locked
  repository operation.

Compatibility aliases under `/knowledge-base/build` and `/knowledge-base/rebuild` use the same
header contract. Versioned `/v1` routes behave the same as unversioned routes.

## Pagination Contract

`GET /jobs` and `GET /v1/jobs` accept:

- `limit`: positive integer bounded by configuration.
- `cursor`: opaque string returned by the previous page.

The response keeps the existing top-level `jobs` field and adds `next_cursor`. Jobs are returned
newest first by creation timestamp, with job ID as the deterministic tie-breaker. If `next_cursor`
is empty or omitted, there are no more records. Invalid cursors return `400 INVALID_REQUEST`.

The route no longer promises to return the entire retained history in one response. Clients that
need history must follow `next_cursor`.

## Retention Policy

The API configuration gains:

- `api.build_job_retention_limit`, default `100`.
- `api.build_job_list_default_limit`, default `50`.
- `api.build_job_list_max_limit`, default `100`.

Environment overrides use:

- `API_BUILD_JOB_RETENTION_LIMIT`
- `API_BUILD_JOB_LIST_DEFAULT_LIMIT`
- `API_BUILD_JOB_LIST_MAX_LIMIT`

Retention runs after job creation and terminal state changes. It removes the oldest terminal jobs
above `build_job_retention_limit`. Queued and running jobs are always retained. Idempotency index
records for retained jobs are kept. Idempotency index records for removed jobs are deleted so a
very old retry can create a fresh job instead of pointing to missing state.

Setting the retention limit to zero is invalid because operators need at least one terminal job for
basic diagnosis. The list default limit must be less than or equal to the max limit.

## Corruption Handling

The repository treats each job file and idempotency index file as an independent recovery unit. If
a file cannot be read, parsed, or validated, the repository records an internal corruption warning
and continues with the remaining files.

Corruption warnings include:

- stable warning code;
- storage component type, such as `job` or `idempotency`;
- stable file name or key-hash prefix;
- timestamp.

Warnings never include raw file contents or raw exception text. Public diagnostics expose only a
safe summary with counts and warning codes. Build-job list responses skip corrupted job records.
Reading a corrupted job by ID returns the same not-found behavior as an unknown job.

## Legacy Migration

On initialization, the repository checks the legacy `build_jobs.json` only when `metadata.json`
does not already record a successful import for that exact source path. If the legacy file is
present and parseable, each valid job is written to `jobs/<job_id>.json`, then the metadata import
marker is persisted. The legacy file is not deleted or rewritten.

If the legacy file is malformed, the repository records a corruption warning for the legacy source
and starts with any already migrated directory records. A malformed legacy file does not prevent
new build jobs from being accepted.

Interrupted queued or running jobs keep the current recovery semantics: when no build-flight lock
is held by another service instance, startup marks them failed with the safe typed
`BUILD_FAILED` object and an interrupted-build log line. When another service still holds the
build-flight lock, startup preserves the active job as running.

## Data Flow

1. A client submits `/jobs/build` or `/jobs/rebuild` with an optional `Idempotency-Key`.
2. The request boundary resolves the safe request ID as it does today.
3. The route validates and passes the idempotency key to `GraphRAGBuildApiService`.
4. The service asks the repository to create a job or return the existing idempotent job.
5. The repository holds the store lock, refreshes active state from per-job files, checks the
   idempotency index, acquires the build-flight lock when creating a new job, writes only the new
   job and index files, and returns the job payload.
6. The executor updates running, log, succeeded, or failed state by rewriting only that job file.
7. Listing reads bounded job pages newest first and emits an opaque cursor for the next page.
8. Retention prunes terminal job files and stale idempotency index files after create and terminal
   transitions.

## API Models

`BuildJobPayloadModel` remains backward compatible except for the optional internal
`idempotency_key_hash`, which is not part of the public response model.

`BuildJobListResponseModel` adds:

```python
next_cursor: str = ""
```

The response builder continues to sanitize public error fields before model validation. OpenAPI
schemas for `/jobs` and `/v1/jobs` document the new pagination query parameters and response
cursor.

## Testing

Implementation follows test-driven development. Each behavior gets a focused failing test before
production code changes.

Repository tests cover:

- creating and retrieving a job from per-job storage;
- updating one job does not rewrite the legacy whole-file store;
- duplicate idempotency key plus same job type returns the same job;
- duplicate idempotency key plus different job type conflicts;
- active build-flight lock behavior across two service instances remains intact;
- terminal retention removes only old terminal jobs;
- retention preserves queued and running jobs;
- stale idempotency indexes are removed when their jobs are pruned;
- corrupted job and idempotency files create safe warnings and do not break unrelated jobs;
- legacy `build_jobs.json` imports once and is not deleted.

API tests cover:

- `Idempotency-Key` on `/jobs/build`, `/jobs/rebuild`, and compatibility aliases;
- invalid idempotency keys returning `400 INVALID_REQUEST`;
- `/jobs?limit=...&cursor=...` pagination shape and ordering;
- invalid pagination values returning `400 INVALID_REQUEST`;
- `/v1/jobs` matching unversioned route behavior;
- corruption warning summaries appearing only in safe diagnostics fields;
- failed jobs still persist typed `BUILD_FAILED` errors without raw exception text.

Configuration tests cover defaults, environment overrides, and invalid list or retention limits.

Verification starts with:

```powershell
python -m pytest tests/test_build_job_persistence.py tests/test_api_app.py -q
```

Then expands to:

```powershell
python -m pytest tests/test_configuration_defaults.py tests/test_configuration_section_loaders.py tests/test_public_api_manifest.py tests/test_module_boundary_facades.py -q
pre-commit run --all-files
python scripts/release_gate.py
```

If any environment-dependent check cannot run, the final delivery must state the exact command and
failure reason.

## Documentation

README or API operations documentation should describe:

- `Idempotency-Key` retry behavior;
- conflict behavior when a key is reused for a different operation;
- paginated `/jobs` reads and `next_cursor`;
- build-job retention configuration;
- safe corruption warning summaries and expected operator response.

`.env.example` should include the three new API configuration variables with safe defaults.

## Acceptance Criteria

- Build-job state changes no longer rewrite the full legacy `build_jobs.json` document.
- The build API supports `Idempotency-Key` for safe retry of accepted submissions.
- Reusing a key across build and rebuild returns a typed conflict.
- `/jobs` and `/v1/jobs` support bounded pagination with `next_cursor`.
- Terminal job history is pruned by a configurable retention policy while active jobs remain.
- Corrupted job or index records produce safe warnings and do not hide healthy records.
- Existing legacy job state migrates into the repository without deleting the legacy file.
- Existing public imports through `rag_modules.interfaces.api.build_job_store` continue to work.
- Focused tests, formatting, and release-sensitive checks pass or are reported with evidence.

## Self-Review

- No placeholder requirements remain.
- The storage approach stays inside the existing build API and build-job package boundaries.
- The design keeps compatibility aliases and existing public build-job payload fields stable.
- The idempotency and pagination contracts are explicit enough for implementation and tests.
- Corruption handling avoids raw file contents and raw exception details at public boundaries.
