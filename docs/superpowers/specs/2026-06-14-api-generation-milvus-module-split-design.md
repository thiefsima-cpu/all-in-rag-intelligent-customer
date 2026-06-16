# API, Generation, And Milvus Module Split Design

## Goal

Split three oversized implementation modules into clear internal subsystems
without leaving the old files as places where new logic can accumulate. The
refactor should make API service behavior, generation execution, and Milvus
infrastructure easier to understand, test, and extend while preserving current
runtime behavior.

The target modules are:

- `rag_modules.interfaces.api.service`
- `rag_modules.generation.executor`
- `rag_modules.infra.milvus_index_construction`

## Current Context

The repository already has the broad application structure in place:

- `rag_modules.interfaces.api` owns FastAPI app factories, routes, models,
  security, response builders, and build job storage.
- `rag_modules.app` owns application assembly, runtime lifecycle, provider
  composition, and use-case services.
- `rag_modules.generation` already separates prompt building, planning,
  fallback policy, model client access, integration, and service orchestration.
- `rag_modules.infra` already marks Milvus index construction as
  infrastructure, but the concrete Milvus implementation is still one large
  module.

The remaining problem is not missing packages. It is that three files still
own too many reasons to change:

- API service lifecycle, diagnostics, serving answers, stream execution, build
  job orchestration, and executor shutdown are concentrated in one file.
- Generation execution mixes direct completion, two-stage completion,
  streaming, fallback, trace finalization, timeout handling, and usage capture.
- Milvus infrastructure mixes client setup, schema creation, collection
  operations, document writes, similarity search, stats, and blue-green publish
  logic.

## Recommended Approach

Use a decisive internal split with thin compatibility exports. The old module
paths remain importable during the migration window, but their files should no
longer contain business logic. Internal callers should move to the new
canonical modules as part of the refactor.

This is intentionally stronger than extracting helper functions. Each new
module gets one primary responsibility, tests cover both the canonical modules
and legacy import paths, and future changes should land in the canonical
module, not in the compatibility file.

This is also narrower than a full repository-wide domain migration. Retrieval,
graph, app composition, and build pipeline code should stay outside this
change unless a direct dependency needs a small import update.

## API Service Design

Create a service package under `rag_modules.interfaces.api.services`:

```text
rag_modules/interfaces/api/
  service.py                 # compatibility exports only
  services/
    __init__.py
    base.py                  # shared locks, caches, lifecycle guard helpers
    errors.py                # API service exceptions
    serving.py               # serving runtime and answer operations
    build.py                 # build runtime and build job operations
```

`base.py` owns shared implementation that is independent of serving versus
build mode:

- `_GraphRAGApiServiceLocks`
- shared lock resolution on the application system
- `_BaseGraphRAGApiService`
- health, readiness, diagnostics, stats caching, and exclusive runtime guards

`base.py` should not own serving or build executor instances. Serving stream
executor lifecycle belongs in `serving.py`; build executor lifecycle belongs in
`build.py`.

`serving.py` owns `GraphRAGServingApiService` and the private helpers needed to
answer questions and stream events. It may use shared helpers from `base.py`,
but it should not know about build job storage or build job state transitions.

`build.py` owns `GraphRAGBuildApiService` and the build job lifecycle:

- build runtime initialization
- synchronous build endpoint behavior
- asynchronous job submission
- build executor creation and shutdown
- job status updates, logs, result mapping, and failure snapshots

`errors.py` owns:

- `SystemNotReadyError`
- `BuildJobNotFoundError`
- `BuildJobConflictError`
- `_StreamCancelledError`

`service.py` becomes a compatibility export that imports the public service
classes and exceptions from `services.*`. It should not define behavior.

## Generation Execution Design

Create an execution package under `rag_modules.generation.execution`:

```text
rag_modules/generation/
  executor.py                # compatibility export only
  execution/
    __init__.py
    engine.py                # GenerationExecutionEngine public class
    direct.py                # direct completion path
    two_stage.py             # two-stage completion and fallback handoff
    streaming.py             # stream and stream_with_trace behavior
    tracing.py               # trace snapshot/finalization helpers
    timeouts.py              # deadline and remaining-time helpers
```

`engine.py` remains the public orchestration object. It should keep the current
constructor shape and public methods:

- `generate`
- `generate_with_trace`
- `stream`
- `stream_with_trace`
- `compose`
- `compose_from_context`

The engine delegates execution details to small collaborators or functions:

- `direct.py` builds and runs the direct answer prompt.
- `two_stage.py` builds the answer plan, runs two-stage completion, and falls
  back through the existing fallback builder semantics.
- `streaming.py` owns streaming event production, cancellation handling,
  final trace capture, and timeout behavior for streams.
- `tracing.py` owns trace cloning, trace snapshots, empty-trace records,
  token usage capture, retry count capture, and finalization.
- `timeouts.py` owns deadline math so both blocking and streaming paths use
  the same timeout semantics.

`generation/executor.py` becomes a compatibility export for
`GenerationExecutionEngine`. Other generation modules should import from
`generation.execution` after the split.

## Milvus Infrastructure Design

Create a Milvus package under `rag_modules.infra.milvus`:

```text
rag_modules/infra/
  milvus_index_construction.py  # compatibility export only
  milvus/
    __init__.py
    module.py                   # MilvusIndexConstructionModule public class
    client.py                   # client setup and collection primitives
    schema.py                   # collection schema and index config
    writer.py                   # build/add document operations
    search.py                   # similarity search and result mapping
    blue_green.py               # alias, slot, publish, rollback, discard
```

`module.py` keeps the public class and public method surface that existing
callers use. It coordinates specialized helpers rather than implementing all
details inline.

`client.py` owns:

- Milvus client initialization
- collection existence checks
- collection load/delete operations
- collection stats primitives
- close semantics

`schema.py` owns schema and index parameter construction. It should be pure
enough to test without a Milvus server.

`writer.py` owns:

- text truncation and metadata normalization for insert payloads
- full vector index construction
- incremental document append
- embedding calls needed for writes

`search.py` owns:

- query embedding for search
- filter expression construction
- similarity search calls
- result normalization into the current dictionary shape

`blue_green.py` owns:

- active slot selection
- physical collection name derivation
- alias target inspection
- publish, rollback, and discard behavior

`infra/milvus_index_construction.py` becomes a compatibility export for
`MilvusIndexConstructionModule`. `rag_modules.infra.__init__` should export the
same class from the canonical package.

## Public Surface And Compatibility

The refactor should preserve current external behavior:

- Existing imports from `rag_modules.interfaces.api.service` keep working.
- Existing imports from `rag_modules.generation.executor` keep working.
- Existing imports from `rag_modules.infra.milvus_index_construction` keep
  working.
- Public class names, method names, return shapes, exceptions, and route
  behavior remain stable.

The compatibility files must stay thin. A file is acceptable as a compatibility
bridge only if it imports and re-exports canonical objects. It should not own
new branching logic, thread pools, fallback behavior, Milvus operations, or
state mutation.

Internal imports touched by this refactor should prefer the canonical modules:

- API code imports from `rag_modules.interfaces.api.services`.
- Generation code imports from `rag_modules.generation.execution`.
- Infrastructure composition imports from `rag_modules.infra.milvus`.

## Data Flow

Serving API flow remains:

1. FastAPI route receives a request.
2. Route delegates to `GraphRAGServingApiService`.
3. Serving service ensures serving runtime readiness.
4. Application system answers or streams the answer.
5. API response builders preserve the existing HTTP response shape.

Build API flow remains:

1. FastAPI route receives a build or rebuild request.
2. Route delegates to `GraphRAGBuildApiService`.
3. Build service ensures build runtime readiness.
4. Synchronous calls run the build operation directly.
5. Asynchronous calls create a persisted build job and run it through the
   build executor.
6. Job state and logs are updated through the existing build job store.

Generation flow remains:

1. Generation service creates or passes an answer context.
2. `GenerationExecutionEngine` selects the existing plan path.
3. Direct, two-stage, or streaming helpers execute the selected behavior.
4. Trace helpers capture retry count, token usage, elapsed time, and final
   answer metadata.
5. The answer string, stream events, and trace snapshots keep the same shape.

Milvus flow remains:

1. App composition creates `MilvusIndexConstructionModule`.
2. Build pipeline calls collection preparation and vector index construction.
3. Writer helpers create embeddings and insert payloads.
4. Blue-green helper publishes aliases and rolls back on failure.
5. Serving runtime uses the manifest-selected collection for similarity
   search.
6. Search helper maps Milvus results into the existing dictionary contract.

## Error Handling

API services keep existing lock semantics and readiness behavior. Runtime
initialization conflicts should still surface as readiness or conflict errors
with the same response-building path used today.

Generation execution keeps current fallback behavior. If direct or two-stage
model calls fail in a path that currently falls back, the refactor must preserve
that fallback. If streaming cancellation currently suppresses or maps a
specific exception, the streaming helper must preserve that behavior.

Milvus operations keep current failure behavior:

- client setup failures are logged and raised or represented as they are today;
- build failures do not publish a candidate collection;
- publish failures after alias switch attempt rollback;
- rollback failures are logged without hiding the original publish failure;
- search failures return the same safe fallback result shape as before.

## Testing

The implementation should start with focused boundary tests before moving
logic. Required checks:

- API service tests import services from both old and canonical paths.
- Serving API tests still cover health, readiness, initialize, refresh,
  answer, streaming, and diagnostics.
- Build API tests still cover build runtime initialization, synchronous build,
  submitted jobs, job lookup, conflicts, logs, and artifact registry snapshot.
- Generation executor tests cover direct answers, two-stage composition,
  fallback behavior, streaming behavior, trace finalization, retry count, token
  usage, and timeouts.
- Milvus tests cover schema creation, insert payload mapping, search result
  mapping, blue-green slot selection, alias publishing, rollback, discard, and
  collection stats.
- Public surface and dependency-isolation tests assert that compatibility files
  are thin and internal imports use canonical modules where this refactor
  touches them.

The minimum verification suite for this refactor is:

```powershell
pytest tests/test_api_app.py `
  tests/test_generation_executor.py `
  tests/test_milvus_blue_green.py `
  tests/test_public_surface_boundaries.py `
  tests/test_dependency_isolation.py
```

If that targeted suite passes, run the full test suite before final completion
unless local external-service dependencies make a subset explicitly necessary.

## Rollout Plan

Implement in three independent slices so failures stay easy to isolate:

1. API service split.
2. Generation execution split.
3. Milvus infrastructure split.

Each slice should:

- add canonical modules;
- move behavior out of the old file;
- update internal imports touched by the slice;
- keep the old module as a compatibility export;
- run the relevant focused tests before moving to the next slice.

The final cleanup pass should check that the three old files contain only
docstrings, imports, and `__all__`.

## Non-Goals

This refactor should not redesign retrieval, graph reasoning, build pipeline
workflow, prompt semantics, FastAPI route shapes, manifest schemas, or Milvus
collection naming. Those areas may be touched only to update imports required
by the three splits above.
