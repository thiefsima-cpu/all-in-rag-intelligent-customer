# Public Surface Retirement Policy

## Current Policy

The repository uses canonical packages for all internal implementation,
scripts, and ordinary tests. The final legacy facade migration window closes at
removal version `0.2.0`: no legacy bridge remains registered, and retired
import paths now fail instead of forwarding. New code must use canonical imports;
compatibility modules are not an alternate architecture.

The machine-readable source of truth is
[`rag_modules/public_surface_manifest.py`](../rag_modules/public_surface_manifest.py).
Root package exports are public API too: names exposed through
`rag_modules.__all__` are governed by `ROOT_PACKAGE_EXPORTS` in the manifest.
This does not reopen the retired root-facade migration window; root wrapper
modules remain retired unless the manifest explicitly registers a future
bridge.

## Version Governance

The package version, API version, and compatibility removal version are not
interchangeable:

- Package version comes from `[project].version` in `pyproject.toml`. The
  current package version is `0.4.0.dev0`, which is the development release
  axis for Python package publication and customer upgrade notes.
- API version comes from `API_VERSION` in
  `rag_modules/interfaces/api/versioning.py`. The current API version is
  `1.0.0`, served under `/v1`, and describes the HTTP/OpenAPI contract for both
  serving and build apps.
- Compatibility removal version comes from
  `LEGACY_PUBLIC_SURFACE_REMOVAL_VERSION` for the final import-facade closure
  and from the row-level milestones below for later closures. Each removal must
  say whether it is a package-version milestone or an API-version milestone.

The `0.2.0` import-facade retirement is a completed package-version milestone.
The `0.3.0` routing compatibility closure is also a completed package-version
milestone. The unversioned HTTP alias closure belongs to API version `1.0.0`;
it does not imply API version `2.0.0` or package version `1.0.0`.

## Canonical Packages

- Application use cases and ports: `rag_modules.application.*`
- Application composition and runtime facade: `rag_modules.app.*`
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

## Root Package Exports

`rag_modules.__all__` is a public API contract for external Python callers.
Each exported name must be recorded in `ROOT_PACKAGE_EXPORTS`, must point to an
importable canonical module, and must resolve to the same object exposed by the
root package lazy export. Adding, removing, or retargeting one of these names is
a public API change and must update the manifest and focused public-surface
tests in the same patch.

Root package exports are intentionally separate from `ROOT_PUBLIC_SURFACE`.
`ROOT_PUBLIC_SURFACE` tracks legacy wrapper module files under `rag_modules/`,
and it remains empty after the import-facade retirement. In other words,
`from rag_modules import AdvancedGraphRAGSystem` is supported by the root
package export contract, while recreating a retired module such as
`rag_modules.graph_indexing` is still prohibited.
The root wrapper modules remain retired.

## Canonical Internal Facades

Thin package facades may remain when they are the documented import surface for
their package. These are formal export surfaces, not compatibility shims, and
their code comments should use canonical facade or export-surface language.
Current examples include:

- `rag_modules.app.diagnostics` is the single diagnostics DTO facade and imports
  directly from the artifact, runtime, and stats diagnostics owner modules.
- `rag_modules.interfaces.api.answer_models` for answer API DTOs.
- `rag_modules.contracts.build_jobs` for build-job domain models, events,
  reducer logic, and repository/runner ports.
- `rag_modules.app.build_jobs` for the build-job application service and its
  canonical contract exports.
- `rag_modules.runtime.build_jobs` for file-backed repository, migration, and
  in-process runner adapters selected by application composition.
- `rag_modules.routing.execution_strategies` for route execution strategies.
- `rag_modules.infra.milvus_index_construction` for Milvus index construction.
- `rag_modules.graph.data_preparation` for graph data-preparation imports.

Old shim modules without a formal facade role are retired instead. The removed
paths include `rag_modules.neo4j_pool`,
`rag_modules.build_pipeline.graph_data_preparation`,
`rag_modules.evidence_processing.core`, and
`rag_modules.query_understanding.planner_service`.

The `0.4.0.dev0` internal hard cutover also retires namespace-only forwarding
modules that own no behavior:

- `rag_modules.graph.cache` -> `rag_modules.graph.cache_stats` and
  `rag_modules.graph.cache_warmup`
- `rag_modules.graph.evidence` -> `rag_modules.graph.evidence_builder`,
  `rag_modules.graph.evidence_orchestrator`, and `rag_modules.graph.path_ranker`
- `rag_modules.graph.query` -> `rag_modules.graph.query_executor`,
  `rag_modules.graph.query_intent`, and `rag_modules.graph.query_resolution`
- `rag_modules.graph.reasoning` -> `rag_modules.graph.reasoning_strategy`
- `rag_modules.graph.retrieval` -> the focused `rag_modules.graph.retrieval_*`
  modules and `rag_modules.graph.rag_retrieval`
- `rag_modules.interfaces.api.routes` -> `rag_modules.interfaces.api.build_routes`
  and `rag_modules.interfaces.api.serving_routes`

These exact retired paths fail instead of forwarding. Package-level exports
from `rag_modules.graph` remain supported and resolve directly to owner modules.

Consumer-owned runtime ports live in the package that consumes them, such as
`rag_modules.app.ports`, `rag_modules.retrieval.ports`,
`rag_modules.routing.ports`, and `rag_modules.infra.milvus.ports`. No aggregate
runtime port module remains a canonical facade.

## Legacy Bridge Status

No legacy bridge remains registered in `public_surface_manifest.py`.

| Retired module | Canonical replacement | Status | Package removal version |
| --- | --- | --- | --- |
| `config.py` | `rag_modules.configuration` | retired in favor of canonical configuration imports | `0.2.0` |
| `rag_modules.intelligent_query_router` | `rag_modules.routing.RoutingWorkflowService` | retired in favor of canonical routing workflow imports | `0.2.0` |
| `rag_modules.graph_data_preparation` | `rag_modules.graph.data_preparation` | retired in favor of canonical graph data-preparation imports | `0.2.0` |
| `rag_modules.graph_indexing` | `rag_modules.graph.indexing` | retired in favor of canonical graph indexing imports | `0.2.0` |
| `rag_modules.neo4j_pool` | `rag_modules.infra.neo4j.Neo4jConnectionManager` | root-level Neo4j pool export retired | `0.3.0` |
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

| Retired layer | Canonical replacement | Status | Removal axis and version |
| --- | --- | --- | --- |
| unversioned HTTP API aliases | `/v1` serving and build routes | unversioned HTTP API aliases are retired | API version `1.0.0` |
| `rag_modules.routing.IntelligentQueryRouter` | `rag_modules.routing.RoutingWorkflowService` or the routing workflow protocol | `rag_modules.routing.IntelligentQueryRouter` is retired | package version `0.3.0` |
| `rag_modules.interfaces.api.build_job_store` and `rag_modules.interfaces.api.build_jobs` | `rag_modules.contracts.build_jobs`, `rag_modules.app.build_jobs`, and `rag_modules.runtime.build_jobs` by responsibility | API-owned build-job registry/store facades are retired after the ports/events cutover | package version `0.3.0` |

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
- The application-use-case compatibility modules under
  `rag_modules.app.services.answer_*`,
  `rag_modules.app.services.knowledge_base_service`, and
  `rag_modules.app.services.trace_adapters` are retired in favor of
  `rag_modules.application`. The internal aggregates
  `rag_modules.app.contracts`, `rag_modules.app.diagnostics_models`, and
  `rag_modules.runtime.snapshot_utils`, plus the bootstrap invocation support
  modules, must fail instead of forwarding.
- Internal compatibility shells are retired too. Runtime assembly must use
  `BuildRuntimeFactory.build()` and `ServingRuntimeFactory.build()` directly;
  `rag_modules.app.composition.build_runtime_assembler`,
  `rag_modules.app.composition.serving_runtime_assembler`, and
  `rag_modules.app.runtime` must not be recreated. The old internal export
  shims `rag_modules.build_pipeline.graph_data_preparation`,
  `rag_modules.evidence_processing.core`, and
  `rag_modules.query_understanding.planner_service` must not be recreated.
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
- Build-job internals must not import or recreate
  `rag_modules.interfaces.api.build_job_store` or
  `rag_modules.interfaces.api.build_jobs`. Use
  `rag_modules.contracts.build_jobs` for domain events, models, reducer logic,
  ports, and safe projections; `rag_modules.app.build_jobs` for application
  use cases; and `rag_modules.runtime.build_jobs` for concrete V3 file
  persistence, migration, leases, and the in-process runner. FastAPI services
  should depend on `BuildJobApplicationService`, not storage or executor
  adapters.

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
  `rag_modules.application.*`.
- `generation_integration` and `hybrid_retrieval` facades retired in favor of
  `rag_modules.generation.service` and `rag_modules.retrieval.hybrid_service`.
- `QuestionAnswerService` retired in favor of `AnswerWorkflow`.
- `GenerationIntegrationModule` retired in favor of `GenerationWorkflowService`.
- `HybridRetrievalModule`, `HybridLegacyResultTranslator`, and `RetrievalResult`
  retired in favor of `HybridRetrievalService` and evidence-native retrieval
  contracts.
- Root `graph_*` wrappers retired in favor of `rag_modules.graph.*`.
- Graph cache, evidence, query, reasoning, and retrieval namespace forwarders,
  plus the API routes forwarder, retired in favor of their focused owner
  modules during the `0.4.0.dev0` development cycle.
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
- `rag_modules.interfaces.api.build_job_store` and
  `rag_modules.interfaces.api.build_jobs` retired in favor of
  `rag_modules.contracts.build_jobs`, `rag_modules.app.build_jobs`, and
  `rag_modules.runtime.build_jobs`.

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
