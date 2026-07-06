# Root Shared Module Convergence Design

## Context

Several shared modules still live directly under `rag_modules/`: artifact helpers,
query constraints, retrieval post-processing, query tracing, and semantic schema helpers.
The repository has already retired root-level public facades, and boundary tests expect
canonical imports rather than compatibility wrappers.

## Goals

- Move root shared modules into package-owned canonical locations.
- Keep behavior unchanged while updating all repository imports.
- Avoid adding new root compatibility facades.
- Add focused boundary coverage so these modules do not return to `rag_modules/`.

## Target Layout

- `rag_modules/runtime/artifacts/`
  - Owns `artifacts.py` and all `artifact_*` helpers.
  - Used by runtime ports, build artifact caches, manifest lifecycle, and artifact registry code.
- `rag_modules/domain/shared/`
  - Owns cross-subsystem domain helpers: `query_constraints.py` and `semantic_schema.py`.
  - Used by graph, retrieval, routing, query understanding, build pipeline, scripts, and tests.
- `rag_modules/retrieval/post_processor.py`
  - Owns retrieval result post-processing currently in `retrieval_post_processor.py`.
  - Used by routing orchestration and model-client port tests.
- `rag_modules/observability/`
  - Owns query tracing and trace sinks currently in `tracing.py` and `tracing_sinks.py`.
  - Used by services, scripts, and tracing tests.

## Compatibility Policy

No new root-level thin wrappers will be created. Internal code, scripts, and tests will import
from canonical packages only. This follows the existing public-surface retirement policy and
keeps `ROOT_PUBLIC_SURFACE` and `LEGACY_PUBLIC_SURFACE` empty.

## Testing

- Add or update boundary tests to assert the migrated root files are absent.
- Update import tests and affected behavior tests to canonical paths.
- Run the public surface tests and targeted artifact, retrieval, routing, and tracing tests.
- Run broader verification if the focused suite exposes shared runtime risk.
