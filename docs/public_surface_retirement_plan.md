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
- Contract kernel: `rag_modules.contracts.*`
- Generation: `rag_modules.generation.*`
- Retrieval: `rag_modules.retrieval.*`
- Runtime workflow contracts: `rag_modules.runtime.*`
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
| `rag_modules.intelligent_query_router` | `rag_modules.routing.RoutingWorkflowService` | retired in favor of canonical routing workflow imports | `0.2.0` |
| `rag_modules.graph_data_preparation` | `rag_modules.graph.data_preparation` | retired in favor of canonical graph data-preparation imports | `0.2.0` |
| `rag_modules.graph_indexing` | `rag_modules.graph.indexing` | retired in favor of canonical graph indexing imports | `0.2.0` |
| `rag_modules.configuration.settings` | `rag_modules.configuration`, `rag_modules.configuration.models`, `rag_modules.configuration.loader` | late-migration compatibility exports retired | `0.2.0` |
| `rag_modules.configuration.section_loaders` | `rag_modules.configuration.sections` | late-migration compatibility exports retired | `0.2.0` |
| `rag_modules.interfaces.api.models` | `rag_modules.interfaces.api.answer_models`, `rag_modules.interfaces.api.build_models`, `rag_modules.interfaces.api.diagnostics_models` | late-migration compatibility exports retired | `0.2.0` |
| `rag_modules.interfaces.api.service` | `rag_modules.interfaces.api.services` | late-migration compatibility exports retired | `0.2.0` |
| `rag_modules.generation.client` | `rag_modules.generation.clients` | late-migration compatibility exports retired | `0.2.0` |
| `rag_modules.generation.executor` | `rag_modules.generation.execution` | late-migration compatibility exports retired | `0.2.0` |
| `rag_modules.retrieval.bm25_retriever` | `rag_modules.retrieval.adapters` | late-migration compatibility exports retired | `0.2.0` |
| `rag_modules.retrieval.constraint_retriever` | `rag_modules.retrieval.adapters` | late-migration compatibility exports retired | `0.2.0` |
| `rag_modules.retrieval.graph_kv_retriever` | `rag_modules.retrieval.adapters` | late-migration compatibility exports retired | `0.2.0` |
| `rag_modules.retrieval.vector_retriever` | `rag_modules.retrieval.adapters` | late-migration compatibility exports retired | `0.2.0` |
| `rag_modules.retrieval.retrieval_contracts` | `rag_modules.contracts` | late-migration compatibility exports retired | `0.2.0` |
| `rag_modules.retrieval.contracts` | `rag_modules.contracts` | replaced by independent contract kernel; no compatibility re-export remains | `0.2.0` |
| `rag_modules.query_understanding.planner_models` | `rag_modules.contracts` | replaced by independent contract kernel; no compatibility re-export remains | `0.2.0` |
| `rag_modules.retrieval.runtime_settings` | `rag_modules.contracts`, `rag_modules.retrieval.runtime_profile` | late-migration compatibility exports retired | `0.2.0` |
| `rag_modules.retrieval.runtime_profile.planner_settings` | `rag_modules.contracts` | replaced by independent contract kernel; no compatibility re-export remains | `0.2.0` |
| `rag_modules.retrieval.runtime_profile.semantic_settings` | `rag_modules.contracts` | replaced by independent contract kernel; no compatibility re-export remains | `0.2.0` |

## Compatibility Closure

The already-completed `0.2.0` import-facade retirement is now joined by the
active-layer closure. No active compatibility layers remain; compatibility
paths are not alternate architecture paths.

| Retired layer | Canonical replacement | Status | Removal version |
| --- | --- | --- | --- |
| unversioned HTTP API aliases | `/v1` serving and build routes | unversioned HTTP API aliases are retired | API version `2.0.0` |
| `rag_modules.routing.IntelligentQueryRouter` | `rag_modules.routing.RoutingWorkflowService` or the routing workflow protocol | `rag_modules.routing.IntelligentQueryRouter` is retired | package version `0.3.0` |

HTTP clients must use `/v1`. Python routing code must use
`RoutingWorkflowService` or the routing workflow protocol. Tests may mention the
retired layers only to verify removed routes, removed imports, and canonical
replacement policy.

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
  `rag_modules.compat.*`, `rag_modules.intelligent_query_router`, root graph
  facade modules, or late-migration compatibility exports listed above.
- New implementation lands in canonical packages only.
- Compatibility tests should assert retirement and canonical replacements, not
  legacy import behavior.
- Internal compatibility shells are retired too. Runtime assembly must use
  `BuildRuntimeFactory.build()` and `ServingRuntimeFactory.build()` directly;
  `rag_modules.app.composition.build_runtime_assembler`,
  `rag_modules.app.composition.serving_runtime_assembler`, and
  `rag_modules.app.runtime` must not be recreated.
- Retrieval providers must expose `provide_routing_workflow`. The legacy
  `provide_query_router` provider hook is not a supported fallback.
- The internal app-layer query-understanding facade
  `rag_modules.app.services.query_understanding_service` is retired. Internal
  code must import `rag_modules.query_understanding.service` or the package
  export from `rag_modules.app.services` when it is intentionally using the
  application service package surface.
- Cross-subsystem DTOs and query runtime settings must be imported from
  `rag_modules.contracts`. Runtime, retrieval, and query-understanding packages
  must not own or re-export those shared contracts.
- `rag_modules.app.provider_components` is retired. Provider construction now
  lives in `rag_modules.app.providers`; assembly code should consume
  `RuntimeProviderSurface` rather than recreating provider subpackages.
- `ServingRuntimeRefreshService` is retired. Serving refresh, prepare-existing,
  and build-driven refresh semantics belong to
  `ServingRuntimeLifecycleService`; build/rebuild flows should reach them
  through `BuildRuntimeLifecycleService`.

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
- `rag_modules.intelligent_query_router` and
  `rag_modules.routing.IntelligentQueryRouter` retired in favor of
  `rag_modules.routing.RoutingWorkflowService`.
- `rag_modules.graph_data_preparation` retired in favor of
  `rag_modules.graph.data_preparation`.
- `rag_modules.graph_indexing` retired in favor of
  `rag_modules.graph.indexing`.
- Late-migration compatibility exports retired in favor of split canonical
  packages: `rag_modules.interfaces.api.models` to API model modules,
  `rag_modules.interfaces.api.service` to `rag_modules.interfaces.api.services`,
  `rag_modules.generation.client` to `rag_modules.generation.clients`,
  `rag_modules.generation.executor` to `rag_modules.generation.execution`,
  retrieval adapter/profile facades to `rag_modules.retrieval.adapters` and
  `rag_modules.retrieval.runtime_profile`, shared retrieval/query contracts to
  `rag_modules.contracts`, and configuration facades to
  `rag_modules.configuration` modules.
- `rag_modules.retrieval.contracts`,
  `rag_modules.query_understanding.planner_models`,
  `rag_modules.retrieval.runtime_profile.planner_settings`, and
  `rag_modules.retrieval.runtime_profile.semantic_settings` retired in favor of
  the independent `rag_modules.contracts` kernel.
- Build and serving runtime assembler shims retired in favor of
  `BuildRuntimeFactory.build()` and `ServingRuntimeFactory.build()`.
- `rag_modules.app.runtime` retired in favor of direct imports from
  `rag_modules.app.runtime_state` and `rag_modules.app.runtime_view`.
- Legacy retrieval provider hook `provide_query_router` retired in favor of
  `provide_routing_workflow`.
- `rag_modules.app.provider_components` retired in favor of the canonical
  `rag_modules.app.providers` runtime provider boundary.
- `ServingRuntimeRefreshService` retired in favor of
  `ServingRuntimeLifecycleService.refresh_from_build` and
  `prepare_existing`.

## 0.2.0 Compatibility Note

The final public-surface retirement removes `config.py`,
`rag_modules.intelligent_query_router`, `rag_modules.graph_data_preparation`,
`rag_modules.graph_indexing`, and the late-migration compatibility exports
listed in the status table. Shared DTOs/settings previously owned by retrieval
or query-understanding now live only in `rag_modules.contracts`. External
callers that still import retired paths must migrate to the canonical
replacements listed above. The boundary tests keep this final state in place by
checking the empty legacy manifest, removed files, retired import paths,
canonical internal imports, retired internal compatibility shells, the
independent contract kernel, and metadata that must not recreate old facade
names.
