# PostgreSQL Build-Job Control Plane Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development
> (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the built-in production file-backed build-job control plane with a transactional
PostgreSQL adapter while retaining a contract-equivalent file backend for development.

**Architecture:** Keep `BuildJobApplicationService` behind `BuildJobRepositoryPort`, extend the
port with audit pagination and deterministic close, and select the concrete repository only in
composition. PostgreSQL stores indexed current projections and append-only events in one
transactional schema; the file adapter gains a development-only archive path with the same
retention and audit semantics.

**Tech Stack:** Python 3.11, Psycopg 3.3.4, psycopg-pool 3.3.1, PostgreSQL 16+, FastAPI,
Pydantic 2, pytest, Prometheus client, Docker Compose, GitHub Actions.

## Global Constraints

- Python remains `>=3.11,<3.12`.
- PostgreSQL 16 or newer is supported.
- Production baseline composition uses PostgreSQL; `dev` and ordinary unit tests explicitly use
  the file backend.
- PostgreSQL selection fails closed for missing DSN, connectivity, or schema mismatch and never
  falls back to files.
- Runtime startup validates schema but never runs DDL or imports V3 files.
- Job and event pagination use opaque keyset cursors, never offset scans.
- Idempotency hashes, lease tokens, DSNs, SQL text, parameters, and raw exceptions never enter
  public payloads, diagnostics, metrics, or logs.
- Operational retention archives excess terminal jobs; physical purge occurs only after the
  90-day default audit retention period.
- `repository_factory` remains authoritative when explicitly supplied.
- Use TDD for every behavior change: write the focused test, observe the expected failure, add the
  minimum implementation, and rerun the focused test.
- Do not hand-edit `requirements.txt` or `requirements-dev.txt`; regenerate them with
  `scripts/compile_locks.ps1` under Python 3.11.

---

## File Structure

### New production files

- `rag_modules/runtime/build_jobs/postgres/__init__.py` — concrete PostgreSQL exports.
- `rag_modules/runtime/build_jobs/postgres/repository.py` — pool ownership, row codecs,
  transaction/error boundaries, and all repository operations.
- `rag_modules/runtime/build_jobs/postgres/schema.py` — packaged migration discovery, checksum
  validation, advisory locking, status, and migration execution.
- `rag_modules/runtime/build_jobs/postgres/importer.py` — validated V3 active/archive discovery,
  dry-run reporting, exact replay, and conflict detection.
- `rag_modules/runtime/build_jobs/postgres/migrations/0001_build_job_control_plane.sql` — dedicated
  schema, tables, constraints, and indexes.
- `scripts/build_job_db.py` — `status`, `migrate`, and `import-file` command-line surface.

### New test support and tests

- `tests/build_job_repository_contract.py` — backend-neutral repository behavior mixin/helpers.
- `tests/postgres_build_job_helpers.py` — guarded real-PostgreSQL reset, migration, and repository
  fixtures.
- `tests/test_postgres_build_job_schema.py` — DDL, checksum, locking, and plan/index tests.
- `tests/test_postgres_build_job_repository.py` — PostgreSQL contract and concurrency tests.
- `tests/test_build_job_file_import.py` — dry-run, replay, mismatch, corruption, and archive import.

### Existing files changed

- Build-job contracts, application service, file repository modules, composition, configuration,
  API models/routes/services/error handlers, telemetry, profiles, package metadata, Docker/CI,
  tests, and operator documentation listed in the tasks below.

---

### Task 1: Extend the repository contract and application lifecycle

**Files:**
- Modify: `rag_modules/contracts/build_jobs/models.py`
- Modify: `rag_modules/contracts/build_jobs/events.py`
- Modify: `rag_modules/contracts/build_jobs/errors.py`
- Modify: `rag_modules/contracts/build_jobs/ports.py`
- Modify: `rag_modules/contracts/build_jobs/__init__.py`
- Modify: `rag_modules/app/build_jobs/service.py`
- Test: `tests/test_build_job_domain.py`
- Test: `tests/test_build_job_application.py`

**Interfaces:**
- Produces:
  `BuildJobEventListQuery(limit: int | None, cursor: str)`,
  `BuildJobEventPage(events: tuple[BuildJobEvent, ...], next_cursor: str)`,
  `BuildJobRepositoryUnavailableError`,
  `public_build_job_event(event) -> JsonObject`,
  `BuildJobRepositoryPort.list_events(...)`, and `BuildJobRepositoryPort.close()`.
- Consumes: existing `BuildJobEvent`, `BuildJobId`, and `BuildJobApplicationService`.

- [ ] **Step 1: Write failing contract and public-projection tests**

Add tests that require the new port methods, DTOs, diagnostics fields, and redaction:

```python
def test_build_job_repository_port_includes_audit_and_close() -> None:
    methods = {name for name, value in vars(BuildJobRepositoryPort).items() if callable(value)}
    assert {"list_events", "close"} <= methods


def test_public_claim_event_omits_lease_token() -> None:
    event = BuildJobEvent(
        event_id=f"{'a' * 32}:2",
        job_id=BuildJobId("a" * 32),
        revision=2,
        event_type=BuildJobEventType.CLAIMED,
        schema_version=1,
        occurred_at=NOW,
        request_id="request-a",
        payload=JobClaimed(
            worker=WorkerIdentity("worker-1", "external_worker"),
            lease_token="private-lease-token",
            lease_expires_at=NOW,
        ),
    )
    public = public_build_job_event(event)
    assert public["payload"] == {
        "worker": {"worker_id": "worker-1", "runner_backend": "external_worker"},
        "lease_expires_at": NOW.isoformat(),
    }
    assert "private-lease-token" not in json.dumps(public)
```

Update the application fake repository with `list_events` and `close`, then require audit
delegation and shutdown order:

```python
page = service.list_events(BuildJobId("1" * 32), limit=10, cursor="")
service.shutdown()
assert page.events == repository.events
assert calls[-2:] == [("runner.shutdown",), ("repository.close",)]
```

- [ ] **Step 2: Run the focused tests and confirm RED**

Run:

```powershell
python -m pytest tests/test_build_job_domain.py tests/test_build_job_application.py -q
```

Expected: failures because the audit DTOs, projection, port methods, diagnostics metadata, and
repository close delegation do not exist.

- [ ] **Step 3: Add the contract models and safe projection**

Add to `models.py`:

```python
@dataclass(frozen=True, slots=True)
class BuildJobEventListQuery:
    limit: int | None = None
    cursor: str = ""


@dataclass(frozen=True, slots=True)
class BuildJobEventPage:
    events: tuple[BuildJobEvent, ...]
    next_cursor: str = ""


@dataclass(frozen=True, slots=True)
class BuildJobRepositorySettings:
    retention_limit: int = 100
    list_default_limit: int = 50
    list_max_limit: int = 100
    lease_seconds: float = 30.0
    audit_retention_days: int = 90


@dataclass(frozen=True, slots=True)
class BuildJobRepositoryDiagnostics:
    backend: str = "unknown"
    ready: bool = True
    schema_version: str = ""
    warnings: tuple[BuildJobRepositoryWarning, ...] = field(default_factory=tuple)
```

Use `TYPE_CHECKING` for the `BuildJobEvent` annotation to avoid an events/models import cycle.
Extend `to_public_dict()` with `backend`, `ready`, and `schema_version`.

Add `BuildJobRepositoryUnavailableError(BuildJobRepositoryError)` to `errors.py`.

In `events.py`, implement `public_build_job_event()` with an explicit `isinstance` branch for every
payload class. Expose job type/retry source for queued, worker/expiry without token for claimed,
worker for started, established safe messages for progress/cancellation/interruption, and safe
message/result for terminal events. Never call `event_to_dict()` and then subtract secrets.

- [ ] **Step 4: Extend the port and application service**

Add exact methods:

```python
def list_events(
    self,
    job_id: BuildJobId,
    query: BuildJobEventListQuery,
) -> BuildJobEventPage: ...

def close(self) -> None: ...
```

Add to `BuildJobApplicationService`:

```python
def list_events(
    self,
    job_id: BuildJobId,
    *,
    limit: int | None = None,
    cursor: str = "",
) -> BuildJobEventPage:
    return self._repository.list_events(
        job_id,
        BuildJobEventListQuery(
            limit=limit or self._repository.list_default_limit,
            cursor=cursor,
        ),
    )

def shutdown(self) -> None:
    self._runner.shutdown()
    self._repository.close()
```

Export every new symbol from the contract and application packages.

- [ ] **Step 5: Run GREEN tests**

Run:

```powershell
python -m pytest tests/test_build_job_domain.py tests/test_build_job_application.py -q
```

Expected: all focused tests pass.

- [ ] **Step 6: Commit**

```powershell
git add rag_modules/contracts/build_jobs rag_modules/app/build_jobs tests/test_build_job_domain.py tests/test_build_job_application.py
git commit -m "feat: extend build job repository audit contract"
```

---

### Task 2: Give the file backend archive and audit parity

**Files:**
- Modify: `rag_modules/runtime/build_jobs/file_repository.py`
- Modify: `rag_modules/runtime/build_jobs/file_repository_codecs.py`
- Modify: `rag_modules/runtime/build_jobs/file_repository_storage.py`
- Modify: `rag_modules/runtime/build_jobs/file_repository_idempotency.py`
- Modify: `rag_modules/runtime/build_jobs/file_repository_operations.py`
- Modify: `rag_modules/runtime/build_jobs/file_repository_diagnostics.py`
- Test: `tests/build_job_repository_contract.py`
- Modify: `tests/test_build_job_repository_port.py`
- Modify: `tests/test_build_job_repository_recovery_retention.py`

**Interfaces:**
- Consumes: Task 1 audit DTOs and port methods.
- Produces: file-backed keyset event pagination, archive lookup, 90-day physical purge, and no-op
  close.

- [ ] **Step 1: Extract a shared repository behavior suite and write RED archive tests**

Move backend-neutral assertions from `test_build_job_repository_port.py` into a mixin whose
subclass supplies `make_repository(clock, settings)`. Keep file-format/corruption assertions in
their existing file-specific test modules.

Add this retention assertion:

```python
oldest = submit_and_succeed(repository, "1" * 32, clock=clock, key="key-1")
clock.advance(seconds=1)
submit_and_succeed(repository, "2" * 32, clock=clock, key="key-2")

assert repository.get(oldest.job_id) is None
events = repository.list_events(oldest.job_id, BuildJobEventListQuery(limit=2))
assert [event.revision for event in events.events] == [1, 2]
assert (root / "build_jobs.d" / "archive" / f"{oldest.job_id}.json").exists()

clock.advance(seconds=90 * 86400)
repository.apply_retention()
with pytest.raises(BuildJobNotFoundError):
    repository.list_events(oldest.job_id, BuildJobEventListQuery())
```

Also test invalid event cursors and ensure archived idempotency replays the original job until
physical purge. Add a shared lease assertion that renewal after `lease_expires_at` raises
`BuildJobLeaseLostError` so both adapters implement the same ownership rule.

- [ ] **Step 2: Run the file repository slice and confirm RED**

Run:

```powershell
python -m pytest tests/test_build_job_repository_port.py tests/test_build_job_repository_recovery_retention.py -q
```

Expected: failures because retention deletes envelopes/idempotency records and no event cursor or
archive lookup exists.

- [ ] **Step 3: Add event cursors and archive storage primitives**

In `file_repository_codecs.py`, add base64 JSON event cursors containing only `revision`:

```python
def encode_event_cursor(revision: int) -> str:
    payload = json.dumps({"revision": int(revision)}, separators=(",", ":"))
    return base64.urlsafe_b64encode(payload.encode("utf-8")).decode("ascii")


def decode_event_cursor(cursor: str) -> int:
    if not cursor:
        return 0
    # Decode, require exactly {"revision"}, and require a non-negative integer.
```

In storage, create `archive_dir`, add `archived_job_path`, `archived_at_path`, and
`load_any_envelope`. Archive with `os.replace(active_path, archive_path)` and write the timestamp
sidecar atomically as `<job-id>.archived-at`. Loading normal jobs must never consult the archive;
idempotency and event lookup may consult both.

- [ ] **Step 4: Replace deletion retention with archive then purge**

Change `apply_retention()` to:

1. sort active terminal snapshots newest-first;
2. move rows beyond `retention_limit` into archive and write `repository._now().isoformat()`;
3. retain idempotency indexes for archived jobs;
4. remove archive envelope, timestamp, lease residue, and idempotency indexes only when
   `archived_at <= now - timedelta(days=audit_retention_days)`.

Implement `list_events()` by loading active or archived envelope, decoding the event cursor,
selecting events with greater revision, applying `list_max_limit`, and fetching one extra event
to compute `next_cursor`. Raise `BuildJobNotFoundError` when neither location exists.

Update `renew_lease()` to reject a lease whose stored expiry is less than or equal to
`repository._now()`. Scan both active and archive directories for corruption diagnostics, using
the same safe warning shape and never including file contents.

Return explicit file diagnostics:

```python
BuildJobRepositoryDiagnostics(
    backend="file",
    ready=True,
    schema_version=str(BUILD_JOB_ENVELOPE_SCHEMA_VERSION),
    warnings=tuple(repository._warnings),
)
```

Implement `close()` as an empty method.

- [ ] **Step 5: Run GREEN and file-specific regression tests**

Run:

```powershell
python -m pytest tests/test_build_job_repository_port.py tests/test_build_job_repository_records.py tests/test_build_job_repository_idempotency.py tests/test_build_job_repository_recovery_retention.py tests/test_build_job_migration.py -q
```

Expected: all pass with operationally archived jobs absent from get/list but still available to
event lookup.

- [ ] **Step 6: Commit**

```powershell
git add rag_modules/runtime/build_jobs tests/build_job_repository_contract.py tests/test_build_job_repository_port.py tests/test_build_job_repository_recovery_retention.py
git commit -m "feat: add file build job audit archive"
```

---

### Task 3: Add repository configuration and Psycopg dependencies

**Files:**
- Modify: `rag_modules/configuration/models.py`
- Modify: `rag_modules/configuration/environment_schema.py`
- Modify: `profiles/base.toml`
- Modify: `profiles/dev.toml`
- Modify: `tests/configuration_test_helpers.py`
- Modify: `tests/test_configuration_defaults.py`
- Modify: `tests/test_configuration_section_loaders.py`
- Modify: `tests/test_configuration_profiles.py`
- Modify: `pyproject.toml`
- Regenerate: `requirements.txt`
- Regenerate: `requirements-dev.txt`

**Interfaces:**
- Produces exact repository backend, audit retention, pool, and DSN settings.
- Consumes: no PostgreSQL implementation yet.

- [ ] **Step 1: Write failing configuration tests**

Add assertions:

```python
base = load_config(source=EnvConfigSource(environ={}))
dev = load_config(source=EnvConfigSource(environ={}), profile="dev")
test_config = build_test_config()

assert base.api.build_job_repository_backend == "postgresql"
assert dev.api.build_job_repository_backend == "file"
assert test_config.api.build_job_repository_backend == "file"
assert base.api.build_job_audit_retention_days == 90
assert base.api.build_job_postgres_pool_min_size == 1
assert base.api.build_job_postgres_pool_max_size == 10
assert base.api.build_job_postgres_pool_timeout_seconds == 5.0
```

Test all environment variables and reject `pool_min_size > pool_max_size`. Set a secret DSN and
assert it is absent from `repr(config)` and replaced with `"***"` in `config.to_dict()`.

- [ ] **Step 2: Run configuration tests and confirm RED**

Run:

```powershell
python -m pytest tests/test_configuration_defaults.py tests/test_configuration_section_loaders.py tests/test_configuration_profiles.py -q
```

Expected: unknown-field and missing-attribute failures for the new configuration.

- [ ] **Step 3: Implement strict settings and profile selection**

Add to `ApiSettings`:

```python
build_job_repository_backend: Literal["file", "postgresql"] = "file"
build_job_audit_retention_days: int = Field(default=90, ge=1)
build_job_postgres_pool_min_size: int = Field(default=1, ge=1)
build_job_postgres_pool_max_size: int = Field(default=10, ge=1)
build_job_postgres_pool_timeout_seconds: float = Field(default=5.0, gt=0.0)
```

Extend its validator to reject a pool maximum below the minimum. Add to `StorageSettings`:

```python
build_job_postgres_dsn: str = Field(default="", repr=False)
```

Redact `storage.build_job_postgres_dsn` in `GraphRAGConfig.to_dict()`. Add the six environment
mappings defined by the spec. Set `profiles/base.toml` to `postgresql`, `profiles/dev.toml` to
`file`, and make `build_test_config()` always override the backend to `file`.

- [ ] **Step 4: Add and lock the runtime dependency**

Add:

```toml
"psycopg[binary,pool]==3.3.4",
```

to `[project].dependencies`, then run:

```powershell
.\scripts\compile_locks.ps1 -Python python
python -c "import psycopg, psycopg_pool; print(psycopg.__version__)"
```

Expected: import succeeds and prints `3.3.4`; generated locks include compatible
`psycopg-binary` and `psycopg-pool==3.3.1`.

- [ ] **Step 5: Run GREEN configuration tests**

Run:

```powershell
python -m pytest tests/test_configuration_defaults.py tests/test_configuration_section_loaders.py tests/test_configuration_profiles.py -q
```

Expected: all pass.

- [ ] **Step 6: Commit**

```powershell
git add rag_modules/configuration profiles tests/configuration_test_helpers.py tests/test_configuration_defaults.py tests/test_configuration_section_loaders.py tests/test_configuration_profiles.py pyproject.toml requirements.txt requirements-dev.txt
git commit -m "feat: configure PostgreSQL build job repository"
```

---

### Task 4: Add versioned PostgreSQL schema management and CLI

**Files:**
- Create: `rag_modules/runtime/build_jobs/postgres/__init__.py`
- Create: `rag_modules/runtime/build_jobs/postgres/schema.py`
- Create: `rag_modules/runtime/build_jobs/postgres/migrations/0001_build_job_control_plane.sql`
- Create: `scripts/build_job_db.py`
- Modify: `pyproject.toml`
- Modify: `tests/test_entrypoints.py`
- Create: `tests/postgres_build_job_helpers.py`
- Create: `tests/test_postgres_build_job_schema.py`
- Modify: `tests/test_abstraction_ratchets.py`

**Interfaces:**
- Produces:
  `BuildJobPostgresSchemaStatus(current_version: int, required_version: int,
  pending_versions: tuple[int, ...], ready: bool)`,
  `PostgresBuildJobSchemaManager.status()`,
  `migrate()`, and `verify()`.
- Consumes: Task 3 DSN and Psycopg dependencies.

- [ ] **Step 1: Write failing schema and entrypoint tests**

Guard destructive test reset with both `BUILD_JOB_TEST_POSTGRES_DSN` and
`BUILD_JOB_TEST_ALLOW_RESET=1`; otherwise skip the PostgreSQL module. Add tests that:

- `status()` reports version `0` on an empty test database without creating schema;
- `migrate()` reaches version `1`, and `verify()` succeeds;
- a second migrate is a no-op;
- modifying a loaded migration checksum in memory makes `verify()` fail;
- two concurrent `migrate()` calls serialize and record one ledger row;
- the console entrypoint maps to `scripts.build_job_db:main`.

Example:

```python
def test_migrate_is_repeatable(postgres_dsn: str) -> None:
    manager = PostgresBuildJobSchemaManager(postgres_dsn)
    first = manager.migrate()
    second = manager.migrate()
    assert first.current_version == 1
    assert second.current_version == 1
    assert second.pending_versions == ()
```

- [ ] **Step 2: Run the schema tests and confirm RED**

Run:

```powershell
python -m pytest tests/test_entrypoints.py tests/test_postgres_build_job_schema.py -q
```

Expected: entrypoint assertion fails and PostgreSQL imports fail because schema management does not
exist.

- [ ] **Step 3: Add the packaged migration**

Create the dedicated schema and tables using this shape:

```sql
CREATE SCHEMA IF NOT EXISTS graph_rag_control_plane;

CREATE TABLE graph_rag_control_plane.build_jobs (
    job_id text PRIMARY KEY CHECK (job_id ~ '^[0-9a-f]{32}$'),
    request_id text NOT NULL,
    job_type text NOT NULL CHECK (job_type IN ('build', 'rebuild')),
    status text NOT NULL CHECK (
        status IN (
            'queued', 'claimed', 'running', 'cancel_requested',
            'succeeded', 'failed', 'cancelled', 'interrupted'
        )
    ),
    revision integer NOT NULL CHECK (revision >= 1),
    created_at timestamptz NOT NULL,
    started_at timestamptz,
    finished_at timestamptz,
    message text NOT NULL DEFAULT '',
    error jsonb,
    logs jsonb NOT NULL DEFAULT '[]'::jsonb CHECK (jsonb_typeof(logs) = 'array'),
    result jsonb,
    retry_of_job_id text CHECK (
        retry_of_job_id IS NULL OR retry_of_job_id ~ '^[0-9a-f]{32}$'
    ),
    idempotency_key_hash text NOT NULL DEFAULT '',
    worker_id text,
    runner_backend text,
    lease_token text NOT NULL DEFAULT '',
    lease_expires_at timestamptz,
    archived_at timestamptz,
    updated_at timestamptz NOT NULL
);

CREATE TABLE graph_rag_control_plane.build_job_events (
    job_id text NOT NULL REFERENCES graph_rag_control_plane.build_jobs(job_id),
    revision integer NOT NULL CHECK (revision >= 1),
    event_id text NOT NULL UNIQUE,
    event_type text NOT NULL CHECK (
        event_type IN (
            'queued', 'claimed', 'started', 'progress_recorded',
            'cancellation_requested', 'cancelled', 'succeeded', 'failed', 'interrupted'
        )
    ),
    schema_version integer NOT NULL,
    occurred_at timestamptz NOT NULL,
    request_id text NOT NULL,
    payload jsonb NOT NULL CHECK (jsonb_typeof(payload) = 'object'),
    PRIMARY KEY (job_id, revision)
);

CREATE UNIQUE INDEX build_jobs_idempotency_uq
    ON graph_rag_control_plane.build_jobs (idempotency_key_hash)
    WHERE idempotency_key_hash <> '';
CREATE UNIQUE INDEX build_jobs_one_active_uq
    ON graph_rag_control_plane.build_jobs ((true))
    WHERE archived_at IS NULL
      AND status IN ('queued', 'claimed', 'running', 'cancel_requested');
CREATE INDEX build_jobs_list_idx
    ON graph_rag_control_plane.build_jobs (created_at DESC, job_id DESC)
    WHERE archived_at IS NULL;
CREATE INDEX build_jobs_status_list_idx
    ON graph_rag_control_plane.build_jobs (status, created_at DESC, job_id DESC)
    WHERE archived_at IS NULL;
CREATE INDEX build_jobs_claim_idx
    ON graph_rag_control_plane.build_jobs (created_at, job_id)
    WHERE archived_at IS NULL AND status = 'queued';
CREATE INDEX build_jobs_lease_expiry_idx
    ON graph_rag_control_plane.build_jobs (lease_expires_at, job_id)
    WHERE archived_at IS NULL
      AND status IN ('claimed', 'running', 'cancel_requested');
CREATE INDEX build_jobs_terminal_retention_idx
    ON graph_rag_control_plane.build_jobs (finished_at DESC, job_id DESC)
    WHERE archived_at IS NULL
      AND status IN ('succeeded', 'failed', 'cancelled', 'interrupted');
CREATE INDEX build_jobs_archive_purge_idx
    ON graph_rag_control_plane.build_jobs (archived_at, job_id)
    WHERE archived_at IS NOT NULL;
```

Add package data:

```toml
"rag_modules.runtime.build_jobs.postgres" = ["migrations/*.sql"]
```

- [ ] **Step 4: Implement the schema manager**

Discover `NNNN_name.sql` through `importlib.resources`, calculate SHA-256, and sort by integer
version. `status()` uses catalog queries only and does not create objects. `migrate()`:

1. opens one direct Psycopg connection;
2. obtains session advisory lock `(424902026, 1)`;
3. creates the dedicated schema and migration ledger if absent;
4. rejects recorded checksum differences;
5. runs each pending SQL file and ledger insert in one transaction;
6. unlocks in `finally`.

`verify()` raises `BuildJobRepositoryError("Build job PostgreSQL schema is not ready.")` unless the
current version and every checksum match. Error messages must not interpolate the DSN or raw
database exception.

- [ ] **Step 5: Implement `status` and `migrate` CLI commands**

Use `argparse` subparsers. Read DSN from `BUILD_JOB_POSTGRES_DSN` through `load_config()` and print
JSON only when `--json` is supplied. Return `0` for ready/success, `1` for not ready or failed.
Register:

```toml
graph-rag-build-job-db = "scripts.build_job_db:main"
```

- [ ] **Step 6: Update and verify structural ratchets**

The new `postgres` package adds four production Python files. Change
`MAX_PRODUCTION_PYTHON_FILES` from `379` to `383`; do not change protocol, `Any`, or short-module
ratchets. The later repository and importer tasks consume the reserved file count without another
ratchet change.

Run:

```powershell
python -m pytest tests/test_entrypoints.py tests/test_postgres_build_job_schema.py tests/test_abstraction_ratchets.py -q
```

Expected: all pass against the guarded test database.

- [ ] **Step 7: Commit**

```powershell
git add rag_modules/runtime/build_jobs/postgres scripts/build_job_db.py pyproject.toml tests/postgres_build_job_helpers.py tests/test_postgres_build_job_schema.py tests/test_entrypoints.py tests/test_abstraction_ratchets.py
git commit -m "feat: add build job PostgreSQL schema management"
```

---

### Task 5: Implement PostgreSQL submission, reads, and audit pagination

**Files:**
- Create: `rag_modules/runtime/build_jobs/postgres/repository.py`
- Modify: `rag_modules/runtime/build_jobs/postgres/__init__.py`
- Create: `tests/test_postgres_build_job_repository.py`
- Modify: `tests/build_job_repository_contract.py`

**Interfaces:**
- Produces:
  `PostgresBuildJobRepository(dsn, now, settings, pool_min_size, pool_max_size,
  pool_timeout_seconds)`.
- Consumes: Tasks 1, 3, and 4 contracts/config/schema.

- [ ] **Step 1: Write failing basic and race tests**

Subclass the shared contract suite with a migrated real database fixture. Add:

```python
def test_same_idempotency_key_race_returns_one_job(repository_factory) -> None:
    commands = [
        SubmitBuildJob(
            job_id=BuildJobId(character * 32),
            request_id=f"request-{character}",
            job_type=BuildJobType.BUILD,
            idempotency_key="stable-race-key",
        )
        for character in ("a", "b")
    ]
    with ThreadPoolExecutor(max_workers=2) as executor:
        submissions = list(executor.map(repository_factory().submit, commands))
    assert len({item.snapshot.job_id for item in submissions}) == 1
    assert {item.disposition for item in submissions} == {
        BuildJobSubmissionDisposition.CREATED,
        BuildJobSubmissionDisposition.REPLAYED,
    }
```

Also require:

- same key/different type raises idempotency conflict;
- different keys racing for the active slot produce one created and one active conflict;
- get/list use row values exactly;
- event pages are revision-ordered and reject invalid cursors;
- archived rows are absent from get/list but still satisfy event lookup;
- captured repository logs contain a stable operation/backend/SQLSTATE-class record but do not
  contain a secret embedded in the DSN, SQL parameters, or raw exception message.

- [ ] **Step 2: Run PostgreSQL repository tests and confirm RED**

Run:

```powershell
python -m pytest tests/test_postgres_build_job_repository.py -q
```

Expected: import failure because the repository does not exist.

- [ ] **Step 3: Implement pool lifecycle, codecs, and error translation**

Open `psycopg_pool.ConnectionPool` with `open=False`, then `open(wait=True)` using the configured
timeout. Call `PostgresBuildJobSchemaManager.verify()` before accepting work. `close()` is
idempotent.

Implement one `_snapshot_from_row()` and one `_snapshot_values()` covering every
`BuildJobSnapshot` field. Use Psycopg JSON adapters for JSONB and `event_to_dict()` /
`event_from_dict()` for event payload integrity. Wrap operational/database failures as
`BuildJobRepositoryUnavailableError("Build job repository is unavailable.")`.

Log database failures with a constant message and structured `backend`, `operation`, and
two-character SQLSTATE class. Do not pass `exc_info`, DSN, SQL, parameters, persisted JSON, or
`str(exc)` to the logger.

- [ ] **Step 4: Implement submit with named-constraint race handling**

Within a transaction:

1. query `idempotency_key_hash` first;
2. return replay or raise type conflict when present;
3. reduce `new_queued_event`;
4. insert projection and event.

Catch `UniqueViolation` by exact constraint/index name:

- `build_jobs_idempotency_uq`: retry the idempotency lookup in a new transaction;
- `build_jobs_one_active_uq`: read the active projection and raise `BuildJobConflictError`;
- anything else: translate to repository unavailable.

Never retry an unclassified database failure.

- [ ] **Step 5: Implement get/list/event keyset queries**

Use:

```sql
SELECT
    job_id, request_id, job_type, status, revision,
    created_at, started_at, finished_at, message, error, logs, result,
    retry_of_job_id, idempotency_key_hash, worker_id, runner_backend,
    lease_token, lease_expires_at, archived_at
FROM graph_rag_control_plane.build_jobs
WHERE archived_at IS NULL
  AND (
      %(cursor_created_at)s IS NULL
      OR (created_at, job_id) < (%(cursor_created_at)s, %(cursor_job_id)s)
  )
ORDER BY created_at DESC, job_id DESC
LIMIT %(fetch_limit)s
```

Use a separate static status-filtered statement with
`WHERE archived_at IS NULL AND status = %(status)s`; do not use a nullable-status `OR`, because it
would make use of `build_jobs_status_list_idx` plan-dependent.

Event query:

```sql
SELECT event_id, job_id, revision, event_type, schema_version, occurred_at, request_id, payload
FROM graph_rag_control_plane.build_job_events
WHERE job_id = %(job_id)s AND revision > %(cursor_revision)s
ORDER BY revision
LIMIT %(fetch_limit)s
```

Check subject existence separately so missing/purged jobs raise `BuildJobNotFoundError` while an
existing job with zero events is treated as corruption.

- [ ] **Step 6: Run GREEN basic and race tests**

Run:

```powershell
python -m pytest tests/test_postgres_build_job_repository.py -k "submission or idempotency or list or event" -q
```

Expected: selected tests pass.

- [ ] **Step 7: Commit**

```powershell
git add rag_modules/runtime/build_jobs/postgres tests/test_postgres_build_job_repository.py tests/build_job_repository_contract.py
git commit -m "feat: persist build job projections and audit events in PostgreSQL"
```

---

### Task 6: Complete atomic claim, lease, recovery, and retention

**Files:**
- Modify: `rag_modules/runtime/build_jobs/postgres/repository.py`
- Modify: `tests/test_postgres_build_job_repository.py`
- Modify: `tests/test_postgres_build_job_schema.py`

**Interfaces:**
- Consumes: Task 5 repository.
- Produces: the complete `BuildJobRepositoryPort` implementation and indexed retention behavior.

- [ ] **Step 1: Write failing concurrency and rollback tests**

Add real-database tests for:

- two workers racing `claim_next` never receive the same job;
- stale token, wrong worker, and expired lease fail;
- competing applies at one revision produce one success and one concurrent-update error;
- an injected failure between event insert and projection update rolls the event back;
- two recovery callers interrupt an expired task once;
- operational retention archives only excess terminal rows;
- audit expiry deletes events then jobs;
- `find_dispatchable(limit)` returns ordered queued IDs;
- `EXPLAIN (FORMAT JSON)` can use each migration index when `enable_seqscan=off`.

Install a temporary test-database trigger that rejects projection updates after the repository
has inserted an event:

```sql
CREATE FUNCTION graph_rag_control_plane.reject_projection_update()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'forced projection update failure';
END;
$$;
CREATE TRIGGER reject_projection_update
BEFORE UPDATE ON graph_rag_control_plane.build_jobs
FOR EACH ROW EXECUTE FUNCTION graph_rag_control_plane.reject_projection_update();
```

Then assert the real transaction rolls back both statements:

```python
with pytest.raises(BuildJobRepositoryUnavailableError):
    repository.apply(event, expected_revision=snapshot.revision, lease=lease)
assert repository.get(snapshot.job_id).revision == snapshot.revision
assert revisions(repository, snapshot.job_id) == tuple(range(1, snapshot.revision + 1))
```

Drop the trigger and function in `finally`.

- [ ] **Step 2: Run the focused concurrency tests and confirm RED**

Run:

```powershell
python -m pytest tests/test_postgres_build_job_repository.py -k "claim or lease or apply or recover or retention or rollback" -q
```

Expected: missing-method or `NotImplementedError` failures.

- [ ] **Step 3: Implement claim and lease operations**

Claim with:

```sql
SELECT
    job_id, request_id, job_type, status, revision,
    created_at, started_at, finished_at, message, error, logs, result,
    retry_of_job_id, idempotency_key_hash, worker_id, runner_backend,
    lease_token, lease_expires_at, archived_at
FROM graph_rag_control_plane.build_jobs
WHERE archived_at IS NULL AND status = 'queued'
ORDER BY created_at, job_id
FOR UPDATE SKIP LOCKED
LIMIT 1
```

Reduce and persist the claimed event/projection in the same transaction. Renewal selects the row
`FOR UPDATE`, checks token, worker ID/backend, non-terminal status, and `lease_expires_at > now`;
then it updates only lease expiry and `updated_at`.

- [ ] **Step 4: Implement atomic apply and recovery**

`apply()` selects the row `FOR UPDATE`, checks exact revision, validates a supplied unexpired
lease, reduces the event, inserts it, invokes the optional rollback test hook, and updates all
projection fields. Terminal states clear lease fields.

Recovery loops in batches of 100 over indexed expired rows with `FOR UPDATE SKIP LOCKED`, adds an
interrupted event for each, and commits each batch. Stop when a batch contains fewer than 100.

- [ ] **Step 5: Implement retention and bounded diagnostics**

Archive excess terminal rows with a windowed CTE ordered by
`COALESCE(finished_at, created_at) DESC, job_id DESC`. Set `archived_at` without deleting events.
Purge with:

```sql
SELECT job_id
FROM graph_rag_control_plane.build_jobs
WHERE archived_at <= %(cutoff)s
ORDER BY archived_at, job_id
FOR UPDATE SKIP LOCKED
LIMIT 100;

DELETE FROM graph_rag_control_plane.build_job_events
WHERE job_id = ANY(%(expired_job_ids)s);

DELETE FROM graph_rag_control_plane.build_jobs
WHERE job_id = ANY(%(expired_job_ids)s);
```

Fetch the locked IDs from the first statement and execute both deletes in the same transaction.
The public `apply_retention()` owns a transaction, while `submit()`, terminal `apply()`, and
recovery call the same private retention function with their current connection so no nested pool
checkout or transaction occurs.

Diagnostics runs only `SELECT 1` and schema verification. A healthy result reports backend
`postgresql`, ready `true`, and version `1`. A runtime connectivity failure returns ready `false`
with a safe `BUILD_JOB_POSTGRES_UNAVAILABLE` warning; it does not scan tables or include the raw
database exception.

- [ ] **Step 6: Run the full PostgreSQL repository and schema slices**

Run:

```powershell
python -m pytest tests/test_postgres_build_job_repository.py tests/test_postgres_build_job_schema.py -q
```

Expected: all pass, including concurrency and plan/index assertions.

- [ ] **Step 7: Commit**

```powershell
git add rag_modules/runtime/build_jobs/postgres/repository.py tests/test_postgres_build_job_repository.py tests/test_postgres_build_job_schema.py
git commit -m "feat: add atomic PostgreSQL build job leases and retention"
```

---

### Task 7: Add repeatable V3 file import

**Files:**
- Create: `rag_modules/runtime/build_jobs/postgres/importer.py`
- Modify: `rag_modules/runtime/build_jobs/postgres/__init__.py`
- Modify: `scripts/build_job_db.py`
- Create: `tests/test_build_job_file_import.py`

**Interfaces:**
- Produces:
  `BuildJobImportReport(scanned_jobs, scanned_events, imported_jobs, skipped_jobs, conflicts,
  dry_run)` and `V3BuildJobImporter.run(source_path, dry_run)`.
- Consumes: V3 serializers, file archive layout, PostgreSQL pool/schema.

- [ ] **Step 1: Write failing import tests**

Create a file repository with active and archived jobs, then assert:

```python
dry_report = importer.run(source_path, dry_run=True)
assert dry_report.scanned_jobs == 2
assert postgres_job_count() == 0

first = importer.run(source_path, dry_run=False)
second = importer.run(source_path, dry_run=False)
assert first.imported_jobs == 2
assert second.skipped_jobs == 2
assert postgres_event_revisions(archived_id) == (1, 2, 3)
```

Also test mismatched destination projection/event/idempotency owner, corrupt metadata/envelope,
and CLI JSON output. Every conflict must leave the database unchanged.

- [ ] **Step 2: Run import tests and confirm RED**

Run:

```powershell
python -m pytest tests/test_build_job_file_import.py -q
```

Expected: importer and `import-file` subcommand do not exist.

- [ ] **Step 3: Implement validated discovery and dry-run**

Resolve a source `build_jobs.json` to `<stem>.d`, require valid V3 metadata, read active
`jobs/*.json`, archived `archive/*.json`, and archived timestamp sidecars. Parse every envelope
with `envelope_from_dict()` so reducer validation runs before any destination write.

Dry-run opens a read transaction, compares all source rows/events/idempotency ownership, builds a
report, and rolls back. It must not call retention.

- [ ] **Step 4: Implement exact replay and conflict behavior**

In one transaction for the complete import:

- insert absent job projection plus all events;
- skip only when every projection field, archived timestamp, and event dictionary matches;
- fail on an event revision gap, differing payload, differing projection, or idempotency owner;
- preserve source job IDs, event IDs, revisions, timestamps, and archive status.

Wrap errors with stable messages that contain job ID and revision only, never payload or DSN.

- [ ] **Step 5: Add `import-file` CLI**

Add `--source`, `--dry-run`, and `--json`; load runtime DSN from configuration, verify schema, run
the importer, and return `1` on validation/conflict. Human output contains counts only.

- [ ] **Step 6: Run GREEN import tests**

Run:

```powershell
python -m pytest tests/test_build_job_file_import.py tests/test_entrypoints.py -q
```

Expected: all pass.

- [ ] **Step 7: Commit**

```powershell
git add rag_modules/runtime/build_jobs/postgres/importer.py rag_modules/runtime/build_jobs/postgres/__init__.py scripts/build_job_db.py tests/test_build_job_file_import.py
git commit -m "feat: import V3 build job history into PostgreSQL"
```

---

### Task 8: Select PostgreSQL in built-in production composition

**Files:**
- Modify: `rag_modules/runtime/build_jobs/__init__.py`
- Modify: `rag_modules/app/composition/build_jobs.py`
- Modify: `rag_modules/runtime/build_jobs/external_worker_runner.py`
- Modify: `tests/test_build_job_composition.py`
- Modify: `tests/test_build_job_persistence.py`
- Modify: `tests/test_build_job_external_worker.py`
- Modify: `tests/test_abstraction_ratchets.py`

**Interfaces:**
- Consumes: Task 3 configuration and Task 6 complete repository.
- Produces: production/backend composition with factory priority and fail-closed startup.

- [ ] **Step 1: Write failing composition tests**

Test:

```python
def test_factory_precedes_postgresql_validation() -> None:
    config = build_test_config().with_overrides(
        {
            "api": {"build_job_repository_backend": "postgresql"},
            "storage": {"build_job_postgres_dsn": ""},
        }
    )
    repository = CompleteRecordingRepository()
    service = compose_build_job_application(
        system=cast(GraphRAGApplication, object()),
        config=config,
        coordinator=RuntimeOperationCoordinator(),
        repository_factory=lambda _: repository,
    )
    assert service.diagnostics() == repository.diagnostics()
```

Also test built-in file selection, built-in PostgreSQL constructor arguments, missing DSN
fail-closed, unsupported backend validation, and external worker shutdown closing its repository
exactly once. Patch the runtime module constructor rather than opening PostgreSQL in unit tests.

- [ ] **Step 2: Run composition tests and confirm RED**

Run:

```powershell
python -m pytest tests/test_build_job_composition.py tests/test_build_job_persistence.py -q
```

Expected: PostgreSQL backend is ignored and file repository is always constructed.

- [ ] **Step 3: Export and compose the PostgreSQL adapter**

Add `PostgresBuildJobRepository` to runtime exports and `_RuntimeBuildJobsModule` as a
`Callable[..., BuildJobRepositoryPort]`, avoiding a new composition protocol.

Refactor `_compose_repository()`:

```python
if repository_factory is not None:
    return repository_factory(config)
if api_settings.build_job_repository_backend == "file":
    return _compose_file_repository(
        runtime_build_jobs=runtime_build_jobs,
        config=config,
    )
if api_settings.build_job_repository_backend == "postgresql":
    if not config.storage.build_job_postgres_dsn.strip():
        raise BuildJobRepositoryError("Build job PostgreSQL DSN is required.")
    return runtime_build_jobs.PostgresBuildJobRepository(
        dsn=config.storage.build_job_postgres_dsn,
        now=_utc_now,
        settings=_repository_settings(config),
        pool_min_size=api_settings.build_job_postgres_pool_min_size,
        pool_max_size=api_settings.build_job_postgres_pool_max_size,
        pool_timeout_seconds=api_settings.build_job_postgres_pool_timeout_seconds,
    )
raise ValueError("Unsupported build job repository backend.")
```

Both branches receive `audit_retention_days`. Only the file branch runs `BuildJobStoreMigrator`.

`compose_build_job_application` relies on `BuildJobApplicationService.shutdown()` to close its
repository. `compose_build_job_worker` has no application service, so pass
`repository_close=repository.close` to `ExternalBuildJobWorkerRunner`; invoke that callback in the
runner's `shutdown()` after its executor stops. The default callback is a no-op so direct runner
construction remains compatible.

- [ ] **Step 4: Keep structural tests honest**

Update `_RuntimeBuildJobsModule` expected attributes without adding a protocol and keep all
ratchet counts unchanged from Task 4.

- [ ] **Step 5: Run GREEN composition and worker tests**

Run:

```powershell
python -m pytest tests/test_build_job_composition.py tests/test_build_job_persistence.py tests/test_build_job_external_worker.py tests/test_build_job_runner.py tests/test_abstraction_ratchets.py -q
```

Expected: all pass.

- [ ] **Step 6: Commit**

```powershell
git add rag_modules/runtime/build_jobs/__init__.py rag_modules/runtime/build_jobs/external_worker_runner.py rag_modules/app/composition/build_jobs.py tests/test_build_job_composition.py tests/test_build_job_persistence.py tests/test_build_job_external_worker.py tests/test_abstraction_ratchets.py
git commit -m "feat: compose PostgreSQL build job repository by default"
```

---

### Task 9: Expose the protected audit API and sanitized 503 errors

**Files:**
- Modify: `rag_modules/interfaces/api/build_models.py`
- Modify: `rag_modules/interfaces/api/response_builder.py`
- Modify: `rag_modules/interfaces/api/services/build.py`
- Modify: `rag_modules/interfaces/api/services/errors.py`
- Modify: `rag_modules/interfaces/api/services/__init__.py`
- Modify: `rag_modules/interfaces/api/error_handlers.py`
- Modify: `rag_modules/interfaces/api/build_routes.py`
- Modify: `tests/test_api_build.py`
- Modify: `tests/test_api_security.py`
- Modify: `tests/test_api_public_surface.py`

**Interfaces:**
- Produces: authenticated `GET /v1/jobs/{job_id}/events`.
- Consumes: Task 1 application audit page and safe event projection.

- [ ] **Step 1: Write failing API tests**

Using an injected `BuildJobApplicationService`, test:

- ascending event revisions with a bounded `next_cursor`;
- queued payload omits idempotency hash;
- claimed payload omits lease token;
- archived job audit remains available;
- invalid cursor returns `400 INVALID_REQUEST`;
- missing/purged job returns `404 NOT_FOUND`;
- backend-unavailable exception returns `503 SERVICE_UNAVAILABLE` without the injected secret;
- unauthenticated event request returns 401;
- OpenAPI contains only `/v1/jobs/{job_id}/events`, not the unversioned path.

- [ ] **Step 2: Run API tests and confirm RED**

Run:

```powershell
python -m pytest tests/test_api_build.py tests/test_api_security.py tests/test_api_public_surface.py -q
```

Expected: route 404 and missing model/service methods.

- [ ] **Step 3: Add strict audit response models and builder**

Add:

```python
class BuildJobAuditEventModel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    event_id: str
    job_id: str
    revision: int
    event_type: str
    schema_version: int
    occurred_at: str
    request_id: str
    payload: JsonObject = Field(default_factory=dict)


class BuildJobAuditEventListResponseModel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    events: list[BuildJobAuditEventModel] = Field(default_factory=list)
    next_cursor: str = ""
```

The response builder applies
`sanitize_public_error_fields(list(event_payloads), code=ErrorCode.BUILD_FAILED)` before model
validation.

- [ ] **Step 4: Add service translation and route**

Add a service page dataclass and call `public_build_job_event` for every event. Translate
application `BuildJobNotFoundError`, cursor `ValueError`, and
`BuildJobRepositoryUnavailableError` into interface-layer errors. Add an interface
`BuildJobBackendUnavailableError`; map it to `ErrorCode.SERVICE_UNAVAILABLE`.
Apply the unavailable translation to submit, list, get, cancel, retry, and event-list methods so
every request-time repository outage has the same sanitized 503 contract.

Register:

```python
@app.get(
    f"{API_PREFIX}/jobs/{{job_id}}/events",
    response_model=BuildJobAuditEventListResponseModel,
)
def list_build_job_events(
    job_id: str = Path(pattern=r"^[0-9a-f]{32}$"),
    limit: int | None = Query(default=None, ge=1),
    cursor: str = Query(default=""),
) -> BuildJobAuditEventListResponseModel:
    page = api_service.list_build_job_events(job_id, limit=limit, cursor=cursor)
    return build_build_job_event_list_response(page.events, next_cursor=page.next_cursor)
```

Do not add the route to unauthenticated passthrough paths.

- [ ] **Step 5: Run GREEN API tests**

Run:

```powershell
python -m pytest tests/test_api_build.py tests/test_api_security.py tests/test_api_public_surface.py -q
```

Expected: all pass.

- [ ] **Step 6: Commit**

```powershell
git add rag_modules/interfaces/api tests/test_api_build.py tests/test_api_security.py tests/test_api_public_surface.py
git commit -m "feat: expose sanitized build job audit events"
```

---

### Task 10: Add low-cardinality repository metrics

**Files:**
- Modify: `rag_modules/telemetry.py`
- Modify: `rag_modules/runtime/build_jobs/postgres/repository.py`
- Modify: `rag_modules/app/composition/build_jobs.py`
- Modify: `tests/test_runtime_telemetry.py`
- Modify: `tests/test_postgres_build_job_repository.py`

**Interfaces:**
- Produces operation duration, claim, error, archive, and purge metric recorders.
- Consumes: existing `RuntimeTelemetry` from composition.

- [ ] **Step 1: Write failing metric tests**

Record one operation, empty claim, connection error, archive, and purge. Require:

```text
graphrag_build_job_repository_operation_seconds_count{backend="postgresql",operation="submit",outcome="success"} 1.0
graphrag_build_job_claim_total{backend="postgresql",outcome="empty"} 1.0
graphrag_build_job_repository_errors_total{backend="postgresql",category="connection"} 1.0
graphrag_build_job_retention_total{action="archived",backend="postgresql"} 2.0
graphrag_build_job_retention_total{action="purged",backend="postgresql"} 1.0
```

Pass deliberately unsafe/high-cardinality labels and assert they normalize to `unknown`.

- [ ] **Step 2: Run metric tests and confirm RED**

Run:

```powershell
python -m pytest tests/test_runtime_telemetry.py tests/test_postgres_build_job_repository.py -k "metric or telemetry" -q
```

Expected: missing metric attributes/methods.

- [ ] **Step 3: Add instruments and recorders**

Add histogram/counters with only the labels shown above. Add:

```python
record_build_job_repository_operation(
    *, backend: str, operation: str, outcome: str, duration_seconds: float
)
record_build_job_claim(*, backend: str, outcome: str)
record_build_job_repository_error(*, backend: str, category: str)
record_build_job_retention(*, backend: str, action: str, count: int)
```

Normalize every label with `_metric_label`.

- [ ] **Step 4: Inject narrow callbacks into PostgreSQL repository**

Define `PostgresBuildJobObservers` in `repository.py` with four callable fields. Composition builds
it from `RuntimeTelemetry` bound methods. Time operations with `time.perf_counter`; emit only
classified operation/outcome/category values. Never attach identifiers, SQLSTATE strings, SQL,
or exception text as labels.

- [ ] **Step 5: Run GREEN telemetry tests**

Run:

```powershell
python -m pytest tests/test_runtime_telemetry.py tests/test_postgres_build_job_repository.py -k "metric or telemetry" -q
```

Expected: all selected tests pass.

- [ ] **Step 6: Commit**

```powershell
git add rag_modules/telemetry.py rag_modules/runtime/build_jobs/postgres/repository.py rag_modules/app/composition/build_jobs.py tests/test_runtime_telemetry.py tests/test_postgres_build_job_repository.py
git commit -m "feat: observe build job repository operations"
```

---

### Task 11: Add PostgreSQL CI, Docker profile, and operator documentation

**Files:**
- Modify: `docker-compose.yml`
- Modify: `.github/workflows/ci.yml`
- Modify: `.env.example`
- Modify: `README.md`
- Modify: `docs/architecture.md`
- Modify: `docs/app_composition_maintenance_guide.md`
- Modify: `docs/release_process.md`
- Modify: `tests/test_docker_api_build_context.py`
- Modify: `tests/test_entrypoints.py`

**Interfaces:**
- Produces documented migration/import/cutover workflow and mandatory real-PostgreSQL CI.
- Consumes: Tasks 3–10 commands and configuration.

- [ ] **Step 1: Write failing Docker and documentation assertions**

Require Compose to contain a `build-job-postgres` service under profile `postgres`, image
`postgres:16.14-alpine`, health check, persistent volume, and safe local defaults. Assert README
and release docs contain:

- `graph-rag-build-job-db status`;
- `graph-rag-build-job-db migrate`;
- `graph-rag-build-job-db import-file --source storage/indexes/build_jobs.json --dry-run`;
- fail-closed startup order;
- rollback instruction to switch backend only after stopping API/workers;
- the fact that runtime startup never migrates.

- [ ] **Step 2: Run focused assertions and confirm RED**

Run:

```powershell
python -m pytest tests/test_docker_api_build_context.py tests/test_entrypoints.py -q
```

Expected: missing service/documented command assertions.

- [ ] **Step 3: Add the optional Compose service**

Add:

```yaml
build-job-postgres:
  image: postgres:16.14-alpine
  environment:
    POSTGRES_DB: graph_rag
    POSTGRES_USER: graph_rag
    POSTGRES_PASSWORD: ${BUILD_JOB_POSTGRES_PASSWORD:-graph-rag-local}
  healthcheck:
    test: ["CMD-SHELL", "pg_isready -U graph_rag -d graph_rag"]
    interval: 5s
    timeout: 5s
    retries: 20
  volumes:
    - ${DOCKER_VOLUME_DIRECTORY:-.}/volumes/build-job-postgres:/var/lib/postgresql/data
  ports:
    - "5432:5432"
  profiles:
    - postgres
```

Do not make the existing `api` profile depend on it; that profile selects `dev` and file storage.

- [ ] **Step 4: Add a mandatory PostgreSQL CI service**

Under `quality-gates`, add the PostgreSQL service with database `graph_rag_test`, health options,
and job environment:

```yaml
BUILD_JOB_TEST_POSTGRES_DSN: postgresql://graph_rag:graph_rag_test@localhost:5432/graph_rag_test
BUILD_JOB_TEST_ALLOW_RESET: "1"
```

The existing full pytest command then collects and runs PostgreSQL tests instead of skipping them.

- [ ] **Step 5: Document configuration, migration, import, and release order**

Document:

1. deploy PostgreSQL 16+;
2. run `status`, then `migrate`;
3. dry-run and execute file import if history exists;
4. stop API/workers before backend cutover;
5. set backend/DSN/pool/audit variables;
6. start API/worker and check diagnostics/metrics;
7. retain the source V3 directory as rollback evidence.

State that file backend is development-only and scans directories.

- [ ] **Step 6: Run GREEN focused tests**

Run:

```powershell
python -m pytest tests/test_docker_api_build_context.py tests/test_entrypoints.py -q
```

Expected: all pass.

- [ ] **Step 7: Commit**

```powershell
git add docker-compose.yml .github/workflows/ci.yml .env.example README.md docs/architecture.md docs/app_composition_maintenance_guide.md docs/release_process.md tests/test_docker_api_build_context.py tests/test_entrypoints.py
git commit -m "docs: operationalize PostgreSQL build job control plane"
```

---

### Task 12: Run release-sensitive verification

**Files:**
- Modify only files required by failures directly caused by Tasks 1–11.

**Interfaces:**
- Consumes: complete implementation.
- Produces: fresh evidence for repository, API, typing, lint, and release claims.

- [ ] **Step 1: Run focused PostgreSQL and build-job tests**

Run with the guarded test DSN:

```powershell
python -m pytest tests/test_postgres_build_job_schema.py tests/test_postgres_build_job_repository.py tests/test_build_job_file_import.py tests/test_build_job_repository_port.py tests/test_build_job_repository_records.py tests/test_build_job_repository_idempotency.py tests/test_build_job_repository_recovery_retention.py tests/test_build_job_application.py tests/test_build_job_composition.py tests/test_build_job_external_worker.py tests/test_build_job_runner.py -q
```

Expected: all pass, no skips in the three PostgreSQL-specific modules.

- [ ] **Step 2: Run the documented API slice**

Run:

```powershell
python -m pytest tests/test_api_answer.py tests/test_api_build.py tests/test_api_public_surface.py tests/test_api_security.py tests/test_api_sse.py tests/test_entrypoints.py -q
```

Expected: all pass.

- [ ] **Step 3: Run type and formatting checks**

Run:

```powershell
python -m mypy --config-file pyproject.toml
pre-commit run --all-files
git diff --check
```

Expected: zero errors. If Ruff modifies files, inspect the diff and rerun the affected tests plus
`pre-commit run --all-files`.

- [ ] **Step 4: Run the complete suite**

Run:

```powershell
python -m pytest -q
```

Expected: all tests pass and PostgreSQL modules do not skip when the CI/test DSN is configured.

- [ ] **Step 5: Run the offline release gate**

Run:

```powershell
python scripts/release_gate.py
```

Expected: exit code `0`.

- [ ] **Step 6: Review requirements against the approved spec**

Verify explicitly:

- base production profile is PostgreSQL and dev/test are file;
- missing DSN/schema never falls back;
- factory injection precedes built-in validation;
- event/projection writes are atomic;
- idempotency and active-slot races are database-enforced;
- claim/recovery use `SKIP LOCKED`;
- archived audit survives operational retention and is purged after audit expiry;
- API projection excludes idempotency hash and lease token;
- diagnostics and metrics are bounded and low-cardinality;
- V3 import is dry-runnable, repeatable, and fail-closed.

- [ ] **Step 7: Route any verification correction back through its owning task**

If verification finds a gap, return to the task that owns that behavior, add a failing regression
test, observe RED, implement the minimum correction, rerun that task's GREEN command, and use that
task's explicit file list for the corrective commit. If no correction is required, do not create
an empty commit.

---

## Plan Self-Review

- Spec coverage: production selection, dev file parity, indexed PostgreSQL operations, atomic
  claim/lease, append-only audit, retention split, protected API, explicit migration/import,
  diagnostics, metrics, Docker/CI, documentation, dependency locks, and release verification all
  map to tasks.
- Type consistency: `BuildJobEventListQuery`, `BuildJobEventPage`,
  `BuildJobRepositoryUnavailableError`, `PostgresBuildJobRepository`,
  `PostgresBuildJobSchemaManager`, and `V3BuildJobImporter` retain the same names/signatures across
  producing and consuming tasks.
- Module-ratchet impact is exact: four new files under `rag_modules`, moving the production Python
  file ceiling from `379` to `383`; no new Protocol or `Any` baseline is required.
- The plan contains no deferred implementation markers; every behavior lists its test,
  expected RED reason, implementation rule, GREEN command, and commit boundary.
