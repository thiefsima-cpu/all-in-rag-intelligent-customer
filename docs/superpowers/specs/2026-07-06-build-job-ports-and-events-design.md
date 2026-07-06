# Build Job Ports and Events Design

**Date:** 2026-07-06

**Status:** Approved for implementation planning

## Goal

Refactor build-job orchestration around stable application ports and a versioned event model so a
transactional repository or external worker can be added without changing the FastAPI boundary or
the build-job application service.

This is an internal architecture change. The HTTP routes, response models, idempotency behavior,
pagination behavior, retention policy, safe diagnostics, and build/rebuild semantics remain stable.

## Problem

The current implementation has several useful reliability properties: atomically replaced job
records, cross-process locks, idempotent submission, interrupted-job recovery, bounded history,
and isolated corruption handling. Its abstractions do not yet form a replaceable application
boundary:

- `BuildJobRunner` mixes execution commands with repository queries and diagnostics.
- `InProcessBuildJobRunner` reaches through `PersistentBuildJobRegistry` to concrete repository
  settings and validation behavior.
- `BuildJobRunRequest` exposes `_InterprocessFileLock`, which makes file persistence part of the
  execution contract.
- `GraphRAGBuildApiService` constructs the file store, registry, repository, runtime hooks, and
  runner itself.
- Persistence transitions are imperative methods over ad hoc dictionaries rather than a stable,
  versioned event vocabulary.
- Submission persistence and executor notification are not modeled as separate durable and
  best-effort steps.

Merely renaming the current protocol and concrete repository would preserve these couplings. The
refactor therefore removes the existing compatibility facade and rewires the feature around a
clean application boundary.

## Scope

This design covers:

- typed build-job identifiers, commands, snapshots, pages, leases, failures, and diagnostics;
- an immutable, versioned build-job event model;
- a pure build-job state reducer;
- `BuildJobRepositoryPort` and `BuildJobRunnerPort`;
- application-level build-job orchestration;
- a file-backed repository adapter and in-process runner adapter;
- composition outside the FastAPI-facing service;
- one-time migration from the existing V2 file layout to the V3 envelope;
- focused architecture, migration, repository, runner, API, and release-sensitive tests.

This design does not add a database, message broker, external worker deployment, new API route,
new production dependency, or a public event streaming endpoint.

## Considered Approaches

### Rename existing abstractions

The smallest option is to rename the current `BuildJobRunner` protocol to
`BuildJobRunnerPort`, add a protocol in front of `BuildJobRepository`, and preserve the registry
and existing data flow. This is rejected because the runner would still own queries, repository
validation, and file-lock lifecycle. It would be a naming patch rather than an extension point.

### Ports, snapshots, and versioned domain events

The chosen approach introduces an application service over a repository port and a runner port.
The repository is the sole source of job state. The runner receives scheduling and cancellation
notifications, claims work through the repository, and records transitions as versioned events.
The file adapter keeps an atomically written snapshot and event sequence for each job.

This preserves the current operational footprint while making a future SQL repository, outbox,
or external worker an adapter decision.

### Full distributed event sourcing now

The most expansive option is to introduce a broker, event store, consumer offsets, delivery
retries, and external workers immediately. This is rejected because no current deployment needs
those runtime components. The stable event vocabulary and ports provide the needed seam without
precommitting to a broker.

## Architecture

The dependency direction is:

```text
FastAPI routes
  -> GraphRAGBuildApiService
      -> BuildJobApplicationService
          -> BuildJobRepositoryPort
          -> BuildJobRunnerPort

BuildJobRepositoryPort <- FileBuildJobRepository
BuildJobRunnerPort     <- InProcessBuildJobRunner
```

Domain models, events, reducer logic, ports, and application orchestration live under
`rag_modules/app/build_jobs/`. File persistence and local execution adapters live under
`rag_modules/runtime/build_jobs/`. FastAPI request and response mapping remains under
`rag_modules/interfaces/api/`.

`rag_modules/app/composition/build_jobs.py` is the only production location that chooses the
file repository and in-process runner. The API service receives a fully constructed
`BuildJobApplicationService` and does not construct persistence or execution infrastructure.

## Application Models

Application and port signatures use typed dataclasses rather than mutable dictionaries.

The core models are:

- `BuildJobId`: validated string value object.
- `BuildJobType`: `build` or `rebuild`.
- `BuildJobStatus`: `queued`, `claimed`, `running`, `cancel_requested`, `cancelled`,
  `succeeded`, `failed`, or `interrupted`.
- `SubmitBuildJob`: job type, request ID, idempotency key, and optional retry source.
- `BuildJobSubmission`: typed result with `created` or `replayed` disposition and a snapshot.
- `BuildJobSnapshot`: public job state plus revision and lease metadata.
- `BuildJobListQuery` and `BuildJobPage`: bounded repository query and opaque cursor result.
- `WorkerIdentity`: stable worker ID and backend name.
- `BuildJobLease`: job ID, worker ID, opaque lease token, and expiration timestamp.
- `BuildJobRepositoryDiagnostics`: safe warning counts and stable warning codes.

Internal fields such as revision, lease token, idempotency-key hash, and event payload metadata are
not returned by the public API response mapper.

## Event Model

Every build-job state transition is represented by an immutable event envelope:

```python
@dataclass(frozen=True, slots=True)
class BuildJobEvent:
    event_id: str
    job_id: BuildJobId
    revision: int
    event_type: BuildJobEventType
    schema_version: int
    occurred_at: datetime
    request_id: str
    payload: BuildJobEventPayload
```

`schema_version` starts at `1`. `revision` is monotonic within one job and starts at `1` for a
new V3 job. Event payloads are a closed union of dedicated dataclasses; arbitrary dictionaries are
not accepted at the domain boundary.

The event types and payload purposes are:

- `JobQueued`: records job type, idempotency-key hash, and optional retry source.
- `JobClaimed`: records worker identity, lease token, and lease expiration.
- `JobStarted`: records execution start.
- `JobProgressRecorded`: records a safe stage, safe message, and elapsed milliseconds.
- `JobCancellationRequested`: records a cancellation request without claiming it succeeded.
- `JobCancelled`: records a safe cancellation result.
- `JobSucceeded`: records the typed successful build result.
- `JobFailed`: records a safe typed failure and safe diagnostic snapshot.
- `JobInterrupted`: records loss of an execution lease or process interruption.

Raw exception text, credentials, source document content, prompts, and customer data are forbidden
from event payloads. Existing progress sanitization rules continue to apply before creating a
`JobProgressRecorded` event.

## State Reducer

`rag_modules/app/build_jobs/reducer.py` exposes a pure function that applies one event to a
snapshot. It validates the job ID, next revision, event payload type, and allowed transition.

The primary state flow is:

```text
queued -> claimed -> running -> succeeded
   |         |         |-----> failed
   |         |         |-----> cancel_requested -> cancelled
   |         |         `-----> interrupted
   |         `---------------> interrupted
   `-------------------------> cancel_requested
```

Additional rules are:

- terminal states reject all later transitions;
- progress is valid only while running or cancel requested;
- cancellation is a request, so a cancel-requested job may end as cancelled, failed, or
  succeeded depending on what the worker observes;
- retry creates a new queued job whose `retry_of_job_id` refers to a failed, cancelled, or
  interrupted job;
- an expired lease produces `JobInterrupted`; it does not silently rerun a potentially
  side-effecting build;
- a lease token is required for worker-owned transitions after claim;
- a revision mismatch raises a concurrent-update error instead of overwriting state.

## BuildJobRepositoryPort

The repository port is shaped around application semantics rather than file operations:

```python
class BuildJobRepositoryPort(Protocol):
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
```

The repository owns atomic idempotency checks, the single-active-job rule, optimistic concurrency,
lease validation, recovery, retention, pagination, and corruption diagnostics. It never returns a
file lock, filesystem path, raw JSON mapping, or backend-specific exception.

Submission and idempotency checking occur within one repository critical section. Same-key,
same-type submission returns a replay result. Same-key, different-type submission raises a typed
idempotency conflict. A new submission cannot be accepted while another nonterminal job exists.

## BuildJobRunnerPort

The runner port contains execution notifications only:

```python
class BuildJobRunnerPort(Protocol):
    def start(self) -> None: ...
    def schedule(self, job_id: BuildJobId) -> None: ...
    def notify_cancellation(self, job_id: BuildJobId) -> None: ...
    def shutdown(self) -> None: ...
```

The runner does not expose get, list, pagination, diagnostics, idempotency validation, or state
mutation methods. A runner claims a scheduled job through `BuildJobRepositoryPort`, executes the
build operation, and submits events through the same port.

`schedule` is a best-effort wake-up hint. Durable queued state lives in the repository. `start`
scans `find_dispatchable`, so a process crash between job creation and executor notification does
not lose an accepted job.

`notify_cancellation` provides prompt local interruption. Cancellation correctness does not depend
on that notification: the cancellation-requested snapshot remains durable and is checked at
progress boundaries.

## Application Service

`BuildJobApplicationService` owns the public use cases:

- `startup()` recovers expired leases before starting the runner;
- `submit()` persists the job before notifying the runner;
- `get()` and `list_page()` query only the repository;
- `cancel()` persists `JobCancellationRequested` before notifying the runner;
- `retry()` validates the original terminal state and submits a linked new job;
- `shutdown()` stops the runner.

If repository submission fails, the runner is not called. If scheduling fails after a successful
submission, the queued job remains accepted and recoverable. The service records a safe scheduling
warning and returns the accepted job rather than pretending persistence was rolled back.

## In-Process Runner

The in-process adapter owns a bounded `ThreadPoolExecutor` and local cancellation controls. It does
not own authoritative job state.

When scheduling work, it:

1. claims the next dispatchable job with its worker identity;
2. records `JobStarted`;
3. executes the build or rebuild through typed runtime hooks;
4. sanitizes and records progress events;
5. renews the lease at progress checkpoints;
6. observes durable cancellation state and local cancellation notification;
7. records exactly one terminal event;
8. stops writing immediately if lease validation or revision checks fail.

Shutdown requests cancellation for locally owned tasks, stops accepting new scheduling hints, and
closes the executor without releasing backend-specific locks because leases belong to the
repository.

## File Repository

The file adapter preserves the current directory-per-repository layout and one-record-per-job
isolation. A V3 job record is:

```json
{
  "schema_version": 3,
  "revision": 6,
  "baseline": null,
  "snapshot": {},
  "events": []
}
```

For a newly created V3 job, the first event is `JobQueued` and `baseline` is null. For a migrated
V2 job, `baseline` contains the imported snapshot and new events start after baseline revision
zero.

An event append and its resulting snapshot are written by one atomic file replacement. Store-wide
submission, idempotency, active-job, retention, and migration operations retain an interprocess
critical section internal to the adapter. Lease tokens replace build-flight locks at the port
boundary.

On read, the adapter verifies:

- supported envelope and event schema versions;
- contiguous revisions;
- matching job IDs;
- valid event payloads;
- consistency between the final reduced state and stored snapshot.

One corrupted record is isolated and reported through safe diagnostics. It does not hide healthy
records. Raw file contents and exception messages are never exposed in diagnostics.

A future transactional repository can map the same contract to job snapshots, event rows, leases,
idempotency keys, and an outbox within database transactions.

## Startup and Recovery

Startup order is explicit:

1. complete or fail the V2-to-V3 migration;
2. construct the V3 repository;
3. convert expired claimed or running leases to interrupted jobs;
4. start the runner;
5. redispatch queued jobs without a lease.

An expired lease never triggers implicit execution retry. Operators or clients can use the
existing retry operation to create a linked new job.

Interrupted artifact candidate-manifest recovery remains part of build API startup, but it is
invoked after repository recovery reports an interrupted build.

## Error Model

Application code uses typed exceptions:

- `BuildJobNotFoundError`;
- `BuildJobConflictError`;
- `BuildJobIdempotencyConflictError`;
- `BuildJobInvalidTransitionError`;
- `BuildJobConcurrentUpdateError`;
- `BuildJobLeaseLostError`;
- `BuildJobRepositoryError`;
- `BuildJobDispatchError`.

The API adapter maps these to the existing safe HTTP behavior. Backend-specific `OSError`, JSON
decoder errors, file-lock errors, futures, and executor errors do not cross the adapter boundary.
Unknown execution exceptions become a safe `JobFailed` event with the existing typed
`BUILD_FAILED` response content.

## V2-to-V3 Migration

`BuildJobStoreMigrator` runs before normal repository reads or writes. Under a dedicated
cross-process migration lock, it:

1. identifies the current V2 metadata and job records;
2. validates each source record with the existing safety rules;
3. writes each V3 envelope to a staging directory;
4. verifies staged envelopes through the V3 reader;
5. atomically publishes the V3 directory and metadata marker;
6. retains the source V2 files as a migration backup that is not consulted at runtime.

Migrated snapshots become revision-zero baselines. This preserves known state without inventing a
historical event sequence. All later transitions use normal V3 events.

Once V3 metadata is published, the production repository reads only V3. There is no permanent
dual reader, deprecated alias, compatibility registry, or fallback to the old whole-document
store. A failed or incomplete migration prevents build API startup and leaves the original V2
data available for diagnosis.

## Removed Components

Implementation removes rather than wraps:

- `PersistentBuildJobRegistry`;
- `FileBuildJobStore`;
- the current concrete `BuildJobRepository`;
- the current mixed-responsibility `BuildJobRunner`;
- `rag_modules/interfaces/api/build_job_store.py`;
- old `build_jobs` package re-exports;
- concrete repository and runner construction from `GraphRAGBuildApiService`.

Tests and production code move to canonical imports. No deprecated aliases or forwarding facades
remain. Persisted V2 data receives a one-time migration because data preservation is an
operational requirement, not a Python compatibility surface.

## Public API Behavior

The following behavior remains stable:

- build, rebuild, cancel, retry, get, and list routes;
- versioned and unversioned route parity;
- HTTP status codes and safe error envelopes;
- `Idempotency-Key` validation and replay behavior;
- list ordering, limits, and opaque cursor behavior;
- public job status, timestamps, message, error, logs, result, and retry link fields;
- retention configuration and corruption-summary diagnostics.

Internal `claimed` and `interrupted` states must be mapped deliberately in the public response
model. `claimed` is exposed as queued until execution starts. `interrupted` is exposed as failed
with the existing safe `BUILD_FAILED` object so the current external status vocabulary does not
change.

## Testing Strategy

Implementation follows test-driven development. Every new behavior begins with a focused test
that fails for the expected missing capability before production code is added.

### Domain tests

- valid transition table;
- rejected terminal and invalid transitions;
- revision sequencing;
- lease ownership requirements;
- retry source validation;
- deterministic event reduction;
- event serialization round trips;
- rejection or sanitization of unsafe event content.

### Repository contract tests

A reusable contract suite is run against `FileBuildJobRepository` and any future repository
adapter. It covers submit, replay, conflicts, get, pagination, claim-next, renew, apply, CAS conflicts,
lease loss, recovery, retention, and diagnostics.

### File adapter tests

- one atomic envelope update per transition;
- no file-lock or path type escapes the port;
- cross-process submission conflict;
- idempotency index repair;
- corrupted record isolation;
- snapshot/event consistency validation;
- expired lease recovery;
- queued-job discovery;
- terminal retention and idempotency cleanup.

### Application and runner tests

- persistence occurs before scheduling;
- repository failure prevents scheduling;
- scheduling failure leaves a recoverable queued job;
- startup rediscovers queued jobs;
- cancellation persists before local notification;
- retries create linked jobs;
- runner claims before execution;
- runner records safe progress and one terminal event;
- runner stops after lease loss;
- shutdown terminates local ownership cleanly.

### Migration tests

- representative V2 queued, running, succeeded, failed, cancelled, and retry records;
- revision-zero baseline creation;
- staged V3 verification before publication;
- migration restart idempotency;
- incomplete migration rollback behavior;
- V3-only reads after publication;
- malformed V2 input prevents startup without destroying source data.

### API and boundary tests

- existing build-job HTTP contract remains unchanged;
- API responses do not leak internal revision, lease, or event fields;
- build API service depends on application service rather than concrete adapters;
- AST boundary tests prohibit API modules from importing file repository or in-process runner;
- deleted facades and registry names are absent from package exports.

Verification expands from focused tests to the full suite, Ruff/pre-commit, and
`python scripts/release_gate.py`. Any environment-dependent check that cannot run is reported with
its exact command and failure reason.

## Documentation

Implementation updates the existing build-job design documentation and operator documentation to
describe:

- queued-job redispatch after process restart;
- lease-based interrupted-job handling;
- V2-to-V3 migration and backup behavior;
- unchanged HTTP contracts;
- the composition seam for adding a transactional repository or external worker.

No external-worker deployment instructions are added until such an adapter exists.

## Acceptance Criteria

- API and application code depend on `BuildJobRepositoryPort` and `BuildJobRunnerPort`, not
  concrete storage or execution classes.
- The runner port contains no query, pagination, diagnostics, idempotency, or persistence methods.
- No file lock, filesystem path, future, executor, or raw JSON mapping crosses either port.
- All build-job transitions use the typed event model and pure reducer.
- Job records atomically persist snapshot, revision, and event sequence.
- Accepted queued jobs survive a crash before runner notification and are redispatched on startup.
- Worker-owned transitions enforce revision and lease ownership.
- Existing V2 state migrates once to V3, after which only the V3 reader is used.
- Old registry, file-store facade, mixed runner protocol, and compatibility exports are deleted.
- Existing HTTP behavior and safe data handling remain stable.
- Focused tests, full tests, formatting checks, and release-sensitive checks pass or are reported
  with evidence.

## Self-Review

- The design contains no placeholder requirements.
- Ports do not expose backend-specific concepts.
- Durable state and best-effort scheduling have distinct ownership.
- Event, snapshot, revision, and lease semantics are internally consistent.
- Migration preserves data without preserving obsolete Python abstractions.
- The scope is one cohesive refactor and does not require an external worker or database.
