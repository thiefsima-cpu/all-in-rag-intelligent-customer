# App Composition Convergence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Converge app runtime assembly so provider ownership lives behind `rag_modules.app.providers`, lifecycle classes only keep real state policy, and contributors have a clear maintenance guide.

**Architecture:** Replace the internal `provider_components` package with a single provider-facing app boundary. Merge query-understanding and retrieval provider facets into one retrieval-runtime facet, move diagnostics/shutdown into application services, and remove the pure forwarding serving refresh service by moving its rules into serving lifecycle. Update tests to protect the converged boundary rather than the retired wrappers.

**Tech Stack:** Python 3.11, FastAPI app assembly, Protocol-based provider contracts, unittest/pytest, Ruff.

---

## File Structure

- Create `docs/app_composition_maintenance_guide.md`: maintainer guide for provider, lifecycle, factory, and app-service ownership.
- Modify `docs/architecture.md`: link to the new guide from Runtime Assembly.
- Modify `docs/public_surface_retirement_plan.md`: record `rag_modules.app.provider_components` and `ServingRuntimeRefreshService` as retired internal assembly layers.
- Modify `rag_modules/public_surface_manifest.py`: remove `rag_modules.app.provider_components` from the internal-only surface.
- Replace `rag_modules/app/providers.py`: define provider protocols, default provider groups, `DefaultRuntimeProvider`, and `create_default_runtime_provider`.
- Delete `rag_modules/app/provider_components/__init__.py`, `build_pipeline.py`, `contracts.py`, `diagnostics.py`, `generation.py`, `infrastructure.py`, `lifecycle.py`, `query_understanding.py`, `retrieval.py`, `runtime.py`, and `services.py`.
- Modify `rag_modules/app/contracts.py`, `__init__.py`, `assembly.py`, `bootstrap.py`, and `system.py`: import `RuntimeComponentProvider` from `rag_modules.app.providers`.
- Modify `rag_modules/app/composition/provider_resolution.py`: use `create_default_runtime_provider` and the new provider groups.
- Modify `rag_modules/app/composition/build_runtime_factory.py`: read build services from `provider.services`.
- Modify `rag_modules/app/composition/serving_runtime_factory.py`: use `provider.retrieval_runtime` and root `provider.provide_generation_module`.
- Modify `rag_modules/app/composition/system_composer.py`: resolve diagnostics and shutdown through `provider.services`.
- Modify `rag_modules/app/composition/bootstrapper_composer.py`: import provider contracts from `rag_modules.app.providers`.
- Modify `rag_modules/app/composition/contracts.py`: extend `ServingRuntimeLifecycleServiceProtocol` with refresh semantics.
- Modify `rag_modules/app/composition/serving_runtime_lifecycle_service.py`: add `prepare_existing`, `prepare_if_needed`, and `refresh_from_build`.
- Delete `rag_modules/app/composition/runtime_refresh_service.py`.
- Modify `rag_modules/app/composition/runtime_initialization_service.py`, `build_runtime_lifecycle_service.py`, `runtime_lifecycle_service_composer.py`, `runtime_manager.py`, and `__init__.py`: consume serving lifecycle directly instead of `ServingRuntimeRefreshService`.
- Modify `tests/test_app_system_runtime.py`, `tests/test_build_pipeline_provider.py`, `tests/test_infrastructure_trace_provider.py`, `tests/test_runtime_lifecycle_services.py`, `tests/test_serving_runtime_factory.py`, `tests/test_public_api_manifest.py`, `tests/test_public_surface_boundaries.py`, `tests/test_type_contract_ratchets.py`, and `tests/typecheck/type_contracts.py`: move assertions to the new boundary.

## Task 1: Provider Boundary Tests

**Files:**
- Modify: `tests/test_app_system_runtime.py`
- Modify: `tests/test_build_pipeline_provider.py`
- Modify: `tests/test_infrastructure_trace_provider.py`
- Modify: `tests/typecheck/type_contracts.py`

- [ ] **Step 1: Rewrite provider imports to the new public boundary**

Replace old imports from `rag_modules.app.provider_components.*` with imports from `rag_modules.app.providers`.

```python
from rag_modules.app.providers import (
    ApplicationServiceProvider,
    DefaultRuntimeProvider,
    InfrastructureProvider,
    RetrievalRuntimeProvider,
    create_default_runtime_provider,
)
```

- [ ] **Step 2: Add a failing converged provider-shape test**

In `tests/test_app_system_runtime.py`, replace tests that instantiate `DefaultGenerationComponentProvider`, `DefaultQueryUnderstandingComponentProvider`, and `DefaultRuntimeComponentProvider` with this test.

```python
def test_default_runtime_provider_exposes_converged_capabilities(self) -> None:
    provider = create_default_runtime_provider()

    self.assertIsInstance(provider, DefaultRuntimeProvider)
    self.assertTrue(callable(provider.provide_generation_module))
    self.assertTrue(callable(provider.retrieval_runtime.provide_retrieval_runtime_profile))
    self.assertTrue(callable(provider.retrieval_runtime.provide_query_understanding_service))
    self.assertTrue(callable(provider.retrieval_runtime.provide_routing_workflow))
    self.assertTrue(callable(provider.services.provide_runtime_diagnostics_service))
    self.assertTrue(callable(provider.services.provide_runtime_shutdown_service))
    self.assertFalse(hasattr(provider, "query_understanding"))
    self.assertFalse(hasattr(provider, "lifecycle"))
    self.assertFalse(hasattr(provider, "diagnostics"))
```

- [ ] **Step 3: Update provider injection tests**

In `tests/test_app_system_runtime.py`, change provider construction from separate `query_understanding`, `retrieval`, `diagnostics`, and `lifecycle` facets to `retrieval_runtime` and `services`.

```python
provider = DefaultRuntimeProvider(
    retrieval_runtime=_StubRetrievalRuntimeProvider(),
    services=_StubApplicationServicesProvider(),
)
```

The stub retrieval provider must expose both query-understanding and retrieval workflow methods.

```python
class _StubRetrievalRuntimeProvider:
    def provide_retrieval_runtime_profile(self, config):
        del config
        return SimpleNamespace(name="profile")

    def provide_query_understanding_service(self, *, config, llm_client, retrieval_profile):
        del config, llm_client, retrieval_profile
        return SimpleNamespace(name="understanding")

    def provide_traditional_retrieval(self, **kwargs):
        del kwargs
        return SimpleNamespace(name="traditional")

    def provide_graph_rag_retrieval(self, **kwargs):
        del kwargs
        return SimpleNamespace(name="graph")

    def provide_routing_workflow(self, **kwargs):
        del kwargs
        return SimpleNamespace(name="router")
```

- [ ] **Step 4: Move build-pipeline provider test to the default runtime provider**

In `tests/test_build_pipeline_provider.py`, instantiate the provider through `create_default_runtime_provider`.

```python
provider = create_default_runtime_provider().build_pipeline
```

- [ ] **Step 5: Move infrastructure and diagnostics tests to the new groups**

In `tests/test_infrastructure_trace_provider.py`, replace direct default provider classes with `DefaultRuntimeProvider`.

```python
provider = DefaultRuntimeProvider(query_trace_sink_factory=_CapturingSinkFactory(sink))
tracer = provider.infrastructure.provide_query_tracer(config)
```

For runtime stats, use the service group.

```python
provider = create_default_runtime_provider()
stats_access = provider.services.provide_runtime_stats_access(config=build_test_config())
```

- [ ] **Step 6: Update typecheck contract imports**

In `tests/typecheck/type_contracts.py`, use the new provider protocols.

```python
from rag_modules.app.providers import (
    ApplicationServiceProvider,
    InfrastructureProvider,
    RetrievalRuntimeProvider,
    create_default_runtime_provider,
)

runtime_provider = create_default_runtime_provider()
infrastructure_provider: InfrastructureProvider = runtime_provider.infrastructure
retrieval_provider: RetrievalRuntimeProvider = runtime_provider.retrieval_runtime
service_provider: ApplicationServiceProvider = runtime_provider.services
```

- [ ] **Step 7: Run provider-focused tests and confirm they fail**

Run:

```powershell
python -m pytest tests/test_app_system_runtime.py tests/test_build_pipeline_provider.py tests/test_infrastructure_trace_provider.py -q
```

Expected: FAIL with import errors or missing `DefaultRuntimeProvider` / `retrieval_runtime` attributes.

- [ ] **Step 8: Commit the failing tests**

```powershell
git add tests/test_app_system_runtime.py tests/test_build_pipeline_provider.py tests/test_infrastructure_trace_provider.py tests/typecheck/type_contracts.py
git commit -m "test: define converged app provider boundary"
```

## Task 2: Provider Boundary Implementation

**Files:**
- Modify: `rag_modules/app/providers.py`
- Modify: `rag_modules/app/contracts.py`
- Modify: `rag_modules/app/__init__.py`
- Modify: `rag_modules/app/assembly.py`
- Modify: `rag_modules/app/bootstrap.py`
- Modify: `rag_modules/app/system.py`
- Modify: `rag_modules/app/composition/provider_resolution.py`
- Modify: `rag_modules/app/composition/bootstrapper_composer.py`

- [ ] **Step 1: Replace `rag_modules/app/providers.py` with the converged provider surface**

Keep the existing module path, but replace the facade re-export with protocols and defaults. Use existing method bodies from `provider_components` for infrastructure, build-pipeline, retrieval, and application-service construction. The top-level shape must be:

```python
"""Provider boundary and default runtime provider for application assembly."""

from __future__ import annotations

from typing import Protocol, cast

from ..build_pipeline.contracts import DocumentArtifactBuilderPort, SemanticGraphSchemaSyncPort
from ..build_pipeline.document_artifacts import DocumentArtifactBuildService, DocumentIndexCache
from ..build_pipeline.graph_preparation import GraphDataPreparationModule
from ..build_pipeline.schema_sync import SemanticGraphSchemaSyncService
from ..configuration.models import GraphRAGConfig
from ..generation.service import GenerationWorkflowService
from ..graph.retrieval import GraphRAGRetrieval
from ..infra.milvus import MilvusIndexConstructionModule
from ..infra.neo4j import Neo4jConnectionManager
from ..observability.tracing import QueryTracer
from ..observability.tracing_sinks import (
    JsonlQueryTraceSinkFactory,
    NullQueryTraceSink,
    QueryTraceSink,
    QueryTraceSinkFactory,
)
from ..query_understanding.service import QueryUnderstandingService
from ..retrieval import HybridRetrievalService
from ..retrieval.runtime_profile import RetrievalRuntimeProfile, RetrievalRuntimeProfileFactory
from ..routing import RoutingWorkflowProtocol, RoutingWorkflowService
from ..runtime.artifact_adapters import DefaultRuntimeArtifactAccess
from ..runtime.artifact_ports import (
    ArtifactManifestStorePort,
    DocumentArtifactCachePort,
    RuntimeArtifactAccessPort,
)
from ..runtime.artifacts import ArtifactManifestStore
from ..runtime.stats_adapters import DefaultRuntimeStatsAccess
from ..runtime.stats_ports import RuntimeStatsAccessPort
from .runtime_contracts import (
    GraphDataModulePort,
    LLMClientPort,
    Neo4jManagerPort,
    QueryTracerPort,
    VectorIndexModulePort,
)
from .services.answer_workflow import AnswerWorkflow
from .services.knowledge_base_service import KnowledgeBaseService
from .services.runtime_diagnostics_service import RuntimeDiagnosticsService
from .services.runtime_shutdown_service import RuntimeShutdownService


class InfrastructureProvider(Protocol):
    def provide_neo4j_manager(
        self,
        config: GraphRAGConfig,
        existing: Neo4jManagerPort | None = None,
    ) -> Neo4jManagerPort: ...

    def provide_data_module(
        self,
        config: GraphRAGConfig,
        neo4j_manager: Neo4jManagerPort,
        existing: GraphDataModulePort | None = None,
    ) -> GraphDataModulePort: ...

    def provide_index_module(
        self,
        config: GraphRAGConfig,
        existing: VectorIndexModulePort | None = None,
    ) -> VectorIndexModulePort: ...

    def provide_query_trace_sink(
        self,
        config: GraphRAGConfig,
        existing: QueryTraceSink | None = None,
    ) -> QueryTraceSink: ...

    def provide_artifact_manifest_store(
        self,
        config: GraphRAGConfig,
        existing: ArtifactManifestStorePort | None = None,
    ) -> ArtifactManifestStorePort: ...

    def provide_document_artifact_cache(
        self,
        config: GraphRAGConfig,
        existing: DocumentArtifactCachePort | None = None,
        *,
        manifest_store: ArtifactManifestStorePort | None = None,
    ) -> DocumentArtifactCachePort: ...

    def provide_runtime_artifact_access(
        self,
        config: GraphRAGConfig,
        existing: RuntimeArtifactAccessPort | None = None,
    ) -> RuntimeArtifactAccessPort: ...

    def provide_query_tracer(
        self,
        config: GraphRAGConfig,
        existing: QueryTracerPort | None = None,
        *,
        sink: QueryTraceSink | None = None,
    ) -> QueryTracerPort: ...
```

- [ ] **Step 2: Add provider protocols for build pipeline, retrieval runtime, services, and root provider**

Continue in `rag_modules/app/providers.py`.

```python
class BuildPipelineProvider(Protocol):
    def provide_document_artifact_builder(
        self,
        *,
        config: GraphRAGConfig,
        existing: DocumentArtifactBuilderPort | None = None,
        manifest_store: ArtifactManifestStorePort | None = None,
        cache: DocumentArtifactCachePort | None = None,
    ) -> DocumentArtifactBuilderPort: ...

    def provide_semantic_graph_schema_sync(
        self,
        *,
        config: GraphRAGConfig,
        neo4j_manager: Neo4jManagerPort,
        existing: SemanticGraphSchemaSyncPort | None = None,
    ) -> SemanticGraphSchemaSyncPort: ...


class RetrievalRuntimeProvider(Protocol):
    def provide_retrieval_runtime_profile(self, config: GraphRAGConfig) -> RetrievalRuntimeProfile: ...

    def provide_query_understanding_service(
        self,
        *,
        config: GraphRAGConfig,
        llm_client: LLMClientPort,
        retrieval_profile: RetrievalRuntimeProfile,
    ) -> QueryUnderstandingService: ...

    def provide_traditional_retrieval(
        self,
        *,
        config: GraphRAGConfig,
        milvus_module: VectorIndexModulePort,
        data_module: GraphDataModulePort,
        llm_client: LLMClientPort,
        neo4j_manager: Neo4jManagerPort,
        retrieval_profile: RetrievalRuntimeProfile,
    ) -> HybridRetrievalService: ...

    def provide_graph_rag_retrieval(
        self,
        *,
        config: GraphRAGConfig,
        llm_client: LLMClientPort,
        neo4j_manager: Neo4jManagerPort,
        retrieval_profile: RetrievalRuntimeProfile,
    ) -> GraphRAGRetrieval: ...

    def provide_routing_workflow(
        self,
        *,
        config: GraphRAGConfig,
        traditional_retrieval: HybridRetrievalService,
        graph_rag_retrieval: GraphRAGRetrieval,
        llm_client: LLMClientPort,
        retrieval_profile: RetrievalRuntimeProfile,
        query_understanding_service: QueryUnderstandingService,
    ) -> RoutingWorkflowProtocol: ...


class ApplicationServiceProvider(Protocol):
    def provide_runtime_stats_access(
        self,
        *,
        config: GraphRAGConfig,
        existing: RuntimeStatsAccessPort | None = None,
    ) -> RuntimeStatsAccessPort: ...

    def provide_runtime_diagnostics_service(
        self,
        *,
        config: GraphRAGConfig,
        existing: RuntimeDiagnosticsService | None = None,
        runtime_stats_access: RuntimeStatsAccessPort | None = None,
    ) -> RuntimeDiagnosticsService: ...

    def provide_runtime_shutdown_service(
        self,
        *,
        config: GraphRAGConfig,
        existing: RuntimeShutdownService | None = None,
    ) -> RuntimeShutdownService: ...
```

Root provider protocol:

```python
class RuntimeComponentProvider(Protocol):
    infrastructure: InfrastructureProvider
    build_pipeline: BuildPipelineProvider
    retrieval_runtime: RetrievalRuntimeProvider
    services: ApplicationServiceProvider

    def provide_generation_module(self, config: GraphRAGConfig) -> GenerationWorkflowService: ...
```

- [ ] **Step 3: Add default provider classes**

Use these class names in `rag_modules/app/providers.py`:

```python
class DefaultRuntimeProvider:
    """Default provider used by application composition."""

    def __init__(
        self,
        *,
        infrastructure: InfrastructureProvider | None = None,
        build_pipeline: BuildPipelineProvider | None = None,
        retrieval_runtime: RetrievalRuntimeProvider | None = None,
        services: ApplicationServiceProvider | None = None,
        query_trace_sink_factory: QueryTraceSinkFactory | None = None,
        retrieval_profile_factory: RetrievalRuntimeProfileFactory | None = None,
    ) -> None:
        self.infrastructure = infrastructure or _DefaultInfrastructureProvider(
            query_trace_sink_factory=query_trace_sink_factory
        )
        self.build_pipeline = build_pipeline or _DefaultBuildPipelineProvider()
        self.retrieval_runtime = retrieval_runtime or _DefaultRetrievalRuntimeProvider(
            profile_factory=retrieval_profile_factory
        )
        self.services = services or _DefaultApplicationServiceProvider()

    def provide_generation_module(self, config: GraphRAGConfig) -> GenerationWorkflowService:
        return GenerationWorkflowService.from_config(config)

    @property
    def provider(self) -> "DefaultRuntimeProvider":
        return self


def create_default_runtime_provider() -> RuntimeComponentProvider:
    return DefaultRuntimeProvider()
```

Move the old default method bodies into private classes named `_DefaultInfrastructureProvider`, `_DefaultBuildPipelineProvider`, `_DefaultRetrievalRuntimeProvider`, and `_DefaultApplicationServiceProvider`. The service provider must contain runtime stats, diagnostics, shutdown, knowledge-base, and answer-workflow methods.

- [ ] **Step 4: Export only the new provider boundary**

At the bottom of `rag_modules/app/providers.py`, use this `__all__`.

```python
__all__ = [
    "ApplicationServiceProvider",
    "BuildPipelineProvider",
    "DefaultRuntimeProvider",
    "InfrastructureProvider",
    "RetrievalRuntimeProvider",
    "RuntimeComponentProvider",
    "create_default_runtime_provider",
]
```

- [ ] **Step 5: Update app-level type imports**

In `rag_modules/app/contracts.py`, import the runtime provider from the new module.

```python
from .providers import RuntimeComponentProvider
```

In `rag_modules/app/bootstrap.py`, replace the old provider import.

```python
from .providers import RuntimeComponentProvider
```

In `rag_modules/app/composition/bootstrapper_composer.py`, replace the old provider import.

```python
from ..providers import RuntimeComponentProvider
```

- [ ] **Step 6: Update provider resolution**

In `rag_modules/app/composition/provider_resolution.py`, import provider protocols from the new module and use the public factory.

```python
from ..providers import (
    ApplicationServiceProvider,
    BuildPipelineProvider,
    InfrastructureProvider,
    RetrievalRuntimeProvider,
    RuntimeComponentProvider,
    create_default_runtime_provider,
)
```

Update `_create_default_runtime_provider` usage by deleting the local helper and using `create_default_runtime_provider` as the default factory.

```python
self.default_provider_factory = default_provider_factory or create_default_runtime_provider
```

Update `RuntimeProviderSurface`.

```python
@dataclass(frozen=True)
class RuntimeProviderSurface:
    provider: RuntimeComponentProvider
    infrastructure: InfrastructureProvider
    build_pipeline: BuildPipelineProvider
    retrieval_runtime: RetrievalRuntimeProvider
    services: ApplicationServiceProvider

    @classmethod
    def from_provider(cls, provider: RuntimeComponentProvider) -> "RuntimeProviderSurface":
        return cls(
            provider=provider,
            infrastructure=provider.infrastructure,
            build_pipeline=provider.build_pipeline,
            retrieval_runtime=provider.retrieval_runtime,
            services=provider.services,
        )
```

- [ ] **Step 7: Run provider-focused tests**

Run:

```powershell
python -m pytest tests/test_app_system_runtime.py tests/test_build_pipeline_provider.py tests/test_infrastructure_trace_provider.py -q
```

Expected: provider boundary tests pass or fail only in factories/composers that still read old attributes.

- [ ] **Step 8: Commit provider boundary implementation**

```powershell
git add rag_modules/app/providers.py rag_modules/app/contracts.py rag_modules/app/__init__.py rag_modules/app/assembly.py rag_modules/app/bootstrap.py rag_modules/app/system.py rag_modules/app/composition/provider_resolution.py rag_modules/app/composition/bootstrapper_composer.py tests/test_app_system_runtime.py tests/test_build_pipeline_provider.py tests/test_infrastructure_trace_provider.py tests/typecheck/type_contracts.py
git commit -m "refactor: converge app provider boundary"
```

## Task 3: Runtime Factory and System Composer Migration

**Files:**
- Modify: `rag_modules/app/composition/build_runtime_factory.py`
- Modify: `rag_modules/app/composition/serving_runtime_factory.py`
- Modify: `rag_modules/app/composition/system_composer.py`
- Modify: `tests/test_serving_runtime_factory.py`
- Modify: `tests/test_app_system_runtime.py`

- [ ] **Step 1: Update build runtime factory to use services for stats**

In `rag_modules/app/composition/build_runtime_factory.py`, remove `self.diagnostics` and read runtime stats from services.

```python
self.services = provider.services
```

Inside `build`, delete `diagnostics = self.diagnostics` and use:

```python
runtime_stats_access = services.provide_runtime_stats_access(config=config)
```

- [ ] **Step 2: Update serving runtime factory to use the retrieval-runtime facet**

In `rag_modules/app/composition/serving_runtime_factory.py`, replace old attributes.

```python
self.retrieval_runtime = provider.retrieval_runtime
self.services = provider.services
```

Inside `build`, use:

```python
retrieval_runtime = self.retrieval_runtime
generation_service = self.provider.provide_generation_module(config)
retrieval_runtime_profile = retrieval_runtime.provide_retrieval_runtime_profile(config)
query_understanding_service = retrieval_runtime.provide_query_understanding_service(
    config=config,
    llm_client=llm_client,
    retrieval_profile=retrieval_runtime_profile,
)
traditional_retrieval = retrieval_runtime.provide_traditional_retrieval(
    config=config,
    milvus_module=index_module,
    data_module=data_module,
    llm_client=llm_client,
    neo4j_manager=graph_manager,
    retrieval_profile=retrieval_runtime_profile,
)
graph_rag_retrieval = retrieval_runtime.provide_graph_rag_retrieval(
    config=config,
    llm_client=llm_client,
    neo4j_manager=graph_manager,
    retrieval_profile=retrieval_runtime_profile,
)
query_router = retrieval_runtime.provide_routing_workflow(
    config=config,
    traditional_retrieval=traditional_retrieval,
    graph_rag_retrieval=graph_rag_retrieval,
    llm_client=llm_client,
    retrieval_profile=retrieval_runtime_profile,
    query_understanding_service=query_understanding_service,
)
```

- [ ] **Step 3: Update system composer to use service providers**

In `rag_modules/app/composition/system_composer.py`, replace diagnostics/lifecycle provider calls.

```python
runtime_stats_access = provider_surface.services.provide_runtime_stats_access(
    config=config,
)
diagnostics_service = diagnostics_service or (
    provider_surface.services.provide_runtime_diagnostics_service(
        config=config,
        runtime_stats_access=runtime_stats_access,
    )
)
shutdown_service = shutdown_service or (
    provider_surface.services.provide_runtime_shutdown_service(config=config)
)
```

- [ ] **Step 4: Update serving runtime factory tests**

In `tests/test_serving_runtime_factory.py`, replace provider stubs that set `query_understanding` and `retrieval` with a single `retrieval_runtime` object.

```python
provider = SimpleNamespace(
    infrastructure=infrastructure,
    build_pipeline=SimpleNamespace(),
    retrieval_runtime=retrieval_runtime,
    services=services,
    provide_generation_module=lambda config: SimpleNamespace(client=SimpleNamespace()),
)
```

Update the canonical-routing failure to expect the missing method on `retrieval_runtime`.

```python
with self.assertRaisesRegex(AttributeError, "provide_routing_workflow"):
    factory.build(config=config)
```

- [ ] **Step 5: Run factory and app-system tests**

Run:

```powershell
python -m pytest tests/test_serving_runtime_factory.py tests/test_app_system_runtime.py -q
```

Expected: PASS after the factory and composer migrations.

- [ ] **Step 6: Commit factory and composer migration**

```powershell
git add rag_modules/app/composition/build_runtime_factory.py rag_modules/app/composition/serving_runtime_factory.py rag_modules/app/composition/system_composer.py tests/test_serving_runtime_factory.py tests/test_app_system_runtime.py
git commit -m "refactor: route factories through converged providers"
```

## Task 4: Lifecycle Refresh Convergence

**Files:**
- Modify: `tests/test_runtime_lifecycle_services.py`
- Modify: `tests/test_public_surface_boundaries.py`
- Modify: `rag_modules/app/composition/contracts.py`
- Modify: `rag_modules/app/composition/serving_runtime_lifecycle_service.py`
- Delete: `rag_modules/app/composition/runtime_refresh_service.py`
- Modify: `rag_modules/app/composition/runtime_initialization_service.py`
- Modify: `rag_modules/app/composition/build_runtime_lifecycle_service.py`
- Modify: `rag_modules/app/composition/runtime_lifecycle_service_composer.py`
- Modify: `rag_modules/app/composition/runtime_manager.py`
- Modify: `rag_modules/app/composition/__init__.py`

- [ ] **Step 1: Update lifecycle tests to target serving lifecycle directly**

In `tests/test_runtime_lifecycle_services.py`, remove imports of `ServingRuntimeRefreshService`.

```python
from rag_modules.app.composition import (
    BuildRuntimeLifecycleService,
    RuntimeInitializationService,
    RuntimeLifecycleServiceBundle,
    RuntimeLifecycleServiceComposer,
    RuntimeReadinessService,
    ServingRuntimeLifecycleService,
    SystemRuntimeManager,
)
```

Change refresh tests to instantiate `ServingRuntimeLifecycleService` directly.

```python
service = ServingRuntimeLifecycleService(
    serving_runtime_factory=serving_bootstrapper,
    serving_runtime_preparer=serving_bootstrapper,
)
result = service.refresh_from_build(
    serving_runtime,
    build_runtime=build_runtime,
    force=True,
)
```

- [ ] **Step 2: Change bundle assertions**

Update the default bundle test to assert the serving lifecycle service is carried directly.

```python
self.assertIsInstance(bundle.serving_lifecycle_service, ServingRuntimeLifecycleService)
self.assertIsInstance(bundle.build_lifecycle_service, BuildRuntimeLifecycleService)
```

- [ ] **Step 3: Extend serving lifecycle protocol**

In `rag_modules/app/composition/contracts.py`, add the new methods to `ServingRuntimeLifecycleServiceProtocol`.

```python
def prepare_existing(
    self,
    runtime: ServingRuntime | None,
    *,
    shared_runtime: BuildRuntime | None = None,
    progress: ProgressCallback = None,
    force: bool = False,
) -> ServingRuntime | None: ...

def prepare_if_needed(
    self,
    runtime: ServingRuntime,
    *,
    shared_runtime: BuildRuntime | None = None,
    progress: ProgressCallback = None,
) -> ServingRuntime: ...

def refresh_from_build(
    self,
    runtime: ServingRuntime | None,
    *,
    build_runtime: BuildRuntime,
    progress: ProgressCallback = None,
    force: bool = False,
) -> ServingRuntime | None: ...
```

- [ ] **Step 4: Move refresh methods into serving lifecycle**

In `rag_modules/app/composition/serving_runtime_lifecycle_service.py`, add:

```python
def prepare_existing(
    self,
    runtime: ServingRuntime | None,
    *,
    shared_runtime: BuildRuntime | None = None,
    progress: ProgressCallback = None,
    force: bool = False,
) -> ServingRuntime | None:
    if runtime is None:
        return None
    return self.prepare_with_shared_runtime(
        runtime,
        shared_runtime=shared_runtime,
        progress=progress,
        force=force,
    )

def prepare_if_needed(
    self,
    runtime: ServingRuntime,
    *,
    shared_runtime: BuildRuntime | None = None,
    progress: ProgressCallback = None,
) -> ServingRuntime:
    if runtime.system_ready:
        return runtime
    return self.prepare_with_shared_runtime(
        runtime,
        shared_runtime=shared_runtime,
        progress=progress,
    )

def refresh_from_build(
    self,
    runtime: ServingRuntime | None,
    *,
    build_runtime: BuildRuntime,
    progress: ProgressCallback = None,
    force: bool = False,
) -> ServingRuntime | None:
    if runtime is None or not runtime.is_initialized():
        return runtime
    return self.prepare_with_shared_runtime(
        runtime,
        shared_runtime=build_runtime,
        progress=progress,
        force=force,
    )
```

- [ ] **Step 5: Update runtime initialization**

In `rag_modules/app/composition/runtime_initialization_service.py`, delete `serving_runtime_refresh_service` from the constructor and call serving lifecycle directly.

```python
refreshed_runtime = self.serving_runtime_lifecycle_service.prepare_existing(
    current_runtime,
    shared_runtime=build_runtime,
    progress=progress,
)
```

- [ ] **Step 6: Update build lifecycle**

In `rag_modules/app/composition/build_runtime_lifecycle_service.py`, rename the dependency to `serving_lifecycle_service`.

```python
def __init__(
    self,
    *,
    build_runtime_executor: BuildRuntimeExecutorProtocol,
    serving_lifecycle_service: ServingRuntimeLifecycleServiceProtocol,
    readiness_service: RuntimeReadinessService,
) -> None:
    self.build_runtime_executor = build_runtime_executor
    self.serving_lifecycle_service = serving_lifecycle_service
    self.readiness_service = readiness_service
```

Refresh after build through:

```python
serving_runtime = self.serving_lifecycle_service.refresh_from_build(
    serving_runtime,
    build_runtime=build_runtime,
    progress=progress,
    force=True,
)
```

- [ ] **Step 7: Update lifecycle service composer and bundle**

In `rag_modules/app/composition/runtime_lifecycle_service_composer.py`, change the bundle field.

```python
@dataclass(frozen=True)
class RuntimeLifecycleServiceBundle:
    initialization_service: RuntimeInitializationService
    readiness_service: RuntimeReadinessService
    serving_lifecycle_service: ServingRuntimeLifecycleServiceProtocol
    build_lifecycle_service: BuildRuntimeLifecycleService
```

Compose without `ServingRuntimeRefreshService`.

```python
initialization_service = initialization_service or RuntimeInitializationService(
    config=config,
    build_runtime_factory=components.build_runtime_factory,
    serving_runtime_lifecycle_service=components.serving_runtime_lifecycle_service,
)
build_lifecycle_service = build_lifecycle_service or BuildRuntimeLifecycleService(
    build_runtime_executor=components.build_runtime_executor,
    serving_lifecycle_service=components.serving_runtime_lifecycle_service,
    readiness_service=readiness_service,
)
```

- [ ] **Step 8: Update runtime manager**

In `rag_modules/app/composition/runtime_manager.py`, store the lifecycle service directly.

```python
self.serving_lifecycle_service = lifecycle_services.serving_lifecycle_service
```

Change refresh calls:

```python
self.serving_runtime = self.serving_lifecycle_service.prepare_existing(
    self.serving_runtime,
    shared_runtime=self.build_runtime,
    progress=progress,
    force=force,
)
```

and:

```python
refreshed_runtime = self.serving_lifecycle_service.prepare_existing(
    runtime,
    shared_runtime=None,
    progress=progress,
    force=force,
)
```

- [ ] **Step 9: Remove exports and the file**

Remove `ServingRuntimeRefreshService` from `rag_modules/app/composition/__init__.py` and delete `rag_modules/app/composition/runtime_refresh_service.py`.

- [ ] **Step 10: Run lifecycle tests and boundary tests**

Run:

```powershell
python -m pytest tests/test_runtime_lifecycle_services.py tests/test_serving_runtime_factory.py tests/test_public_surface_boundaries.py -q
```

Expected: PASS after tests and imports are updated.

- [ ] **Step 11: Commit lifecycle convergence**

```powershell
git add rag_modules/app/composition tests/test_runtime_lifecycle_services.py tests/test_serving_runtime_factory.py tests/test_public_surface_boundaries.py
git commit -m "refactor: merge serving refresh lifecycle"
```

## Task 5: Retire Provider Components Package

**Files:**
- Delete: `rag_modules/app/provider_components/__init__.py`
- Delete: `rag_modules/app/provider_components/build_pipeline.py`
- Delete: `rag_modules/app/provider_components/contracts.py`
- Delete: `rag_modules/app/provider_components/diagnostics.py`
- Delete: `rag_modules/app/provider_components/generation.py`
- Delete: `rag_modules/app/provider_components/infrastructure.py`
- Delete: `rag_modules/app/provider_components/lifecycle.py`
- Delete: `rag_modules/app/provider_components/query_understanding.py`
- Delete: `rag_modules/app/provider_components/retrieval.py`
- Delete: `rag_modules/app/provider_components/runtime.py`
- Delete: `rag_modules/app/provider_components/services.py`
- Modify: `rag_modules/public_surface_manifest.py`
- Modify: `tests/test_public_api_manifest.py`
- Modify: `tests/test_public_surface_boundaries.py`
- Modify: `tests/test_type_contract_ratchets.py`

- [ ] **Step 1: Remove provider-components from the manifest**

In `rag_modules/public_surface_manifest.py`, delete the `PublicSurfaceEntry` for `rag_modules.app.provider_components`.

- [ ] **Step 2: Update public API manifest test**

In `tests/test_public_api_manifest.py`, remove the provider-components import and assert only `composition` remains internal-only.

```python
def test_internal_only_packages_declare_internal_contract(self) -> None:
    import rag_modules.app.composition as composition

    self.assertTrue(getattr(composition, "INTERNAL_ONLY", False))
    self.assertIn("internal", (composition.__doc__ or "").lower())
    self.assertIn("instead", getattr(composition, "INTERNAL_ONLY_REASON", "").lower())
```

- [ ] **Step 3: Add a retired provider-components boundary guard**

In `tests/test_public_surface_boundaries.py`, add a prohibited retired internal package and scan for imports.

```python
RETIRED_INTERNAL_PACKAGES = frozenset(
    {
        "rag_modules.app.provider_components",
    }
)
```

Add a test:

```python
def test_provider_components_package_is_retired(self) -> None:
    path = RAG_MODULES_DIR / "app" / "provider_components"
    self.assertFalse(path.exists())
```

Extend existing import scans so any import whose module matches `RETIRED_INTERNAL_PACKAGES` fails.

- [ ] **Step 4: Update type-contract ratchet targets**

In `tests/test_type_contract_ratchets.py`, replace provider-component paths with `rag_modules/app/providers.py`.

```python
NO_EXPLICIT_ANY_TARGETS = (
    ROOT / "rag_modules" / "app" / "providers.py",
    ROOT / "rag_modules" / "app" / "bootstrap_facade_contracts.py",
    ROOT / "rag_modules" / "app" / "bootstrap_facade_support.py",
    ROOT / "rag_modules" / "app" / "services" / "answer_models.py",
    ROOT / "rag_modules" / "app" / "services" / "answer_pipeline.py",
    ROOT / "rag_modules" / "app" / "services" / "answer_trace_assembler.py",
    ROOT / "rag_modules" / "app" / "services" / "answer_workflow.py",
    ROOT / "rag_modules" / "app" / "services" / "trace_adapters.py",
    ROOT / "rag_modules" / "interfaces" / "api" / "answer_models.py",
    ROOT / "rag_modules" / "interfaces" / "api" / "build_models.py",
    ROOT / "rag_modules" / "interfaces" / "api" / "diagnostics_models.py",
    ROOT / "rag_modules" / "interfaces" / "api" / "services" / "base.py",
    ROOT / "rag_modules" / "interfaces" / "api" / "services" / "build.py",
    ROOT / "rag_modules" / "interfaces" / "api" / "services" / "serving.py",
    ROOT / "rag_modules" / "interfaces" / "api" / "services" / "serving_readiness.py",
    ROOT / "rag_modules" / "runtime" / "generation_models.py",
    ROOT / "rag_modules" / "runtime" / "graph_models.py",
    ROOT / "rag_modules" / "runtime" / "retrieval_models.py",
    ROOT / "rag_modules" / "runtime" / "route_models.py",
    ROOT / "rag_modules" / "runtime" / "stats_adapters.py",
    ROOT / "rag_modules" / "runtime" / "stats_ports.py",
    ROOT / "rag_modules" / "runtime" / "trace_models.py",
    ROOT / "rag_modules" / "runtime" / "workflow_models.py",
    ROOT / "rag_modules" / "routing" / "contracts.py",
    ROOT / "rag_modules" / "routing" / "execution_strategies.py",
    ROOT / "rag_modules" / "routing" / "search_orchestrator.py",
    ROOT / "rag_modules" / "routing" / "statistics.py",
)
```

- [ ] **Step 5: Delete provider component files**

Use `apply_patch` delete hunks for each file in `rag_modules/app/provider_components/`.

- [ ] **Step 6: Search for retired imports**

Run:

```powershell
rg -n "provider_components|Default[A-Za-z]+ComponentProvider|ServingRuntimeRefreshService" rag_modules tests scripts docs
```

Expected: no production or ordinary test imports of `provider_components`; docs may mention retired names only in the retirement policy or historical superpowers specs.

- [ ] **Step 7: Run public-surface and type-contract tests**

Run:

```powershell
python -m pytest tests/test_public_api_manifest.py tests/test_public_surface_boundaries.py tests/test_type_contract_ratchets.py -q
```

Expected: PASS.

- [ ] **Step 8: Commit provider-components retirement**

```powershell
git add rag_modules tests docs
git commit -m "refactor: retire provider components package"
```

## Task 6: Maintenance Guide and Architecture Link

**Files:**
- Create: `docs/app_composition_maintenance_guide.md`
- Modify: `docs/architecture.md`
- Modify: `docs/public_surface_retirement_plan.md`

- [ ] **Step 1: Create the maintenance guide**

Create `docs/app_composition_maintenance_guide.md` with this structure.

```markdown
# App Composition Maintenance Guide

This guide answers where runtime assembly changes belong. The code remains the source of truth, but new contributors should be able to choose the right app-layer owner before reading every composition file.

## Rule Of Thumb

- Providers construct dependencies.
- Factories assemble runtime object graphs.
- Lifecycle services decide state transitions and side-effect ordering.
- App services own use cases.
- Feature packages own feature behavior.

## Change Map

| Change | Primary owner | Also check | Focused tests |
| --- | --- | --- | --- |
| Neo4j, Milvus, artifact store, trace sink, query tracer construction | `rag_modules/app/providers.py` infrastructure provider | `rag_modules/app/composition/build_runtime_factory.py`, `rag_modules/app/composition/serving_runtime_factory.py` | `tests/test_infrastructure_trace_provider.py`, `tests/test_serving_runtime_factory.py` |
| Document artifacts or semantic schema sync construction | `rag_modules/app/providers.py` build-pipeline provider | `rag_modules/build_pipeline/` | `tests/test_build_pipeline_provider.py` |
| Retrieval profile, query understanding, retrieval engines, routing workflow construction | `rag_modules/app/providers.py` retrieval-runtime provider | `rag_modules/retrieval/`, `rag_modules/query_understanding/`, `rag_modules/routing/` | `tests/test_serving_runtime_factory.py`, retrieval/router tests |
| Generation workflow construction | `rag_modules/app/providers.py` root provider method `provide_generation_module` | `rag_modules/generation/` | `tests/test_app_system_runtime.py`, generation tests |
| Knowledge-base service or answer workflow construction | `rag_modules/app/providers.py` application-service provider | `rag_modules/app/services/` | `tests/test_app_system_runtime.py`, `tests/test_answer_workflow.py` |
| Build/rebuild sequencing and serving refresh after build | `rag_modules/app/composition/build_runtime_lifecycle_service.py` | `rag_modules/app/composition/serving_runtime_lifecycle_service.py` | `tests/test_runtime_lifecycle_services.py` |
| Serving runtime build-ready, prepare, or refresh semantics | `rag_modules/app/composition/serving_runtime_lifecycle_service.py` | `rag_modules/app/composition/serving_runtime_preparer.py` | `tests/test_runtime_lifecycle_services.py`, `tests/test_serving_runtime_factory.py` |
| Initialized/ready error semantics | `rag_modules/app/composition/runtime_readiness_service.py` | API serving readiness tests | `tests/test_runtime_lifecycle_services.py`, `tests/test_api_app.py` |
| Runtime state ownership | `rag_modules/app/composition/runtime_state_store.py` and `runtime_manager.py` | `rag_modules/app/runtime_view.py` | `tests/test_runtime_lifecycle_services.py`, public surface boundary tests |

## Do Not Add

- Compatibility facades for retired internal paths.
- Provider classes that only forward to one constructor without a testable injection reason.
- Lifecycle services that only delegate to another lifecycle service or preparer.
- Feature policy inside provider code.
- Ad hoc dictionaries when typed models or existing ports exist.

## Verification

Run the narrow test listed in the change map first. If the change touches shared runtime assembly, also run:

```powershell
python -m pytest tests/test_app_system_runtime.py tests/test_runtime_lifecycle_services.py tests/test_serving_runtime_factory.py -q
```

For release-sensitive changes, finish with:

```powershell
python scripts/release_gate.py
```
```

- [ ] **Step 2: Link from architecture**

In `docs/architecture.md`, add this paragraph after the Runtime Assembly primary code paths.

```markdown
For day-to-day ownership decisions, see
[`docs/app_composition_maintenance_guide.md`](app_composition_maintenance_guide.md).
It maps common changes to provider, factory, lifecycle, and app-service owners.
```

- [ ] **Step 3: Update public-surface retirement policy**

In `docs/public_surface_retirement_plan.md`, add `rag_modules.app.provider_components` and `ServingRuntimeRefreshService` to the internal freeze history.

```markdown
- `rag_modules.app.provider_components` retired in favor of the public
  `rag_modules.app.providers` boundary. Internal code should not recreate
  provider-component files or import paths.
- `ServingRuntimeRefreshService` retired in favor of
  `ServingRuntimeLifecycleService` owning serving prepare and refresh semantics.
```

- [ ] **Step 4: Run documentation-oriented checks**

Run:

```powershell
python -m pytest tests/test_public_api_manifest.py tests/test_public_surface_boundaries.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit docs**

```powershell
git add docs/app_composition_maintenance_guide.md docs/architecture.md docs/public_surface_retirement_plan.md tests/test_public_surface_boundaries.py tests/test_public_api_manifest.py
git commit -m "docs: add app composition maintenance guide"
```

## Task 7: Final Verification

**Files:**
- Verify: full touched tree

- [ ] **Step 1: Run focused provider and lifecycle tests**

Run:

```powershell
python -m pytest tests/test_app_system_runtime.py tests/test_build_pipeline_provider.py tests/test_infrastructure_trace_provider.py tests/test_serving_runtime_factory.py tests/test_runtime_lifecycle_services.py -q
```

Expected: PASS.

- [ ] **Step 2: Run boundary and type tests**

Run:

```powershell
python -m pytest tests/test_public_api_manifest.py tests/test_public_surface_boundaries.py tests/test_type_contract_ratchets.py -q
```

Expected: PASS.

- [ ] **Step 3: Run import search**

Run:

```powershell
rg -n "provider_components|ServingRuntimeRefreshService|DefaultRuntimeComponentProvider|DefaultGenerationComponentProvider|DefaultLifecycleComponentProvider" rag_modules tests scripts docs
```

Expected: only historical design/plan documents may mention retired names. No production code imports them.

- [ ] **Step 4: Run formatting and lint checks**

Run:

```powershell
pre-commit run --all-files
```

Expected: PASS. If Ruff changes files, review `git diff`, then rerun the focused tests from steps 1 and 2.

- [ ] **Step 5: Run release gate**

Run:

```powershell
python scripts/release_gate.py
```

Expected: PASS. If it fails due to an external service not available locally, capture the exact failure and report it in the final handoff.

- [ ] **Step 6: Commit final verification fixes**

If any formatting or verification fixes were needed:

```powershell
git add rag_modules tests docs
git commit -m "chore: verify app composition convergence"
```

If no files changed, do not create an empty commit.
