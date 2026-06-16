# API / Service Oriented Refactor Plan

## Goal

Reshape the project around API/service entrypoints without rewriting the
retrieval core in one step.

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
config.py

rag_modules/
  interfaces/
    api/
  app/
    bootstrap.py
    runtime.py
    system.py
    services/
      knowledge_base_service.py
      question_answer_service.py
  domain/                     # future
    query/
    retrieval/
    graph/
    generation/
    runtime/
  infra/                      # future
    graph/
    vector/
    model/
    cache/
    tracing/
  pipelines/                  # future
    indexing/
```

## Layer Rules

1. `interfaces`
   - Only owns API delivery surfaces.
   - No retrieval, indexing, or model orchestration logic.

2. `app`
   - Owns bootstrap, dependency wiring, runtime state, and use-case services.
   - Coordinates domain modules but does not become a new god object.

3. `domain`
   - Owns contracts, retrieval planning, graph reasoning, evidence, and
     generation policies.
   - Should stay free of CLI and infrastructure-specific side effects.

4. `infra`
   - Owns concrete adapters for Neo4j, Milvus, model clients, tracing storage,
     and caches.

5. `pipelines`
   - Owns offline build workflows such as indexing and schema materialization.

## Mapping From Current Code

- `main.py`
  - serving API entrypoint backed by `rag_modules.interfaces.api`.
- `main_build_service.py`
  - build API entrypoint backed by `rag_modules.interfaces.api`.
- `rag_modules/application.py`
  - replace with compatibility wrapper to `rag_modules.app.system`.
- `rag_modules/knowledge_base_service.py`
  - move implementation to `rag_modules.app.services.knowledge_base_service`.
- `rag_modules/question_answer_service.py`
  - move implementation to `rag_modules.app.services.question_answer_service`.
- retrieval, graph, and generation internals
  - stay in place during batch 1; move in later batches once entrypoints and
    runtime contracts are stable.

## Batch Plan

### Batch 1

- Introduce `interfaces/` and `app/`.
- Create `SystemRuntime`, `GraphRAGBootstrapper`, and the new
  `AdvancedGraphRAGSystem`.
- Move knowledge-base lifecycle and question-answer orchestration into
  `app/services/`.
- Keep old import paths as compatibility wrappers.

### Batch 2

- Move query planning and semantic analysis into `domain/query/`.
- Move graph retrieval orchestration into `domain/graph/`.
- Pull concrete Neo4j and Milvus integration behind `infra/` adapters.

### Batch 3

- Move offline indexing flow into `pipelines/indexing/`.
- Separate online serving runtime from offline build runtime.
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
