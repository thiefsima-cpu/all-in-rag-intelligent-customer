# Public Surface Retirement Policy

## Current Policy

The repository uses canonical packages for all internal implementation,
scripts, and ordinary tests. The final legacy facade migration window closes at
removal version `0.2.0`: no legacy bridge remains registered, and retired
import paths now fail instead of forwarding. New code must use canonical imports;
compatibility modules are not an alternate architecture.

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

## Legacy Bridge Status

No legacy bridge remains registered in `public_surface_manifest.py`.

| Retired module | Canonical replacement | Status | Removal version |
| --- | --- | --- | --- |
| `config.py` | `rag_modules.configuration` | retired in favor of canonical configuration imports | `0.2.0` |
| `rag_modules.intelligent_query_router` | `rag_modules.routing.intelligent_query_router` | retired in favor of canonical routing imports | `0.2.0` |
| `rag_modules.graph_data_preparation` | `rag_modules.graph.data_preparation` | retired in favor of canonical graph data-preparation imports | `0.2.0` |
| `rag_modules.graph_indexing` | `rag_modules.graph.indexing` | retired in favor of canonical graph indexing imports | `0.2.0` |

## Scan Rules

- `internal_dependency_guard`: AST scans cover `rag_modules/`, `scripts/`, and
  ordinary `tests/` files so internal code, scripts, and tests cannot import
  retired facade modules or `rag_modules.compat.*`.
- `thin_wrapper_guard`: the manifest still records the wrapper rule for any
  explicitly approved future migration bridge. With the `0.2.0` retirement
  complete, the active legacy surface is empty, so this guard also confirms
  that no unregistered root wrapper is present.

## Internal Freeze Rule

- No internal module, script, or ordinary test may import repo-root `config.py`,
  `rag_modules.compat.*`, `rag_modules.intelligent_query_router`, or root graph
  facade modules.
- New implementation lands in canonical packages only.
- Compatibility tests should assert retirement and canonical replacements, not
  legacy import behavior.
- The internal app-layer query-understanding facade
  `rag_modules.app.services.query_understanding_service` is retired. Internal
  code must import `rag_modules.query_understanding.service` or the package
  export from `rag_modules.app.services` when it is intentionally using the
  application service package surface.

## Retired Facade Rule

Retired facades must not recreate wrapper files, import aliases, serialization
metadata, or package attributes that point at the old module names. The removed
paths will fail instead of forwarding; callers must import the canonical module
directly.

Flat runtime and system attributes such as `system.query_router` and
`runtime.data_module` are retired. Canonical code must use
`system.infrastructure`, `system.retrieval`, `system.services`, and matching
grouped runtime views.

## Retired Facade History

- `evidence` facades retired in favor of `rag_modules.evidence_processing`.
- `application`, `knowledge_base_service`, and `question_answer_service`
  facades retired in favor of `rag_modules.app.system` and
  `rag_modules.app.services.*`.
- `generation_integration` and `hybrid_retrieval` facades retired in favor of
  `rag_modules.generation.service` and `rag_modules.retrieval.hybrid_service`.
- `QuestionAnswerService` retired in favor of `AnswerWorkflow`.
- `GenerationIntegrationModule` retired in favor of `GenerationWorkflowService`.
- `HybridRetrievalModule`, `HybridLegacyResultTranslator`, and `RetrievalResult`
  retired in favor of `HybridRetrievalService` and evidence-native retrieval
  contracts.
- Root `graph_*` wrappers retired in favor of `rag_modules.graph.*`.
- `indexing_pipeline` facades retired in favor of
  `rag_modules.build_pipeline.document_artifacts`.
- `milvus_index_construction` facades retired in favor of
  `rag_modules.infra.milvus_index_construction`.
- `query_plan`, `query_semantics`, and `runtime_models` facades retired in
  favor of `rag_modules.query_understanding` and `rag_modules.runtime`.
- `rag_modules.compat` namespace retired.
- `config.py` retired in favor of `rag_modules.configuration`.
- `rag_modules.intelligent_query_router` retired in favor of
  `rag_modules.routing.intelligent_query_router`.
- `rag_modules.graph_data_preparation` retired in favor of
  `rag_modules.graph.data_preparation`.
- `rag_modules.graph_indexing` retired in favor of
  `rag_modules.graph.indexing`.

## 0.2.0 Compatibility Note

The final public-surface retirement removes `config.py`,
`rag_modules.intelligent_query_router`, `rag_modules.graph_data_preparation`,
and `rag_modules.graph_indexing`. External callers that still import those
paths must migrate to the canonical replacements listed above. The boundary
tests keep this final state in place by checking the empty legacy manifest,
removed files, retired import paths, and metadata that must not recreate old
facade names.
