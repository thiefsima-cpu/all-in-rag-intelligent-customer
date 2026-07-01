# API / Service Oriented Refactor Plan

## Goal

Reshape the project around API/service entrypoints without rewriting the
retrieval core in one step.

The next architecture phase is boundary hardening around the packages that now
exist in the codebase. It is not a literal migration to new `domain/` or
`pipelines/` directories. Domain responsibilities stay in the existing
subsystem packages, and offline pipeline work stays under `build_pipeline/`
unless a future design explicitly reopens that directory-level migration.

## Current Delivery Split

- `main.py`
  - serving-only FastAPI entrypoint
  - owns `/answers`, `/health`, `/stats`, and serving diagnostics/runtime init
- `main_build_service.py`
  - build-only FastAPI entrypoint
  - owns offline build/rebuild and build diagnostics/runtime init

The online serving surface does not expose knowledge-base build endpoints. Build
and rebuild operations are available through the build API only.

## Target Layout

```text
main.py
main_build_service.py

rag_modules/
  configuration/
  interfaces/
    api/
  app/
    bootstrap.py
    runtime.py
    system.py
    composition/
    provider_components/
    services/
      knowledge_base_service.py
      answer_workflow.py
  runtime/
  retrieval/
  graph/
  generation/
  query_understanding/
  routing/
  build_pipeline/
    graph_preparation/
    document_artifacts/
  infra/
    milvus/
    semantic_graph_writer.py
    resilience.py
```

`domain/` and `pipelines/` are no longer the next target layout. They are
deferred naming options only. Creating them should require a separate design
that proves the benefit over the current package boundaries and includes a
focused migration plan.

## Layer Rules

1. `interfaces`
   - Only owns API delivery surfaces.
   - No retrieval, indexing, or model orchestration logic.

2. `configuration`
   - Owns profile loading, environment parsing, typed settings, and section
     assembly.
   - Runtime behavior should read configuration through typed settings instead
     of root-level compatibility modules or ad hoc environment lookups.

3. `app`
   - Owns bootstrap, dependency wiring, runtime state, and use-case services.
   - Coordinates domain modules but does not become a new god object.

4. `runtime`
   - Owns typed cross-layer contracts, request/response models, trace models,
     artifact ports, and runtime DTOs.
   - Should not own orchestration, concrete adapters, or API route behavior.

5. Domain subsystem packages
   - `query_understanding`, `routing`, `retrieval`, `graph`, and `generation`
     own query planning, retrieval orchestration, graph reasoning, evidence,
     and grounded generation policy.
   - They should stay free of API delivery behavior and infrastructure-specific
     side effects except through explicit adapters or ports.

6. `build_pipeline`
   - Owns offline build workflows such as document artifact preparation, graph
     preparation, indexing workflow, manifest lifecycle, and build statistics.
   - This is the canonical pipeline package for the current architecture.

7. `infra`
   - Owns concrete adapters for Neo4j, Milvus, model clients, tracing storage,
     and caches.

## Mapping From Current Code

- `main.py`
  - serving API entrypoint backed by `rag_modules.interfaces.api`.
- `main_build_service.py`
  - build API entrypoint backed by `rag_modules.interfaces.api`.
- `rag_modules.configuration`
  - typed configuration package for profiles, environment values, defaults, and
    section loaders.
- `rag_modules.app.system`
  - application facade for runtime lifecycle and answering use cases.
- `rag_modules.app.composition`
  - composition-root helpers for runtime assembly and lifecycle wiring.
- `rag_modules.app.provider_components`
  - provider wiring internals used by assembly code.
- `rag_modules.app.services`
  - application use-case services, answer workflow, lifecycle diagnostics, and
    runtime shutdown behavior.
- `rag_modules.runtime`
  - shared typed contracts and runtime models.
- `rag_modules.query_understanding`, `rag_modules.routing`,
  `rag_modules.retrieval`, `rag_modules.graph`, and `rag_modules.generation`
  - canonical domain subsystem packages; keep behavior here instead of moving
    it under a new `domain/` tree.
- `rag_modules.build_pipeline`
  - canonical offline pipeline package; keep indexing and build workflow here
    instead of moving it under a new `pipelines/` tree.
- `rag_modules.infra`
  - canonical infrastructure package for concrete storage, graph, model,
    tracing, and vector-store adapters.

## Batch Plan

### Batch 1 - Complete

- Introduce `interfaces/` and `app/`.
- Create `SystemRuntime`, `GraphRAGBootstrapper`, and the new
  `AdvancedGraphRAGSystem`.
- Move knowledge-base lifecycle and question-answer orchestration into
  `app/services/`.
- Keep old import paths as compatibility wrappers.

### Batch 2 - Current Next Phase

- Harden the existing domain subsystem packages instead of introducing
  `domain/`.
- Keep query planning and semantic analysis in `query_understanding` and
  `routing`.
- Keep retrieval orchestration in `retrieval` and graph reasoning in `graph`.
- Keep generation policy and execution in `generation`.
- Pull remaining concrete Neo4j, Milvus, model, tracing, and cache integration
  behind `infra/` adapters or explicit ports.
- Keep shared cross-layer models in `runtime` or package-local `contracts`
  modules rather than ad hoc dictionaries.

### Batch 3 - Pipeline Hardening

- Treat `build_pipeline/` as the canonical offline pipeline package instead of
  introducing `pipelines/indexing/`.
- Keep online serving runtime and offline build runtime separate.
- Keep build workflow dependencies behind build-pipeline ports where practical.
- Introduce explicit request/response DTOs for future API handlers.

## Batch 1 Design Notes

- `interfaces.api`
  - owns FastAPI application factories, routes, DTOs, and service adapters.
- `app.bootstrap`
  - assembles runtime dependencies.
- `app.runtime`
  - stores initialized modules and readiness state.
- `app.system`
  - exposes stable application methods for API services.
- `app.services.*`
  - contain use-case logic instead of lifecycle logic living in the facade.

## Compatibility Policy

- CLI imports and entrypoints are retired; there is no compatibility alias for
  `rag_modules.interfaces.cli_console`, `main_qa.py`, or `main_build_kb.py`.
- New code should import from `rag_modules.app.*` and `rag_modules.interfaces.*`
  first.
- Once batch 2 and 3 settle, deprecated wrappers can be removed.
