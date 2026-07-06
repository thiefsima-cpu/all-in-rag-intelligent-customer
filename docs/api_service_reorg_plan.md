# API / Service Oriented Refactor Record

> Current status: superseded by
> [architecture.md](architecture.md),
> [app_composition_maintenance_guide.md](app_composition_maintenance_guide.md),
> and [public_surface_retirement_plan.md](public_surface_retirement_plan.md).
> This document records the completed API/service reorganization; do not treat
> older package names here as a target layout.

## Current Delivery Split

GraphRAG C9 is API-only at the user-facing boundary. Console entrypoints from
`pyproject.toml` launch FastAPI factories in `rag_modules.interfaces.api.app`:

- `graph-rag-api` starts the serving API through `create_serving_api_app`.
- `graph-rag-build-api` starts the build API through `create_build_api_app`.

Both API surfaces share the application assembly path through
`create_application_system`. The serving API owns versioned answer, health,
stats, and diagnostics routes. The build API owns versioned build-job submit,
cancel, retry, list, detail, health, and diagnostics routes. Unversioned serving
and build routes are retired; new clients must use `/v1`.

## Current Layout

```text
rag_modules/
  configuration/
  interfaces/
    api/
  app/
    assembly.py
    system.py
    providers/
    composition/
    build_jobs/
    services/
    runtime_state.py
    runtime_view.py
    runtime_views.py
  contracts/
    build_jobs/
    runtime/
  runtime/
    artifacts/
    build_jobs/
  retrieval/
  routing/
  graph/
  generation/
  query_understanding/
  build_pipeline/
    graph_preparation/
    document_artifacts/
  infra/
```

`domain/` and `pipelines/` are not current target directories. Domain
responsibilities stay in the existing subsystem packages, and offline build
work stays under `build_pipeline/` unless a future design explicitly reopens
that migration with a focused plan.

## Layer Rules

1. `interfaces`
   - Owns API delivery surfaces, DTOs, response mapping, and API-facing service
     adapters.
   - Does not own retrieval, indexing, provider selection, or build-job storage.

2. `configuration`
   - Owns profile loading, environment parsing, typed settings, defaults, and
     section assembly.
   - Runtime behavior should read typed settings instead of ad hoc environment
     lookups.

3. `app`
   - Owns application assembly, provider boundaries, lifecycle coordination,
     runtime state, and use-case services.
   - `app.providers` is the canonical provider boundary.
   - `app.composition` is the composition root and lifecycle orchestration
     layer.
   - `app.build_jobs` owns build-job application use cases.

4. `contracts`
   - Owns cross-subsystem DTOs and service contracts that should not belong to
     a feature package.
   - `contracts.build_jobs` owns build-job domain models, events, reducer
     logic, repository/runner ports, and the runtime-hook executor contract.

5. `runtime`
   - Owns runtime adapters and runtime-owned support packages, including
     artifact storage, build-job file persistence, build-job migration,
     in-process build-job execution, stats adapters, and snapshot utilities.
   - Does not own HTTP route behavior or application use-case decisions.

6. Domain subsystem packages
   - `query_understanding`, `routing`, `retrieval`, `graph`, and `generation`
     own query planning, route orchestration, retrieval, graph reasoning,
     evidence, and grounded generation behavior.
   - They stay free of API delivery behavior and concrete infrastructure
     choices except through explicit adapters or ports.

7. `build_pipeline`
   - Owns offline knowledge-base build workflows: graph preparation, document
     artifact preparation, vector artifact reuse/publish/rollback, schema sync,
     manifest lifecycle, and build statistics.

8. `infra`
   - Owns concrete adapters for Neo4j, Milvus, model providers, semantic graph
     writing, tracing storage, and resilience helpers.

## Current Mapping

- `rag_modules.interfaces.api`
  - FastAPI factories, route registration, API DTOs, response builders, error
    handlers, security, and API-facing service adapters.
- `rag_modules.app.assembly`
  - Single application assembly entry and default build-job application
    assembly hook.
- `rag_modules.app.providers`
  - Canonical provider surface: infrastructure, build pipeline,
    retrieval runtime, top-level generation module, and application services.
- `rag_modules.app.composition`
  - Runtime factories, lifecycle services, provider resolution, runtime state
    store, runtime manager, and build-job adapter composition.
- `rag_modules.app.build_jobs`
  - Build-job application service over repository and runner ports.
- `rag_modules.contracts.build_jobs`
  - Stable build-job domain and port contracts.
- `rag_modules.runtime.build_jobs`
  - V3 file repository, V2-to-V3 migration, interprocess locks, serialization,
    leases, heartbeat renewal, and local in-process runner.
- `rag_modules.app.services`
  - Application-level answer workflow, knowledge-base service, diagnostics,
    shutdown, and trace adapters.
- `rag_modules.build_pipeline`
  - Canonical offline pipeline package; keep indexing and build workflow here
    instead of moving it under a new `pipelines/` tree.
- `rag_modules.infra`
  - Canonical infrastructure package for concrete storage, graph, model,
    tracing, and vector-store adapters.

## Retired Names

The following names are completed historical stages, not compatibility
surfaces:

- `main.py`, `main_build_service.py`, `main_qa.py`, and `main_build_kb.py`.
- `rag_modules.interfaces.cli_console`.
- `rag_modules.app.runtime`.
- `rag_modules.app.provider_components`.
- `rag_modules.interfaces.api.build_job_store`.
- `rag_modules.interfaces.api.build_jobs`.
- `ServingRuntimeRefreshService`.
- Build and serving runtime assembler shims.
- Late-migration import facades listed in
  [public_surface_retirement_plan.md](public_surface_retirement_plan.md).

Do not recreate these as forwarding wrappers. Code that needs the old
responsibility should choose the current package from the mapping above.

## Historical Outcome

The original reorganization goal was to separate API delivery, application
assembly, runtime lifecycle, domain subsystems, build workflows, and concrete
infrastructure without a broad rewrite. That migration is complete. Current
work should maintain the converged boundaries documented in
`docs/architecture.md` and protected by `tests/test_public_surface_boundaries.py`.
