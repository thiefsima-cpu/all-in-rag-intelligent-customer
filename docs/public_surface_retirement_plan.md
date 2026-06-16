# Public Surface Retirement Policy

## Current Policy

The repository uses canonical packages for all internal implementation,
scripts, and ordinary tests. Legacy facades remain only as registered external
compatibility bridges during the migration window. New code should use
canonical imports; compatibility modules are not an alternate architecture.

The machine-readable source of truth is
[`rag_modules/public_surface_manifest.py`](../rag_modules/public_surface_manifest.py).

## Canonical Packages

- Application: `rag_modules.app.*`
- Configuration: `rag_modules.configuration.*`
- Generation: `rag_modules.generation.*`
- Retrieval: `rag_modules.retrieval.*`
- Runtime contracts: `rag_modules.runtime.*`
- Routing: `rag_modules.routing.*`
- Query understanding: `rag_modules.query_understanding.*`
- Graph retrieval: `rag_modules.graph.*`
- Build/document artifacts: `rag_modules.build_pipeline.document_artifacts.*`
- Infra adapters: `rag_modules.infra.*`

## Remaining Legacy Bridges

| Legacy module | Canonical module | Phase |
| --- | --- | --- |
| `config.py` | `rag_modules.configuration` | external migration window |
| `rag_modules.intelligent_query_router` | `rag_modules.routing.intelligent_query_router` | external migration window |
| `rag_modules.graph_data_preparation` | `rag_modules.graph.data_preparation` | external migration window |
| `rag_modules.graph_indexing` | `rag_modules.graph.indexing` | external migration window |

These bridges are for external callers that have not migrated yet. Repository
code should import the canonical module directly.

## Internal Freeze Rule

- No internal module, script, or ordinary test may import repo-root `config.py`,
  `rag_modules.compat.*`, or root graph facade modules.
- New implementation lands in canonical packages only.
- Compatibility tests may import legacy facades only to prove external import
  behavior still works.

## Thin Wrapper Rule

Remaining legacy facades may re-export or delegate to their canonical target.
They may not own business logic, lifecycle orchestration, state, fallback
policy, or new dependencies. Wrapper files must be registered in
`public_surface_manifest.py`, and boundary tests must fail if an unregistered
wrapper appears.

Flat runtime and system attributes such as `system.query_router` and
`runtime.data_module` are served by the grouped mapping in
[`rag_modules/app/legacy_surface.py`](../rag_modules/app/legacy_surface.py).
Canonical code should use `system.infrastructure`, `system.retrieval`,
`system.services`, and matching grouped runtime views.

## Retired Facade History

- `evidence` facades retired in favor of `rag_modules.evidence_processing`.
- `application`, `knowledge_base_service`, and `question_answer_service`
  facades retired in favor of `rag_modules.app.system` and
  `rag_modules.app.services.*`.
- `generation_integration` and `hybrid_retrieval` facades retired in favor of
  `rag_modules.generation.integration` and `rag_modules.retrieval.hybrid_facade`.
- Most `graph_*` root wrappers retired; only `graph_data_preparation` and
  `graph_indexing` remain for external import compatibility.
- `indexing_pipeline` facades retired in favor of
  `rag_modules.build_pipeline.document_artifacts`.
- `milvus_index_construction` facades retired in favor of
  `rag_modules.infra.milvus_index_construction`.
- `query_plan`, `query_semantics`, and `runtime_models` facades retired in
  favor of `rag_modules.query_understanding` and `rag_modules.runtime`.
- `rag_modules.compat` namespace retired.

## Final Retirement Criteria

The remaining bridges can be deleted after known repository entrypoints,
documentation, examples, scripts, eval tooling, and downstream consumers
covered by the declared migration window use canonical imports for one release cycle.
Deletion must update `public_surface_manifest.py`, remove the wrapper file, and
keep a compatibility note in release documentation.
