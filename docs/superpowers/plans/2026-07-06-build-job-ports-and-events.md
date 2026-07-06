# Build Job Ports and Events Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace concrete, API-owned build-job orchestration with typed application ports, versioned events, lease-based execution, a V3 file repository, and one-time V2 migration.

**Architecture:** `BuildJobApplicationService` owns use cases and depends only on `BuildJobRepositoryPort` and `BuildJobRunnerPort`. Domain transitions are reduced from immutable typed events; the file adapter atomically stores each job snapshot and event sequence, while the in-process runner claims jobs through opaque leases. Composition chooses adapters outside the FastAPI service, and obsolete registry/store facades are deleted in the final cutover.

**Tech Stack:** Python 3.11, dataclasses, `Protocol`, `StrEnum`, FastAPI, Pydantic v2, existing atomic JSON writer and cross-platform file locking, pytest/unittest, Ruff, mypy.

---

## File Structure

### Application kernel

- Create `rag_modules/app/build_jobs/models.py`: identifiers, enums, commands, snapshots, pages, leases, settings, and safe public projection.
- Create `rag_modules/app/build_jobs/events.py`: versioned event envelope, typed payloads, and JSON serialization.
- Create `rag_modules/app/build_jobs/errors.py`: backend-neutral build-job exceptions.
- Create `rag_modules/app/build_jobs/reducer.py`: pure transition validation and snapshot reduction.
- Create `rag_modules/app/build_jobs/ports.py`: `BuildJobRepositoryPort` and `BuildJobRunnerPort`.
- Create `rag_modules/app/build_jobs/service.py`: submit, query, cancel, retry, startup, and shutdown use cases.
- Create `rag_modules/app/build_jobs/executor.py`: build/rebuild execution against runtime hooks.
- Create `rag_modules/app/build_jobs/__init__.py`: canonical application exports only.
- Create `rag_modules/app/runtime_operations.py`: shared lifecycle, answer, and inspection operation coordination.

### Runtime adapters

- Create `rag_modules/runtime/build_jobs/locks.py`: internal cross-process store and migration locks.
- Create `rag_modules/runtime/build_jobs/serialization.py`: V3 envelope and index encoding/decoding.
- Create `rag_modules/runtime/build_jobs/file_repository.py`: file implementation of the repository port.
- Create `rag_modules/runtime/build_jobs/migration.py`: fail-closed V2-to-V3 staging migration.
- Create `rag_modules/runtime/build_jobs/in_process_runner.py`: thread-pool runner, lease heartbeat, and cancellation controls.
- Create `rag_modules/runtime/build_jobs/__init__.py`: concrete adapter exports.

### Composition and API

- Create `rag_modules/app/composition/build_jobs.py`: compose repository, executor, runner, and application service.
- Modify `rag_modules/app/assembly.py`: expose default build-job assembly without exposing internal composition.
- Modify `rag_modules/interfaces/api/services/base.py`: consume the app-owned operation coordinator.
- Modify `rag_modules/interfaces/api/services/build.py`: depend on `BuildJobApplicationService` and map typed errors.
- Modify `rag_modules/interfaces/api/app.py`: compose the build-job application before constructing the build API service.
- Modify `rag_modules/interfaces/api/build_models.py`: keep public statuses stable while mapping claimed/interrupted internal snapshots.
- Modify `rag_modules/interfaces/api/routes.py`: keep existing HTTP behavior unchanged.
- Modify `rag_modules/configuration/model_sections/api.py`: add lease and heartbeat settings with relationship validation.
- Modify `rag_modules/configuration/env_specs/api.py`, `.env.example`, and `README.md`: expose and document lease settings and V3 migration.

### Deletions at cutover

- Delete `rag_modules/interfaces/api/build_job_store.py`.
- Delete `rag_modules/interfaces/api/build_jobs/` in full after all callers use canonical application/runtime modules.

### Tests

- Create `tests/test_build_job_domain.py`.
- Create `tests/test_build_job_repository_port.py`.
- Create `tests/test_build_job_migration.py`.
- Create `tests/test_build_job_application.py`.
- Rewrite `tests/test_build_job_runner.py`.
- Rewrite `tests/test_build_job_persistence.py` to use canonical composition/runtime imports.
- Modify `tests/test_api_app.py`, `tests/test_configuration_defaults.py`, `tests/test_configuration_section_loaders.py`, `tests/test_module_boundary_facades.py`, and `tests/test_public_surface_boundaries.py`.

## Task 1: Typed Domain Models, Events, and Reducer

**Files:**
- Create: `tests/test_build_job_domain.py`
- Create: `rag_modules/app/build_jobs/models.py`
- Create: `rag_modules/app/build_jobs/events.py`
- Create: `rag_modules/app/build_jobs/errors.py`
- Create: `rag_modules/app/build_jobs/reducer.py`
- Create: `rag_modules/app/build_jobs/__init__.py`

- [ ] **Step 1: Write the failing reducer tests**

Create `tests/test_build_job_domain.py` with the fixed clock and event factory below. The first tests prove the desired API, revision sequence, public projection, and terminal-state guard.

```python
from __future__ import annotations

import unittest
from datetime import datetime, timezone

from rag_modules.app.build_jobs import (
    BuildJobEvent,
    BuildJobEventType,
    BuildJobId,
    BuildJobInvalidTransitionError,
    BuildJobStatus,
    BuildJobType,
    JobClaimed,
    JobFailed,
    JobQueued,
    JobStarted,
    WorkerIdentity,
    reduce_build_job,
)

NOW = datetime(2026, 7, 6, tzinfo=timezone.utc)
JOB_ID = BuildJobId("a" * 32)


def _event(event_type, payload, *, revision: int) -> BuildJobEvent:
    return BuildJobEvent(
        event_id=f"event-{revision}",
        job_id=JOB_ID,
        revision=revision,
        event_type=event_type,
        schema_version=1,
        occurred_at=NOW,
        request_id="request-1",
        payload=payload,
    )


class BuildJobDomainTests(unittest.TestCase):
    def test_reducer_creates_queued_snapshot_and_hides_internal_statuses(self) -> None:
        queued = reduce_build_job(
            None,
            _event(
                BuildJobEventType.QUEUED,
                JobQueued(job_type=BuildJobType.BUILD, idempotency_key_hash="hash"),
                revision=1,
            ),
        )

        self.assertEqual(queued.status, BuildJobStatus.QUEUED)
        self.assertEqual(queued.revision, 1)
        self.assertNotIn("idempotency_key_hash", queued.to_public_dict())

    def test_terminal_snapshot_rejects_later_event(self) -> None:
        queued = reduce_build_job(
            None,
            _event(
                BuildJobEventType.QUEUED,
                JobQueued(job_type=BuildJobType.BUILD),
                revision=1,
            ),
        )
        claimed = reduce_build_job(
            queued,
            _event(
                BuildJobEventType.CLAIMED,
                JobClaimed(
                    worker=WorkerIdentity("worker-1", "in_process"),
                    lease_token="lease-1",
                    lease_expires_at=NOW,
                ),
                revision=2,
            ),
        )
        started = reduce_build_job(
            claimed,
            _event(
                BuildJobEventType.STARTED,
                JobStarted(worker=WorkerIdentity("worker-1", "in_process")),
                revision=3,
            ),
        )
        failed = reduce_build_job(
            started,
            _event(
                BuildJobEventType.FAILED,
                JobFailed(message="Knowledge base build failed."),
                revision=4,
            ),
        )

        with self.assertRaises(BuildJobInvalidTransitionError):
            reduce_build_job(
                failed,
                _event(
                    BuildJobEventType.STARTED,
                    JobStarted(worker=WorkerIdentity("worker-1", "in_process")),
                    revision=5,
                ),
            )
```

- [ ] **Step 2: Run the reducer tests and observe the missing package failure**

Run:

```powershell
python -m pytest tests/test_build_job_domain.py -q
```

Expected: collection fails with `ModuleNotFoundError: rag_modules.app.build_jobs`.

- [ ] **Step 3: Implement typed models and errors**

Create `models.py` with `BuildJobId(str)` validation, `BuildJobType`, `BuildJobStatus`, `BuildJobSubmissionDisposition`, and frozen dataclasses for `SubmitBuildJob`, `BuildJobSubmission`, `BuildJobSnapshot`, `BuildJobListQuery`, `BuildJobPage`, `WorkerIdentity`, `BuildJobLease`, `BuildJobRepositorySettings`, and `BuildJobRepositoryDiagnostics`. `BuildJobRepositorySettings` has `retention_limit=100`, `list_default_limit=50`, `list_max_limit=100`, and `lease_seconds=30.0`. Use this exact public-status mapping:

```python
_PUBLIC_STATUS = {
    BuildJobStatus.CLAIMED: BuildJobStatus.QUEUED,
    BuildJobStatus.INTERRUPTED: BuildJobStatus.FAILED,
}


def public_status(status: BuildJobStatus) -> BuildJobStatus:
    return _PUBLIC_STATUS.get(status, status)
```

`BuildJobSnapshot.to_public_dict()` must return the existing fields only: `job_id`, `request_id`, `job_type`, public `status`, ISO timestamps, `message`, safe `error`, bounded `logs`, typed `result`, and `retry_of_job_id`. It must never include revision, lease, worker, idempotency hash, baseline, or events.

Create `errors.py` with these classes and typed attributes:

```python
class BuildJobError(RuntimeError):
    pass


class BuildJobNotFoundError(BuildJobError):
    def __init__(self, job_id: BuildJobId) -> None:
        super().__init__(str(job_id))
        self.job_id = job_id


class BuildJobConflictError(BuildJobError):
    def __init__(self, message: str, snapshot: BuildJobSnapshot) -> None:
        super().__init__(message)
        self.snapshot = snapshot


class BuildJobIdempotencyConflictError(BuildJobConflictError):
    pass


class BuildJobInvalidTransitionError(BuildJobError):
    pass


class BuildJobConcurrentUpdateError(BuildJobError):
    pass


class BuildJobLeaseLostError(BuildJobError):
    pass


class BuildJobRepositoryError(BuildJobError):
    pass


class BuildJobDispatchError(BuildJobError):
    pass
```

- [ ] **Step 4: Implement the closed event union and reducer**

Create `events.py` with `BuildJobEventType(StrEnum)`, frozen payload dataclasses `JobQueued`, `JobClaimed`, `JobStarted`, `JobProgressRecorded`, `JobCancellationRequested`, `JobCancelled`, `JobSucceeded`, `JobFailed`, and `JobInterrupted`, plus the frozen `BuildJobEvent`. Add `event_to_dict()` and `event_from_dict()` using a fixed `event_type -> payload class` mapping; reject unknown schema versions, payload keys, and event types with `ValueError`.

Create `reducer.py` with an explicit transition table:

```python
_ALLOWED_EVENTS = {
    BuildJobStatus.QUEUED: {
        BuildJobEventType.CLAIMED,
        BuildJobEventType.CANCELLATION_REQUESTED,
    },
    BuildJobStatus.CLAIMED: {
        BuildJobEventType.STARTED,
        BuildJobEventType.CANCELLATION_REQUESTED,
        BuildJobEventType.INTERRUPTED,
    },
    BuildJobStatus.RUNNING: {
        BuildJobEventType.PROGRESS_RECORDED,
        BuildJobEventType.CANCELLATION_REQUESTED,
        BuildJobEventType.SUCCEEDED,
        BuildJobEventType.FAILED,
        BuildJobEventType.INTERRUPTED,
    },
    BuildJobStatus.CANCEL_REQUESTED: {
        BuildJobEventType.PROGRESS_RECORDED,
        BuildJobEventType.CANCELLED,
        BuildJobEventType.SUCCEEDED,
        BuildJobEventType.FAILED,
        BuildJobEventType.INTERRUPTED,
    },
}
```

`reduce_build_job(None, event)` accepts only revision-1 `JobQueued`. Later reductions require matching job IDs and `event.revision == snapshot.revision + 1`. Use `dataclasses.replace` to produce a new snapshot. Bound logs to 200 entries and create the existing safe `BUILD_FAILED` error for failed/interrupted snapshots.

- [ ] **Step 5: Export canonical domain names and run tests**

Create `rag_modules/app/build_jobs/__init__.py` with explicit imports and `__all__` for the models, events, errors, and reducer. Run:

```powershell
python -m pytest tests/test_build_job_domain.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit the domain kernel**

```powershell
git add tests/test_build_job_domain.py rag_modules/app/build_jobs
git commit -m "feat: add typed build job event domain"
```

## Task 2: Stable Application Ports

**Files:**
- Create: `rag_modules/app/build_jobs/ports.py`
- Modify: `rag_modules/app/build_jobs/__init__.py`
- Modify: `tests/test_build_job_domain.py`

- [ ] **Step 1: Add a failing port-shape test**

Append a test that inspects the protocols so repository queries never drift back into the runner:

```python
    def test_runner_port_contains_execution_notifications_only(self) -> None:
        from rag_modules.app.build_jobs import BuildJobRepositoryPort, BuildJobRunnerPort

        runner_methods = {
            name for name, value in vars(BuildJobRunnerPort).items() if callable(value)
        }
        repository_methods = {
            name for name, value in vars(BuildJobRepositoryPort).items() if callable(value)
        }

        self.assertEqual(
            runner_methods.intersection({"start", "schedule", "notify_cancellation", "shutdown"}),
            {"start", "schedule", "notify_cancellation", "shutdown"},
        )
        self.assertFalse(runner_methods.intersection({"get", "list_page", "diagnostics", "apply"}))
        self.assertTrue({"submit", "get", "list_page", "claim_next", "apply"} <= repository_methods)
```

- [ ] **Step 2: Run the port-shape test and observe the import failure**

```powershell
python -m pytest tests/test_build_job_domain.py::BuildJobDomainTests::test_runner_port_contains_execution_notifications_only -q
```

Expected: FAIL because the two ports are not exported.

- [ ] **Step 3: Implement the exact protocols**

Create `ports.py`:

```python
from __future__ import annotations

from typing import Protocol

from .events import BuildJobEvent
from .models import (
    BuildJobId,
    BuildJobLease,
    BuildJobListQuery,
    BuildJobPage,
    BuildJobRepositoryDiagnostics,
    BuildJobSnapshot,
    BuildJobSubmission,
    SubmitBuildJob,
    WorkerIdentity,
)


class BuildJobRepositoryPort(Protocol):
    @property
    def list_default_limit(self) -> int: ...
    def submit(self, command: SubmitBuildJob) -> BuildJobSubmission: ...
    def get(self, job_id: BuildJobId) -> BuildJobSnapshot | None: ...
    def list_page(self, query: BuildJobListQuery) -> BuildJobPage: ...
    def claim_next(self, worker: WorkerIdentity) -> BuildJobLease | None: ...
    def renew_lease(self, lease: BuildJobLease) -> BuildJobLease: ...
    def apply(
        self,
        event: BuildJobEvent,
        *,
        expected_revision: int,
        lease: BuildJobLease | None = None,
    ) -> BuildJobSnapshot: ...
    def find_dispatchable(self, *, limit: int) -> tuple[BuildJobId, ...]: ...
    def recover_expired_leases(self) -> tuple[BuildJobSnapshot, ...]: ...
    def apply_retention(self) -> None: ...
    def diagnostics(self) -> BuildJobRepositoryDiagnostics: ...


class BuildJobRunnerPort(Protocol):
    def start(self) -> None: ...
    def schedule(self, job_id: BuildJobId) -> None: ...
    def notify_cancellation(self, job_id: BuildJobId) -> None: ...
    def shutdown(self) -> None: ...
```

Export both names from the package.

- [ ] **Step 4: Run domain and mypy-focused tests**

```powershell
python -m pytest tests/test_build_job_domain.py -q
python -m mypy rag_modules/app/build_jobs
```

Expected: both commands PASS.

- [ ] **Step 5: Commit the ports**

```powershell
git add tests/test_build_job_domain.py rag_modules/app/build_jobs
git commit -m "feat: define build job application ports"
```

## Task 3: V3 Serialization and Repository Submission

**Files:**
- Create: `tests/test_build_job_repository_port.py`
- Create: `rag_modules/runtime/build_jobs/locks.py`
- Create: `rag_modules/runtime/build_jobs/serialization.py`
- Create: `rag_modules/runtime/build_jobs/file_repository.py`
- Create: `rag_modules/runtime/build_jobs/__init__.py`

- [ ] **Step 1: Write failing submission, replay, and CAS tests**

Create a repository factory using `TemporaryDirectory`, a deterministic `now`, and
`BuildJobRepositorySettings(retention_limit=100, list_default_limit=50, list_max_limit=100,
lease_seconds=30)`. Add these assertions:

```python
submission = repository.submit(
    SubmitBuildJob(
        job_id=BuildJobId("a" * 32),
        request_id="request-1",
        job_type=BuildJobType.BUILD,
        idempotency_key="stable-key",
    )
)
replayed = repository.submit(
    SubmitBuildJob(
        job_id=BuildJobId("b" * 32),
        request_id="request-2",
        job_type=BuildJobType.BUILD,
        idempotency_key="stable-key",
    )
)

self.assertEqual(submission.disposition, BuildJobSubmissionDisposition.CREATED)
self.assertEqual(replayed.disposition, BuildJobSubmissionDisposition.REPLAYED)
self.assertEqual(replayed.snapshot.job_id, submission.snapshot.job_id)
self.assertEqual(repository.get(submission.snapshot.job_id), submission.snapshot)
```

Add a second test that calls `repository.apply(JobCancellationRequested, expected_revision=0)` and expects `BuildJobConcurrentUpdateError` because the queued snapshot revision is 1. Inspect the stored file and assert the top-level keys are exactly `schema_version`, `revision`, `baseline`, `snapshot`, and `events`.

- [ ] **Step 2: Run the repository tests and observe the missing adapter failure**

```powershell
python -m pytest tests/test_build_job_repository_port.py -q
```

Expected: collection fails with `ModuleNotFoundError: rag_modules.runtime.build_jobs`.

- [ ] **Step 3: Move the lock implementation without exposing it**

Create `runtime/build_jobs/locks.py` from the current cross-platform `_InterprocessFileLock`, rename it `InterprocessFileLock`, and export nothing from `runtime/build_jobs/__init__.py`. All uses remain inside runtime adapter modules.

- [ ] **Step 4: Implement V3 encoding and strict decoding**

In `serialization.py`, define `BUILD_JOB_ENVELOPE_SCHEMA_VERSION = 3`, `BuildJobEnvelope`, `snapshot_to_dict`, `snapshot_from_dict`, `envelope_to_dict`, and `envelope_from_dict`. `envelope_from_dict` must reject unknown keys, unsupported versions, mismatched revisions, noncontiguous events, and a reduced final snapshot that differs from the stored snapshot. For migrated records, reduction begins at `baseline`; for new records it begins at `None`.

The job envelope writer must call the existing `rag_modules.runtime.artifacts.write_json_atomic` once per transition.

- [ ] **Step 5: Implement atomic submit/get/apply and idempotency repair**

In `file_repository.py`, implement `FileBuildJobRepository(BuildJobRepositoryPort)` with these invariants:

```python
def submit(self, command: SubmitBuildJob) -> BuildJobSubmission:
    key_hash = hash_idempotency_key(validate_idempotency_key(command.idempotency_key))
    with self._store_lock():
        replay = self._find_idempotent_job(key_hash)
        if replay is not None:
            if replay.job_type is not command.job_type:
                raise BuildJobIdempotencyConflictError(
                    "Idempotency key conflicts with an existing build job.", replay
                )
            return BuildJobSubmission(BuildJobSubmissionDisposition.REPLAYED, replay)
        active = self._active_snapshot()
        if active is not None:
            raise BuildJobConflictError("A build job is already in progress.", active)
        event = new_queued_event(command, key_hash=key_hash, now=self._now())
        snapshot = reduce_build_job(None, event)
        self._write_envelope(BuildJobEnvelope.new(snapshot, event))
        self._write_idempotency_index(key_hash, snapshot)
        self.apply_retention()
        return BuildJobSubmission(BuildJobSubmissionDisposition.CREATED, snapshot)
```

`apply()` must load the envelope under the store lock, compare `expected_revision`, validate an optional lease token for worker-owned transitions, reduce the event, append it, and atomically replace only that job file. Index repair must derive the hash and job type from queued events instead of trusting an orphaned index file.

- [ ] **Step 6: Run repository tests**

```powershell
python -m pytest tests/test_build_job_repository_port.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit V3 repository submission**

```powershell
git add tests/test_build_job_repository_port.py rag_modules/runtime/build_jobs
git commit -m "feat: add V3 build job file repository"
```

## Task 4: Leases, Recovery, Pagination, Retention, and Diagnostics

**Files:**
- Modify: `tests/test_build_job_repository_port.py`
- Modify: `rag_modules/app/build_jobs/models.py`
- Modify: `rag_modules/runtime/build_jobs/file_repository.py`
- Modify: `rag_modules/runtime/build_jobs/serialization.py`

- [ ] **Step 1: Add failing repository contract cases**

Add focused tests proving:

- `claim_next()` changes queued to claimed and returns an opaque token.
- `renew_lease()` extends expiration only for the matching token.
- `apply()` raises `BuildJobLeaseLostError` for a different token.
- `recover_expired_leases()` emits interrupted snapshots but leaves unexpired leases intact.
- `find_dispatchable()` returns queued IDs only.
- cursor pagination is newest-first and bounded by `list_max_limit`.
- retention removes the oldest terminal jobs but never nonterminal jobs.
- a malformed envelope produces `BUILD_JOB_STORE_CORRUPT_RECORD` without leaking file contents.

Use a mutable clock helper so lease expiry is deterministic; never use `sleep()` in repository tests.

- [ ] **Step 2: Run the new contract cases and observe missing behavior**

```powershell
python -m pytest tests/test_build_job_repository_port.py -q
```

Expected: FAIL on the first unimplemented lease or recovery assertion.

- [ ] **Step 3: Implement lease transitions and recovery**

Use `BuildJobRepositorySettings.lease_seconds` when `claim_next()` selects the oldest queued snapshot under the store lock, creates a cryptographically random token, appends `JobClaimed`, and returns the matching lease. Persist lease renewal in an internal `leases/<job_id>.json` record without changing the job's domain revision; every domain revision must still correspond to an event. `recover_expired_leases()` consults that lease record, appends `JobInterrupted` only when `lease_expires_at <= now`, and removes lease records after terminal events.

Store lease token only in the internal snapshot. Never serialize it through `to_public_dict()` or diagnostics.

- [ ] **Step 4: Implement pagination, retention, and safe diagnostics**

Reuse URL-safe base64 JSON cursors containing only `created_at` and `job_id`. Treat malformed cursors as `ValueError("invalid build job cursor")`. Retention sorts terminal snapshots newest-first and removes entries after `retention_limit`, including their idempotency indexes. Diagnostics return frozen warning records with truncated identifiers and stable codes only.

- [ ] **Step 5: Run repository and domain suites**

```powershell
python -m pytest tests/test_build_job_domain.py tests/test_build_job_repository_port.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit repository lifecycle behavior**

```powershell
git add tests/test_build_job_repository_port.py rag_modules/app/build_jobs/models.py rag_modules/runtime/build_jobs
git commit -m "feat: add build job leases and recovery"
```

## Task 5: Fail-Closed V2-to-V3 Migration

**Files:**
- Create: `tests/test_build_job_migration.py`
- Create: `rag_modules/runtime/build_jobs/migration.py`
- Modify: `rag_modules/runtime/build_jobs/file_repository.py`
- Modify: `rag_modules/runtime/build_jobs/serialization.py`

- [ ] **Step 1: Write failing migration tests**

Create V2 fixtures directly in a temporary `build_jobs.d/jobs` directory and in the legacy
`build_jobs.json`. Cover succeeded, failed, running, cancelled, and retry-linked records. Assert:

```python
migrator = BuildJobStoreMigrator(str(root / "build_jobs.json"), now=_now)
migrator.migrate()
repository = FileBuildJobRepository(str(root / "build_jobs.json"), now=_now)

migrated = repository.get(BuildJobId("a" * 32))
self.assertEqual(migrated.revision, 0)
self.assertEqual(migrated.status, BuildJobStatus.SUCCEEDED)
self.assertTrue((root / "build_jobs.v2.backup").exists())
self.assertEqual(json.loads((root / "build_jobs.d" / "metadata.json").read_text())["schema_version"], 3)
```

Add tests that a second migration is a no-op and malformed V2 input raises `BuildJobRepositoryError` while leaving source files untouched.

- [ ] **Step 2: Run migration tests and observe the missing migrator failure**

```powershell
python -m pytest tests/test_build_job_migration.py -q
```

Expected: collection fails because `BuildJobStoreMigrator` does not exist.

- [ ] **Step 3: Implement staging, verification, publication, and rollback**

`BuildJobStoreMigrator.migrate()` must:

1. acquire `<configured-path>.migration.lock`;
2. return immediately when V3 metadata is valid;
3. load all V2 records through a migration-only decoder with existing sanitization rules;
4. write revision-zero baseline envelopes into `build_jobs.v3.staging`;
5. reopen every staged envelope with the strict V3 decoder;
6. move the V2 directory to `build_jobs.v2.backup` and atomically rename staging to `build_jobs.d`;
7. restore the backup if publication fails;
8. raise `BuildJobRepositoryError` on any malformed source or partial-state conflict.

V2 queued records remain queued and become dispatchable. V2 running or cancel-requested records
receive an expired internal lease record during migration, so the first
`recover_expired_leases()` call converts them to interrupted instead of rerunning work that may
already have produced side effects.

Do not import the V2 decoder from normal repository code. `FileBuildJobRepository.__init__` accepts only a V3 directory and fails if migration has not completed.

- [ ] **Step 4: Run migration and repository suites**

```powershell
python -m pytest tests/test_build_job_migration.py tests/test_build_job_repository_port.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit the one-time migration**

```powershell
git add tests/test_build_job_migration.py rag_modules/runtime/build_jobs
git commit -m "feat: migrate build job storage to V3"
```

## Task 6: Build Job Application Service

**Files:**
- Create: `tests/test_build_job_application.py`
- Create: `rag_modules/app/build_jobs/service.py`
- Modify: `rag_modules/app/build_jobs/__init__.py`

- [ ] **Step 1: Write failing orchestration tests with recording fakes**

Create typed `RecordingRepository` and `RecordingRunner` fakes implementing the two ports. Test these exact orderings:

```python
submission = service.submit(
    rebuild=False,
    request_id="request-1",
    idempotency_key="key-1",
)
self.assertEqual(calls, [("repository.submit", submission.snapshot.job_id),
                         ("runner.schedule", submission.snapshot.job_id)])
```

Add cases proving replay does not schedule, repository failure never schedules, dispatch failure leaves the created queued snapshot retrievable, cancel applies `JobCancellationRequested` before notifying the runner, retry accepts failed/cancelled/interrupted only, and startup calls recovery before runner start.

- [ ] **Step 2: Run application tests and observe the missing service failure**

```powershell
python -m pytest tests/test_build_job_application.py -q
```

Expected: collection fails because `BuildJobApplicationService` does not exist.

- [ ] **Step 3: Implement the application service**

Create `BuildJobApplicationService` with injected repository, runner, ID factory, clock/event factory, and a safe dispatch-warning recorder. Implement:

```python
def submit(self, *, rebuild: bool, request_id: str, idempotency_key: str) -> BuildJobSnapshot:
    command = SubmitBuildJob(
        job_id=BuildJobId(self._new_id()),
        request_id=request_id,
        job_type=BuildJobType.REBUILD if rebuild else BuildJobType.BUILD,
        idempotency_key=idempotency_key,
    )
    submission = self._repository.submit(command)
    if submission.disposition is BuildJobSubmissionDisposition.CREATED:
        try:
            self._runner.schedule(submission.snapshot.job_id)
        except BuildJobDispatchError:
            self._record_dispatch_warning(submission.snapshot.job_id)
    return submission.snapshot
```

`cancel()` retries a revision conflict by reloading at most three times, returns an already-cancelled snapshot idempotently, and rejects other terminal states. `retry()` creates a new command with `retry_of_job_id`. `get()` raises `BuildJobNotFoundError`; `list_page()` uses the repository default when limit is absent. `startup()` returns the snapshots from `recover_expired_leases()` and then calls `runner.start()`.

- [ ] **Step 4: Run application and domain tests**

```powershell
python -m pytest tests/test_build_job_application.py tests/test_build_job_domain.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit application orchestration**

```powershell
git add tests/test_build_job_application.py rag_modules/app/build_jobs
git commit -m "feat: orchestrate build jobs through ports"
```

## Task 7: Executor and In-Process Runner Adapter

**Files:**
- Create: `rag_modules/app/build_jobs/executor.py`
- Create: `rag_modules/runtime/build_jobs/in_process_runner.py`
- Rewrite: `tests/test_build_job_runner.py`
- Modify: `rag_modules/app/build_jobs/__init__.py`
- Modify: `rag_modules/runtime/build_jobs/__init__.py`

- [ ] **Step 1: Rewrite runner tests against ports**

Keep the existing build, cancellation, failure-sanitization, and retry systems, but construct a
`FileBuildJobRepository`, `BuildJobExecutor`, `InProcessBuildJobRunner`, and
`BuildJobApplicationService`. Add a deterministic test that replaces the repository lease during
execution and asserts the stale worker records no later progress or terminal event. Add a heartbeat
test with a short configured interval and a fake clock/heartbeat trigger rather than sleeping for
lease expiry.

- [ ] **Step 2: Run runner tests and observe missing adapter failures**

```powershell
python -m pytest tests/test_build_job_runner.py -q
```

Expected: collection fails because `BuildJobExecutor` or `InProcessBuildJobRunner` is missing.

- [ ] **Step 3: Implement the typed executor**

Move runtime hooks and build/rebuild behavior from the old runner into `app/build_jobs/executor.py`.
The executor accepts `BuildJobSnapshot`, a progress callback, and cancellation check; it returns a
typed `JobSucceeded` payload or raises `RequestCancelled`. It sanitizes progress with the existing
stage mapping before passing `JobProgressRecorded` data to the runner. Unknown exceptions never
leave the runner and are converted to `JobFailed` using safe diagnostics and stats snapshots.

- [ ] **Step 4: Implement runner scheduling, heartbeat, and ownership checks**

`InProcessBuildJobRunner` must:

- implement exactly `start`, `schedule`, `notify_cancellation`, and `shutdown` publicly;
- use `find_dispatchable()` during `start()`;
- deduplicate locally scheduled IDs;
- call `claim_next()` before submitting execution;
- append started, progress, and terminal events with the current expected revision and lease;
- renew leases from a daemon heartbeat loop at `heartbeat_seconds` independent of progress;
- stop immediately on `BuildJobLeaseLostError` or `BuildJobConcurrentUpdateError`;
- keep cancellation controls local and observe durable cancel-requested snapshots;
- never expose `Future`, lock, executor, or control objects through a port model.

Use `threading.Event.wait(interval)` for heartbeat wakeups so shutdown is immediate and tests can
trigger the loop without long sleeps.

- [ ] **Step 5: Run runner, application, and repository suites**

```powershell
python -m pytest tests/test_build_job_runner.py tests/test_build_job_application.py tests/test_build_job_repository_port.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit the in-process adapter**

```powershell
git add tests/test_build_job_runner.py rag_modules/app/build_jobs rag_modules/runtime/build_jobs
git commit -m "feat: run build jobs through lease-backed adapter"
```

## Task 8: Composition and One-Way API Cutover

**Files:**
- Create: `rag_modules/app/composition/build_jobs.py`
- Create: `rag_modules/app/runtime_operations.py`
- Modify: `rag_modules/app/assembly.py`
- Modify: `rag_modules/interfaces/api/services/base.py`
- Modify: `rag_modules/interfaces/api/services/build.py`
- Modify: `rag_modules/interfaces/api/app.py`
- Modify: `rag_modules/interfaces/api/build_models.py`
- Modify: `tests/test_api_app.py`
- Rewrite: `tests/test_build_job_persistence.py`
- Modify: `tests/test_public_surface_boundaries.py`
- Modify: `tests/test_module_boundary_facades.py`
- Delete: `rag_modules/interfaces/api/build_job_store.py`
- Delete: `rag_modules/interfaces/api/build_jobs/`

- [ ] **Step 1: Add failing composition and boundary tests**

Rewrite persistence-test construction to use `compose_build_job_application` and canonical runtime
adapters before deleting the old facade. Add an API test that injects a recording
`BuildJobApplicationService` and proves every route calls that service. Add AST boundary rules
prohibiting `rag_modules/interfaces/api/` from importing `rag_modules.runtime.build_jobs` or
`rag_modules.app.composition`. Replace the old facade test with:

```python
def test_build_job_store_facade_is_retired(self) -> None:
    with self.assertRaises(ModuleNotFoundError):
        importlib.import_module("rag_modules.interfaces.api.build_job_store")
```

Add a boundary assertion that `PersistentBuildJobRegistry`, `FileBuildJobStore`, and the old
`BuildJobRunner` name are absent from all `rag_modules.interfaces.api` exports.

- [ ] **Step 2: Run cutover tests and observe old-construction failures**

```powershell
python -m pytest tests/test_build_job_persistence.py tests/test_api_app.py tests/test_public_surface_boundaries.py tests/test_module_boundary_facades.py -q
```

Expected: FAIL because the API still constructs and exports old concrete components.

- [ ] **Step 3: Add the composition root**

Move `_GraphRAGApiServiceLocks` and `_resolve_shared_api_locks` from the API base into
`rag_modules/app/runtime_operations.py` as `RuntimeOperationCoordinator` and
`resolve_runtime_operation_coordinator`. Preserve the existing context-manager behavior so answer,
inspection, and lifecycle concurrency do not change.

Implement internal `compose_build_job_application(system, config, coordinator)`. It runs
`BuildJobStoreMigrator`, constructs `FileBuildJobRepository` with typed settings, constructs
`BuildJobExecutor` and `InProcessBuildJobRunner`, then returns `BuildJobApplicationService`.
Backend selection remains explicit:

```python
if config.api.build_job_runner_backend != "in_process":
    raise ValueError(f"Unsupported build job runner backend: {config.api.build_job_runner_backend!r}")
```

Expose that internal composer through `assemble_build_job_application()` in
`rag_modules/app/assembly.py`. API modules import only the public assembly function and application
types; they never import internal composition or runtime adapters. The stable extension seam is
constructor injection and the two ports; no adapter registry or dynamic import mechanism is
introduced.

- [ ] **Step 4: Rewire API construction and typed error mapping**

Change `GraphRAGBuildApiService.__init__` to require `build_jobs: BuildJobApplicationService` and
retain only API diagnostics/artifact behavior. Delegate submit/list/get/cancel/retry/startup/shutdown
to the application service and map typed application exceptions to existing API exceptions.
`startup()` always starts build-job recovery and execution regardless of the optional runtime
auto-initialize flag. If recovery returns an interrupted snapshot, invoke the existing candidate
manifest failure recovery before accepting new submissions.

Update `create_build_api_app()` to resolve the system/config, call
`assemble_build_job_application()`, then construct the API service. Add an optional
`build_job_application` argument for tests and
embedding callers; it is the stable application injection point, not a concrete adapter escape.

Map claimed snapshots to public queued and interrupted snapshots to the existing public failed
payload before Pydantic validation.

- [ ] **Step 5: Delete obsolete implementation and update imports in one commit**

Delete the old package and facade after `rg` shows no production caller:

```powershell
rg -n "PersistentBuildJobRegistry|FileBuildJobStore|interfaces\.api\.build_jobs|build_job_store" rag_modules scripts
```

Expected before deletion: matches only inside the files being deleted. After deletion, rerun and
expect no output.

- [ ] **Step 6: Run API and boundary suites**

```powershell
python -m pytest tests/test_build_job_persistence.py tests/test_api_app.py tests/test_public_surface_boundaries.py tests/test_module_boundary_facades.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit the cutover**

```powershell
git add -A rag_modules/app rag_modules/runtime rag_modules/interfaces/api tests/test_build_job_persistence.py tests/test_api_app.py tests/test_public_surface_boundaries.py tests/test_module_boundary_facades.py
git commit -m "refactor: cut build jobs over to application ports"
```

## Task 9: Persistence Regression, Configuration, and Documentation

**Files:**
- Modify: `tests/test_build_job_persistence.py`
- Modify: `tests/test_configuration_defaults.py`
- Modify: `tests/test_configuration_section_loaders.py`
- Modify: `rag_modules/configuration/model_sections/api.py`
- Modify: `rag_modules/configuration/env_specs/api.py`
- Modify: `.env.example`
- Modify: `README.md`

- [ ] **Step 1: Rewrite persistence tests using canonical modules**

Extend the rewritten persistence suite so it preserves behavioral cases for completed-job restart visibility, failure sanitization, parallel
service conflict, interrupted candidate manifests, idempotency, pagination, retention, and
corruption. Construct services through `create_build_api_app` or `compose_build_job_application`;
do not import deleted facade names. Add an assertion that the V3 envelope contains no raw exception
or progress secret.

- [ ] **Step 2: Add failing configuration tests**

Assert defaults `build_job_lease_seconds == 30.0` and
`build_job_heartbeat_seconds == 10.0`, environment overrides, and validation that heartbeat is
strictly less than lease duration.

Run:

```powershell
python -m pytest tests/test_build_job_persistence.py tests/test_configuration_defaults.py tests/test_configuration_section_loaders.py -q
```

Expected: FAIL because lease settings and rewritten persistence setup are not complete.

- [ ] **Step 3: Add profile-driven lease settings**

Add to `ApiSettings`:

```python
build_job_lease_seconds: float = Field(default=30.0, ge=1.0)
build_job_heartbeat_seconds: float = Field(default=10.0, ge=0.1)
```

Extend the existing model validator to require heartbeat less than lease. Add
`API_BUILD_JOB_LEASE_SECONDS` and `API_BUILD_JOB_HEARTBEAT_SECONDS` float environment specs. Pass
both settings through composition.

- [ ] **Step 4: Update operator documentation**

Add both variables to `.env.example`. Update README build-job operations to state that accepted
queued jobs are redispatched after restart, expired owned jobs become safely failed/interrupted,
V2 storage is migrated once with a retained backup, and adding a new backend means implementing
the two ports and selecting it in composition. Do not document an external worker as available.

- [ ] **Step 5: Run focused integration tests**

```powershell
python -m pytest tests/test_build_job_domain.py tests/test_build_job_repository_port.py tests/test_build_job_migration.py tests/test_build_job_application.py tests/test_build_job_runner.py tests/test_build_job_persistence.py tests/test_api_app.py tests/test_configuration_defaults.py tests/test_configuration_section_loaders.py tests/test_module_boundary_facades.py tests/test_public_surface_boundaries.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit configuration, docs, and regression coverage**

```powershell
git add tests rag_modules/configuration .env.example README.md
git commit -m "docs: document build job port architecture"
```

## Task 10: Full Verification and Release Gate

**Files:**
- No planned source changes.

- [ ] **Step 1: Verify obsolete names and backend leaks are absent**

```powershell
rg -n "PersistentBuildJobRegistry|FileBuildJobStore|interfaces\.api\.build_jobs|interfaces\.api\.build_job_store" rag_modules scripts tests
rg -n "runtime\.build_jobs" rag_modules/interfaces/api
```

Expected: the first command has matches only in explicit retirement assertions or migration fixture
comments; the second command has no output.

- [ ] **Step 2: Run the complete test suite**

```powershell
python -m pytest -q
```

Expected: PASS with zero failures.

- [ ] **Step 3: Run repository hooks**

```powershell
pre-commit run --all-files
```

Expected: PASS. If Ruff changes files, inspect those exact changes and rerun Step 2 before making a
focused `style: format build job port refactor` commit.

- [ ] **Step 4: Run the offline release gate**

```powershell
python scripts/release_gate.py
```

Expected: PASS.

- [ ] **Step 5: Inspect final change scope**

```powershell
git status --short
git diff --stat fbdeb552..HEAD
git log --oneline -10
```

Expected: no uncommitted task files; commits are limited to the build-job refactor, tests,
configuration, and documentation. Leave unrelated user changes untouched and report them.

## Self-Review

- Spec coverage: typed models, events, reducer, both ports, application service, file repository,
  leases, recovery, runner, migration, composition, API stability, deletion, docs, and release gate
  each have an explicit task.
- Type consistency: repository methods consistently use `claim_next`, `BuildJobLease`,
  `expected_revision`, and typed snapshots; the runner exposes only four lifecycle/notification
  methods.
- Failure semantics: persistence precedes scheduling, schedule failures retain queued work,
  revision and lease loss stop stale workers, migration fails closed, and secrets never enter
  events or diagnostics.
- Scope: the plan does not implement a database, broker, external worker, public event endpoint, or
  dynamic plugin mechanism.
- Compatibility stance: HTTP behavior and persisted customer state are preserved deliberately;
  obsolete Python facades, registries, and dual readers are removed.
