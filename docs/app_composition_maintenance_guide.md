# App Composition Maintenance Guide

This guide answers the practical question: when a runtime capability changes,
which provider, factory, or lifecycle service owns the edit?

The short rule is:

- `rag_modules/app/providers.py` owns concrete collaborator selection.
- `rag_modules/app/composition/*_factory.py` owns runtime object graph assembly.
- `rag_modules/app/composition/*_lifecycle_service.py` owns runtime state transitions.
- `SystemRuntimeManager` coordinates already-composed services and stores active state.

## Provider Map

Use the provider boundary when the change is about choosing, constructing, or
threading a concrete collaborator. Do not recreate `provider_components`; the
canonical provider surface is `rag_modules.app.providers`.

| Capability change | Edit here | Notes |
| --- | --- | --- |
| Neo4j manager, graph data module, Milvus/vector index, trace sink, artifact stores, query tracer | `InfrastructureProvider` in `rag_modules/app/providers.py` | Infrastructure adapters are reused by build and serving runtime factories. |
| Document artifact builder or semantic graph schema sync | `BuildPipelineProvider` in `rag_modules/app/providers.py` | Build-only services that materialize artifacts belong here, not in lifecycle services. |
| Retrieval runtime profile, query understanding service, hybrid retrieval, graph retrieval, routing workflow | `RetrievalRuntimeProvider` in `rag_modules/app/providers.py` | Query understanding and retrieval are one serving runtime facet because routing needs both. |
| Grounded generation workflow construction | `RuntimeComponentProvider.provide_generation_module` in `rag_modules/app/providers.py` | Generation is a top-level provider method because serving assembly wires it directly into answer workflow. |
| Runtime stats, diagnostics, shutdown, knowledge base service, answer workflow | `ApplicationServiceProvider` in `rag_modules/app/providers.py` | Application services sit above infrastructure and retrieval/generation collaborators. |

## Factory Map

Use factories when the provider methods already exist and the change is about
how a runtime object graph is assembled.

| Runtime assembly change | Edit here | Notes |
| --- | --- | --- |
| Build runtime wiring, including `BuildRuntime` fields | `rag_modules/app/composition/build_runtime_factory.py` | This is where infrastructure, build-pipeline services, and knowledge-base service become a build runtime. |
| Serving runtime wiring, including retrieval engines, routing workflow, generation, and answer workflow | `rag_modules/app/composition/serving_runtime_factory.py` | This is where query tracer, retrieval runtime, generation, and answer workflow become a serving runtime. |
| Bootstrapper facade construction | `rag_modules/app/composition/bootstrapper_composer.py` | Keep public bootstrappers thin; compose their collaborators here. |
| Provider surface resolution for full system assembly | `rag_modules/app/composition/provider_resolution.py` | This is the only composition helper that should unwrap provider surfaces from bootstrappers or explicit inputs. |

## Lifecycle Map

Use lifecycle services when the change is about initializing, preparing,
refreshing, validating, or closing active runtime state.

| Lifecycle behavior | Edit here | Notes |
| --- | --- | --- |
| Initialize build runtime, initialize serving runtime, initialize full system | `RuntimeInitializationService` | Initialization delegates serving build/prepare work to `ServingRuntimeLifecycleService`. |
| Build serving runtime, prepare artifacts, prepare existing runtime, refresh serving runtime from a build runtime | `ServingRuntimeLifecycleService` | `ServingRuntimeRefreshService` is retired. Keep refresh semantics here. |
| Validate build/serving readiness and raise user-facing readiness errors | `RuntimeReadinessService` | This service owns readiness checks, not runtime construction. |
| Build or rebuild knowledge base and refresh serving runtime afterward | `BuildRuntimeLifecycleService` | Build/rebuild execution lives here, with serving refresh delegated to `ServingRuntimeLifecycleService`. |
| Store active runtime state and expose facade operations | `SystemRuntimeManager` | The manager coordinates injected lifecycle services and `RuntimeStateStore`; avoid adding construction logic here. |
| Shutdown runtime resources | `RuntimeShutdownService` via `ApplicationServiceProvider` | Construction belongs in the provider, execution belongs to the service. |

## Change Recipes

| If you need to change... | Start with... | Then check... |
| --- | --- | --- |
| A new storage or tracing adapter | `InfrastructureProvider` | Build and serving factories consume the new collaborator through provider methods. |
| A new retrieval strategy or routing dependency | `RetrievalRuntimeProvider` | `ServingRuntimeFactory` wires the strategy into `RoutingWorkflowService`. |
| Answer workflow dependencies | `ApplicationServiceProvider.provide_answer_workflow` | `ServingRuntimeFactory` should pass explicit runtime collaborators. |
| Knowledge-base build dependencies | `BuildPipelineProvider` or `ApplicationServiceProvider.provide_knowledge_base_service` | `BuildRuntimeFactory` should remain the assembly point. |
| Hot refresh after build/rebuild | `ServingRuntimeLifecycleService.refresh_from_build` | `BuildRuntimeLifecycleService` should delegate to it. |
| Public bootstrapper behavior | `bootstrapper_composer.py` plus focused bootstrapper tests | Avoid adding new logic to public facade methods. |
| Full system construction order | `system_composer.py` | Keep provider resolution in `provider_resolution.py` and lifecycle bundle assembly in `runtime_lifecycle_service_composer.py`. |

## Boundary Rules

- Do not add forwarding-only classes to preserve old names.
- Do not reintroduce `rag_modules/app/provider_components`.
- Do not reintroduce `ServingRuntimeRefreshService`.
- Keep provider methods about collaborator creation, not active runtime state.
- Keep lifecycle services about runtime transitions, not low-level adapter construction.
- Update focused tests when a boundary moves; boundary tests protect retired import paths and composition ownership.
