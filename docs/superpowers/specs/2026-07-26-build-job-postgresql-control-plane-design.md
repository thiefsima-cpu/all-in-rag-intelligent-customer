# PostgreSQL Build-Job Control Plane Design

## Status

Approved for implementation on 2026-07-26.

## Context

The build-job application already depends on `BuildJobRepositoryPort`, and API/worker
composition accepts an injected repository factory. The built-in production composition still
constructs `FileBuildJobRepository`, however. That adapter is appropriate for a single machine
and a small job history, but listing, dispatch, lease recovery, retention, and diagnostics scan
JSON files under the repository directory.

This design adds a built-in PostgreSQL repository for the production control plane. The file
repository remains a supported development backend and implements the same application
semantics.

## Goals

- Make PostgreSQL the baseline production build-job repository.
- Keep the file repository as the explicit development and test backend.
- Preserve `BuildJobRepositoryPort` as the application boundary and preserve repository-factory
  injection.
- Provide indexed keyset pagination, database-enforced idempotency, atomic claim/lease behavior,
  optimistic revision checks, and an append-only audit history.
- Expose a protected, privacy-safe, paginated audit API.
- Separate operational job retention from audit retention.
- Manage PostgreSQL schema changes through explicit, versioned migrations.
- Provide an explicit, repeatable V3 file-to-PostgreSQL import with validation and dry-run.
- Fail closed when PostgreSQL is selected but its DSN, connection, or schema is invalid.

## Non-goals

- Replacing the existing runner abstraction with Celery, Temporal, or another workflow engine.
- Changing the build/rebuild HTTP submission, cancellation, retry, or job response contracts.
- Automatically migrating a database or importing file data during API/worker startup.
- Recovering file-backed history already deleted by an older retention run.
- Supporting databases other than PostgreSQL in this implementation.

## Supported Runtime

- Python remains `>=3.11,<3.12`.
- PostgreSQL 16 or newer is supported.
- The adapter uses Psycopg 3 and `psycopg_pool`; the production dependency is
  `psycopg[binary,pool]==3.3.4`, with generated lock files pinning its transitive packages.
- Repository methods remain synchronous to match the existing application port and worker model.

## Architecture

`BuildJobApplicationService` continues to depend only on `BuildJobRepositoryPort`. Composition
selects one built-in adapter from configuration unless the caller supplied a repository factory.
An injected factory remains authoritative and bypasses built-in backend construction.

The PostgreSQL implementation lives under `rag_modules/runtime/build_jobs/postgres/`. Its public
adapter owns a synchronous connection pool, transaction boundaries, database error translation,
and schema compatibility checks. Focused internal modules own row codecs, SQL operations,
migration execution, and V3 file import. Domain transitions continue to use
`reduce_build_job`; SQL code does not reproduce the state machine.

The repository port gains:

- `list_events(job_id: BuildJobId, query: BuildJobEventListQuery) -> BuildJobEventPage` for
  paginated audit access;
- `close()` for deterministic resource cleanup.

The file repository implements `close()` as a no-op and implements event pagination from V3
envelopes. `BuildJobApplicationService.shutdown()` shuts down the runner before closing the
repository.

## PostgreSQL Schema

All control-plane objects live in a dedicated `graph_rag_control_plane` PostgreSQL schema.

### `build_job_schema_migrations`

The migration ledger contains:

- integer `version` as the primary key;
- migration `name`;
- SHA-256 `checksum`;
- `applied_at` as `timestamptz`.

Migration files are immutable after release. A checksum mismatch is a schema error.

### `build_jobs`

The current projection contains:

- `job_id` as the primary key;
- `request_id`, `job_type`, `status`, and `revision`;
- `created_at`, `started_at`, and `finished_at`;
- `message`, `error`, `logs`, and `result`;
- `retry_of_job_id`;
- `idempotency_key_hash`;
- worker ID and runner backend;
- lease token and lease expiration;
- `archived_at`;
- `updated_at`.

Queryable scalar values use typed columns. `error`, `logs`, and `result` use JSONB. The adapter
reconstructs `BuildJobSnapshot` through one row codec and rejects invalid persisted values.

Constraints and indexes include:

- a unique partial index on non-empty `idempotency_key_hash`;
- a unique partial constant-expression index that allows at most one unarchived non-terminal
  task;
- an unarchived listing index on `(created_at DESC, job_id DESC)`;
- a status-filtered variant for status-aware listing;
- a queued claim index on `(created_at, job_id)`;
- an expired-lease recovery index on `lease_expires_at`;
- indexes supporting terminal retention and `archived_at` audit purging.

### `build_job_events`

The append-only audit table contains:

- `job_id`;
- `revision`;
- globally unique `event_id`;
- `event_type` and `schema_version`;
- `occurred_at`;
- `request_id`;
- JSONB `payload`.

`(job_id, revision)` is the primary key. A foreign key references `build_jobs` without automatic
cascade deletion; purge explicitly removes events before their job row. Repository operations
only insert and select event rows.

## Transaction Semantics

### Submission

Submission validates and hashes the idempotency key before opening its write transaction. The
queued projection and revision-1 event are inserted together. Named database constraints
distinguish:

- a same-key, same-type replay, which returns the existing job;
- a same-key, different-type conflict;
- another unarchived active task.

Race losers re-read the constraint owner inside a new bounded transaction and return the same
domain result as a non-racing request. Raw database exceptions do not cross the repository
boundary.

### Claim

`claim_next` selects the oldest unarchived queued row with
`FOR UPDATE SKIP LOCKED LIMIT 1`. It creates a cryptographically random lease token, reduces the
claimed event, inserts that event, and updates the projection in one transaction. Concurrent
workers cannot claim the same revision.

### Lease renewal

Renewal locks the job row and verifies job ID, lease token, worker identity, non-terminal status,
and current ownership. It updates the expiry without adding an audit event so heartbeat traffic
does not flood the event history. A stale or mismatched lease raises `BuildJobLeaseLostError`.

### Applying events

`apply` locks the current projection, verifies `expected_revision`, validates a supplied lease,
runs `reduce_build_job`, inserts the next event, and updates the projection in one transaction.
The event primary key and job revision checks prevent duplicate or out-of-order changes.

### Recovery

Expired leases are selected through the expiry index and locked with `SKIP LOCKED`. Recovery is
processed in bounded batches so multiple API/worker startup paths can recover concurrently
without one unbounded transaction. Every recovered task receives its normal interrupted event.

## Pagination

Job listing remains newest-first and includes only unarchived tasks. The existing opaque cursor
encodes `(created_at, job_id)`, and the PostgreSQL query uses a strict tuple comparison rather than
offset pagination.

Audit events are returned in ascending revision order. A new opaque cursor encodes the last
revision. The query uses `revision > cursor_revision`, orders by revision, and fetches
`bounded_limit + 1` rows to determine `next_cursor`.

Invalid cursors fail before SQL execution. The same cursor semantics are implemented by both
repositories.

## Retention

`build_job_retention_limit` continues to control how many terminal tasks remain operationally
visible. Active tasks are never archived. When the limit is exceeded:

- PostgreSQL sets `archived_at` on older terminal rows;
- the file repository moves their V3 envelopes into
  `<store-stem>.d/archive/<job-id>.json`.

Archived tasks are excluded from normal get/list/retry/cancel behavior, but their events remain
available from the audit endpoint.

`build_job_audit_retention_days`, defaulting to `90`, controls physical deletion. Retention first
deletes events and then job rows whose `archived_at` is older than the cutoff. The file repository
permanently deletes equivalent archived envelopes. The idempotency key remains reserved while the
archived job exists and becomes reusable only after physical purge, matching the lifecycle of its
authoritative job row.

## Audit API

The build API adds:

```text
GET /v1/jobs/{job_id}/events?limit=<n>&cursor=<opaque>
```

The response is:

```json
{
  "events": [
    {
      "event_id": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa:1",
      "job_id": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
      "revision": 1,
      "event_type": "queued",
      "schema_version": 1,
      "occurred_at": "2026-07-26T00:00:00+00:00",
      "request_id": "request-example",
      "payload": {}
    }
  ],
  "next_cursor": ""
}
```

Response models forbid unknown fields. The endpoint is protected by the existing fail-closed
Bearer authentication middleware.

Audit payloads use event-specific public projections:

- queued exposes job type and retry source, not the idempotency hash;
- claimed exposes worker identity and lease expiry, not the lease token;
- started exposes worker identity;
- progress, cancellation, cancellation completion, and interruption expose only established safe
  messages;
- success and failure expose safe messages and results processed by the existing public error
  sanitizer.

DSNs, SQL text, query parameters, lease tokens, idempotency hashes, and raw exception details are
never returned.

## Configuration

The configuration model adds:

- `api.build_job_repository_backend`: `"file"` or `"postgresql"`;
- `api.build_job_audit_retention_days`: positive integer, default `90`;
- `api.build_job_postgres_pool_min_size`: positive integer, default `1`;
- `api.build_job_postgres_pool_max_size`: positive integer, default `10` and not less than the
  minimum;
- `api.build_job_postgres_pool_timeout_seconds`: positive number, default `5.0`;
- `storage.build_job_postgres_dsn`: secret string excluded from repr.

The environment schema adds matching variables, including
`API_BUILD_JOB_REPOSITORY_BACKEND`, `API_BUILD_JOB_AUDIT_RETENTION_DAYS`,
`API_BUILD_JOB_POSTGRES_POOL_MIN_SIZE`, `API_BUILD_JOB_POSTGRES_POOL_MAX_SIZE`,
`API_BUILD_JOB_POSTGRES_POOL_TIMEOUT_SECONDS`, and `BUILD_JOB_POSTGRES_DSN`.

`profiles/base.toml` selects PostgreSQL. `profiles/dev.toml` explicitly selects the file backend.
Test configuration helpers explicitly select the file backend. Selecting the built-in PostgreSQL
backend with a missing DSN, unreachable database, or incompatible schema prevents API/worker
startup. There is no automatic fallback.

An injected `repository_factory` remains higher priority than built-in selection and therefore
does not require PostgreSQL configuration.

## Schema Lifecycle

The package adds a `graph-rag-build-job-db` console command with:

- `status`: connect read-only, report current/required versions, verify checksums, and exit
  non-zero when the schema is not ready;
- `migrate`: acquire a PostgreSQL advisory lock and apply pending packaged SQL migrations in order,
  one transaction per migration;
- `import-file --source <path> --dry-run`: validate V3 metadata, active and archived envelopes,
  event reduction, counts, and destination conflicts without writes;
- `import-file --source <path>`: import job IDs, projections, revisions, timestamps, events, and
  idempotency ownership.

Import is repeatable. Exact existing rows are skipped. A projection, event, or idempotency owner
that differs from the source fails closed. Import does not overwrite destination data and does
not expose either DSN or persisted payloads in errors. Runtime startup checks schema compatibility
but never runs migrations or import.

The Docker Compose file adds an optional PostgreSQL integration profile with a health check and
persistent local volume. The existing local API profile continues to use `GRAPH_RAG_PROFILE=dev`
and therefore the file backend unless the operator explicitly overrides it.

## Error Handling

Domain conflicts retain their current exceptions and HTTP 409 mapping. Missing or physically
purged audit subjects return 404. Invalid cursors map to the existing invalid-request response.

A new backend-unavailable repository error represents runtime connection, pool, or transaction
failures. The HTTP boundary maps it to a sanitized 503 response. Startup DSN, connection, and
schema failures abort startup.

Database errors are logged with a stable operation code, backend, safe outcome, and SQLSTATE class
when available. Logs and responses omit DSNs, SQL text, bound parameters, persisted JSON, and raw
exception messages.

## Diagnostics and Metrics

`BuildJobRepositoryDiagnostics` gains:

- `backend`;
- `ready`;
- `schema_version`;
- the existing warning summary.

PostgreSQL diagnostics execute only bounded connectivity and schema-version checks. They do not
count or scan job/event tables. File diagnostics retain corruption scans because that adapter is
limited to development and small repositories.

Metrics use low-cardinality labels and cover:

- repository operation duration by backend, operation, and outcome;
- claim outcomes;
- connection/transaction failures;
- numbers archived and purged.

Metrics do not label job IDs, request IDs, worker IDs, event IDs, SQL text, or SQL parameters.

## Testing

### Shared repository contract

One behavior suite covers both adapters:

- submission and idempotency replay/conflict;
- active-task exclusion;
- get and keyset listing;
- optimistic revision conflicts;
- claim, renew, stale lease rejection, and expiry recovery;
- dispatchable lookup;
- operational archive and audit purge;
- event ordering and cursor validation;
- diagnostics and close lifecycle.

### PostgreSQL integration

Tests use a real PostgreSQL 16+ service, not mocked SQL. They cover:

- concurrent same-key and different-key submissions;
- database enforcement of one active task;
- concurrent workers claiming each task at most once;
- competing revision updates;
- lease renewal and recovery races;
- transaction rollback between event and projection writes;
- migration order, checksum mismatch, and advisory-lock serialization;
- pool exhaustion/error translation and deterministic close;
- required constraints/indexes and index-compatible `EXPLAIN` plans.

### Import and API

Import tests cover dry-run zero writes, exact replay, mismatch rejection, corrupt V3 failure, and
active/archive event preservation.

API tests cover authenticated audit access, pagination, archived access, 404, invalid cursors,
sanitized 503 responses, payload redaction, and OpenAPI models. Existing build API and external
worker slices remain regression gates.

### Delivery verification

CI adds a PostgreSQL service job. Local unit tests remain database-independent; the PostgreSQL
slice runs when its dedicated test DSN is present. Before completion, run:

- focused repository/configuration tests;
- PostgreSQL integration and import tests;
- the documented API test slice;
- the complete test suite;
- Ruff/pre-commit;
- `python scripts/release_gate.py`.

## Documentation and Dependency Delivery

Update `README.md`, `.env.example`, `docs/architecture.md`,
`docs/app_composition_maintenance_guide.md`, `docs/release_process.md`, Docker Compose, and command
entrypoint documentation.

Psycopg is a production dependency because API and worker processes construct the PostgreSQL
adapter. Update `pyproject.toml`, then use `scripts/compile_locks.ps1` with Python 3.11 to regenerate
`requirements.txt` and `requirements-dev.txt`; never edit generated locks manually.

## Success Criteria

- Production baseline composition selects PostgreSQL without requiring a factory.
- Development and ordinary unit tests select the file backend explicitly.
- A misconfigured PostgreSQL backend fails closed without leaking secrets or falling back.
- Concurrent submit, claim, lease, apply, recovery, and retention operations preserve repository
  invariants.
- Job and audit pagination are keyset-based and supported by checked indexes.
- Audit events remain queryable after operational archival and disappear only after audit expiry.
- V3 file history can be validated and imported without automatic startup mutation.
- Both adapters satisfy the shared repository contract.
- PostgreSQL integration, API, full-suite, lint, and release gates pass.
