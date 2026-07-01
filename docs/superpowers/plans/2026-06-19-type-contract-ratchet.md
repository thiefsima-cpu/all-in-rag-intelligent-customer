# Type Contract Ratchet Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create the first strict mypy island around runtime state, provider contracts, and retrieval/generation ports.

**Architecture:** Add narrow structural Protocols for runtime collaborators, then replace boundary `Any` annotations with those ports or existing domain dataclasses. Keep global mypy behavior unchanged, but add a focused strict override and static type-contract fixture so the first island can ratchet forward without forcing a full-repo strict migration.

**Tech Stack:** Python 3.11, dataclasses, `typing.Protocol`, existing runtime/retrieval/generation models, mypy 2.1.0, pytest.

---

## File Structure

- Create: `rag_modules/app/runtime_contracts.py` - structural ports for Neo4j, graph data, vector index, query tracing, and common runtime service collaborators.
- Modify: `rag_modules/app/runtime_state.py` - type runtime dataclass fields with protocols and existing concrete service contracts.
- Modify: `rag_modules/app/runtime_views.py` - type grouped runtime views with the same ports.
- Modify: `rag_modules/app/runtime_view_builder.py` - add return annotations for resolved grouped dependencies.
- Modify: `rag_modules/app/provider_components/contracts.py` - replace provider-boundary `Any` with runtime ports and existing service contracts.
- Modify: `rag_modules/app/provider_components/infrastructure.py` - make default infrastructure provider match the stricter provider protocol.
- Modify: `rag_modules/app/provider_components/retrieval.py` - type retrieval provider parameters using runtime ports and concrete retrieval contracts.
- Modify: `rag_modules/app/provider_components/services.py` - type service provider parameters using runtime ports and routing/generation contracts.
- Modify: `rag_modules/retrieval/candidate_sources.py` - type candidate source runtime as a minimal retrieval Protocol.
- Modify: `rag_modules/retrieval/hybrid_components.py` - type hybrid assembly inputs with runtime ports.
- Modify: `rag_modules/retrieval/hybrid_runtime.py` - type runtime constructor collaborators and properties that are currently implicit.
- Modify: `rag_modules/retrieval/hybrid_runtime_state.py` - type the Neo4j driver slot as `object | None` instead of `Any`.
- Modify: `rag_modules/retrieval/runtime_adapter_factory.py` - type adapter factory inputs with vector-index and retrieval collaborator ports.
- Modify: `rag_modules/generation/decision.py` - use a typed analysis input alias.
- Modify: `rag_modules/generation/context_factory.py` - normalize typed analysis inputs at the context boundary.
- Modify: `rag_modules/generation/planner.py` - replace `Any` analysis parameters with the typed alias.
- Modify: `rag_modules/generation/execution/engine.py` - normalize typed analysis inputs before constructing `AnswerContext`.
- Modify: `rag_modules/generation/execution/streaming.py` - replace `Any` analysis and callback parameters.
- Modify: `rag_modules/runtime/analysis_models.py` - add reusable analysis input aliases and keep compatibility normalization.
- Modify: `rag_modules/runtime/__init__.py` - export the analysis aliases.
- Create: `tests/test_runtime_type_contracts.py` - runtime behavior tests for the new ports and analysis normalization.
- Create: `tests/typecheck/__init__.py` - make the static typecheck fixture importable as a module.
- Create: `tests/typecheck/type_contracts.py` - mypy-only assignments proving default providers and concrete collaborators satisfy the first typed island.
- Modify: `pyproject.toml` - include `tests/typecheck` in mypy inputs and add strict overrides for the first island.

### Task 1: Runtime Collaborator Ports

**Files:**
- Create: `rag_modules/app/runtime_contracts.py`
- Modify: `tests/test_runtime_type_contracts.py`

- [ ] **Step 1: Write the failing runtime contract tests**

Create `tests/test_runtime_type_contracts.py` with:

```python
from __future__ import annotations

import unittest
from types import SimpleNamespace

from rag_modules.app.runtime_contracts import (
    GraphDataModulePort,
    Neo4jManagerPort,
    VectorIndexModulePort,
)
from rag_modules.runtime import QueryAnalysis, ensure_optional_query_analysis
from rag_modules.text_document import TextDocument


class _GraphDataFake:
    def __init__(self) -> None:
        self.documents = [TextDocument(content="doc")]
        self.chunks = [TextDocument(content="chunk")]
        self.closed = False

    def load_graph_data(self) -> dict[str, object]:
        return {"recipes": 1}

    def build_recipe_documents(self) -> list[TextDocument]:
        return list(self.documents)

    def chunk_documents(self, chunk_size: int = 500, chunk_overlap: int = 50) -> list[TextDocument]:
        del chunk_size, chunk_overlap
        return list(self.chunks)

    def get_statistics(self) -> dict[str, object]:
        return {"total_chunks": len(self.chunks)}

    def close(self) -> None:
        self.closed = True


class _VectorIndexFake:
    def __init__(self) -> None:
        self.collection_name = "recipes"
        self.closed = False

    def has_collection(self, collection_name: str | None = None) -> bool:
        return bool(collection_name or self.collection_name)

    def load_collection(self, collection_name: str | None = None) -> bool:
        self.collection_name = collection_name or self.collection_name
        return True

    def build_vector_index(
        self,
        chunks: list[TextDocument],
        *,
        collection_name: str | None = None,
    ) -> bool:
        self.collection_name = collection_name or self.collection_name
        return bool(chunks)

    def similarity_search(
        self,
        query: str,
        k: int = 5,
        filters: dict[str, object] | None = None,
    ) -> list[dict[str, object]]:
        del filters
        return [{"text": query, "score": float(k), "metadata": {}}]

    def get_collection_stats(self, collection_name: str | None = None) -> dict[str, object]:
        return {"collection_name": collection_name or self.collection_name}

    def delete_collection(self, collection_name: str | None = None) -> bool:
        del collection_name
        return True

    def close(self) -> None:
        self.closed = True


class _Neo4jManagerFake:
    def __init__(self) -> None:
        self.driver = SimpleNamespace(name="driver")
        self.closed = False

    def session(self, **kwargs: object) -> object:
        return {"kwargs": kwargs}

    def close(self) -> None:
        self.closed = True


def _uses_graph_data_port(port: GraphDataModulePort) -> dict[str, object]:
    return port.get_statistics()


def _uses_vector_index_port(port: VectorIndexModulePort) -> list[dict[str, object]]:
    return port.similarity_search("tofu", k=2)


def _uses_neo4j_port(port: Neo4jManagerPort) -> object:
    return port.driver


class RuntimeTypeContractTests(unittest.TestCase):
    def test_runtime_protocols_accept_existing_structural_shapes(self) -> None:
        self.assertEqual(_uses_graph_data_port(_GraphDataFake()), {"total_chunks": 1})
        self.assertEqual(_uses_vector_index_port(_VectorIndexFake())[0]["text"], "tofu")
        self.assertEqual(getattr(_uses_neo4j_port(_Neo4jManagerFake()), "name"), "driver")

    def test_optional_analysis_normalizer_preserves_none(self) -> None:
        self.assertIsNone(ensure_optional_query_analysis(None))

    def test_optional_analysis_normalizer_accepts_mapping(self) -> None:
        analysis = ensure_optional_query_analysis(
            {
                "query_complexity": 0.8,
                "relationship_intensity": 0.7,
                "recommended_strategy": "graph_rag",
            }
        )

        self.assertIsInstance(analysis, QueryAnalysis)
        self.assertEqual(analysis.strategy_name, "graph_rag")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the new test and verify RED**

Run:

```powershell
python -m pytest tests/test_runtime_type_contracts.py -q
```

Expected: FAIL with import errors for `rag_modules.app.runtime_contracts` and `ensure_optional_query_analysis`.

- [ ] **Step 3: Add runtime collaborator protocols**

Create `rag_modules/app/runtime_contracts.py` with:

```python
"""Structural runtime collaborator contracts used by app assembly."""

from __future__ import annotations

from typing import Protocol

from ..retrieval.contracts import EvidenceDocument, RetrievalRequest
from ..runtime import (
    AnswerContext,
    GenerationSnapshot,
    GraphRetrievalSnapshot,
    QueryTraceEvent,
    RetrievalOutcome,
    RouteSnapshot,
)
from ..text_document import TextDocument


class Neo4jManagerPort(Protocol):
    """Neo4j manager behavior used by runtime assembly and shutdown."""

    @property
    def driver(self) -> object: ...

    def session(self, **kwargs: object) -> object: ...

    def close(self) -> None: ...


class GraphDataModulePort(Protocol):
    """Graph data loader and document materializer behavior."""

    documents: list[TextDocument]
    chunks: list[TextDocument]

    def load_graph_data(self) -> dict[str, object]: ...

    def build_recipe_documents(self) -> list[TextDocument]: ...

    def chunk_documents(
        self,
        chunk_size: int = 500,
        chunk_overlap: int = 50,
    ) -> list[TextDocument]: ...

    def get_statistics(self) -> dict[str, object]: ...

    def close(self) -> None: ...


class VectorIndexModulePort(Protocol):
    """Vector index behavior used by build, serving, and hybrid retrieval."""

    collection_name: str

    def has_collection(self, collection_name: str | None = None) -> bool: ...

    def load_collection(self, collection_name: str | None = None) -> bool: ...

    def build_vector_index(
        self,
        chunks: list[TextDocument],
        *,
        collection_name: str | None = None,
    ) -> bool: ...

    def similarity_search(
        self,
        query: str,
        k: int = 5,
        filters: dict[str, object] | None = None,
    ) -> list[dict[str, object]]: ...

    def get_collection_stats(self, collection_name: str | None = None) -> dict[str, object]: ...

    def delete_collection(self, collection_name: str | None = None) -> bool: ...

    def close(self) -> None: ...


class QueryTracerPort(Protocol):
    """Query trace behavior consumed by answer workflow and runtime shutdown."""

    def record(
        self,
        query: str,
        analysis: object,
        documents: list[EvidenceDocument] | RetrievalOutcome | AnswerContext,
        latency_ms: float,
        answer: str | None = None,
        error: str | None = None,
        route_trace: dict[str, object] | RouteSnapshot | None = None,
        graph_trace: dict[str, object] | GraphRetrievalSnapshot | None = None,
        generation_trace: dict[str, object] | GenerationSnapshot | None = None,
    ) -> QueryTraceEvent: ...

    def stats(self) -> dict[str, object]: ...

    def close(self) -> None: ...


class HybridCandidateRuntimePort(Protocol):
    """Candidate-source runtime behavior for hybrid retrieval."""

    def dual_level_candidates(self, request: RetrievalRequest) -> list[EvidenceDocument]: ...

    def vector_candidates(self, query: str, *, top_k: int) -> list[EvidenceDocument]: ...

    def bm25_candidates(self, query: str, *, top_k: int) -> list[EvidenceDocument]: ...


__all__ = [
    "GraphDataModulePort",
    "HybridCandidateRuntimePort",
    "Neo4jManagerPort",
    "QueryTracerPort",
    "VectorIndexModulePort",
]
```

- [ ] **Step 4: Add optional analysis normalization alias**

In `rag_modules/runtime/analysis_models.py`, add the import:

```python
from collections.abc import Mapping
```

Add these aliases after `QueryAnalysis`:

```python
AnalysisMapping = Mapping[str, object]
AnalysisInput = QueryAnalysis | AnalysisMapping | None
```

Add this helper below `ensure_query_analysis()`:

```python
def ensure_optional_query_analysis(analysis: AnalysisInput) -> QueryAnalysis | None:
    if analysis is None:
        return None
    return ensure_query_analysis(analysis)
```

Update `rag_modules/runtime/__init__.py` imports:

```python
from .analysis_models import (
    AnalysisInput,
    AnalysisMapping,
    QueryAnalysis,
    SearchStrategy,
    analysis_payload,
    analysis_strategy_name,
    analysis_value,
    ensure_optional_query_analysis,
    ensure_query_analysis,
)
```

Add to `__all__`:

```python
    "AnalysisInput",
    "AnalysisMapping",
    "ensure_optional_query_analysis",
```

- [ ] **Step 5: Run the new test and verify GREEN**

Run:

```powershell
python -m pytest tests/test_runtime_type_contracts.py -q
```

Expected: PASS.

### Task 2: Runtime State And Provider Boundaries

**Files:**
- Modify: `rag_modules/app/runtime_state.py`
- Modify: `rag_modules/app/runtime_views.py`
- Modify: `rag_modules/app/runtime_view_builder.py`
- Modify: `rag_modules/app/provider_components/contracts.py`
- Modify: `rag_modules/app/provider_components/infrastructure.py`
- Modify: `rag_modules/app/provider_components/retrieval.py`
- Modify: `rag_modules/app/provider_components/services.py`
- Modify: `tests/typecheck/__init__.py`
- Modify: `tests/typecheck/type_contracts.py`

- [ ] **Step 1: Add the static typecheck fixture**

Create `tests/typecheck/__init__.py` with:

```python
"""Static mypy fixtures for repository type-contract ratchets."""
```

Create `tests/typecheck/type_contracts.py` with:

```python
from __future__ import annotations

from rag_modules.app.provider_components.contracts import (
    ApplicationServiceComponentProvider,
    InfrastructureComponentProvider,
    RetrievalComponentProvider,
)
from rag_modules.app.provider_components.infrastructure import (
    DefaultInfrastructureComponentProvider,
)
from rag_modules.app.provider_components.retrieval import DefaultRetrievalComponentProvider
from rag_modules.app.provider_components.services import (
    DefaultApplicationServiceComponentProvider,
)
from rag_modules.app.runtime_contracts import (
    GraphDataModulePort,
    Neo4jManagerPort,
    QueryTracerPort,
    VectorIndexModulePort,
)
from rag_modules.app.runtime_state import BuildRuntime, ServingRuntime
from rag_modules.app.runtime_views import (
    SystemInfrastructureView,
    SystemRetrievalView,
    SystemServicesView,
)
from rag_modules.configuration.testing import build_test_config


infrastructure_provider: InfrastructureComponentProvider = DefaultInfrastructureComponentProvider()
retrieval_provider: RetrievalComponentProvider = DefaultRetrievalComponentProvider()
service_provider: ApplicationServiceComponentProvider = DefaultApplicationServiceComponentProvider()


def accept_runtime_ports(
    graph_manager: Neo4jManagerPort,
    data_module: GraphDataModulePort,
    index_module: VectorIndexModulePort,
    query_tracer: QueryTracerPort,
) -> tuple[BuildRuntime, ServingRuntime, SystemInfrastructureView]:
    config = build_test_config()
    build_runtime = BuildRuntime(
        config=config,
        neo4j_manager=graph_manager,
        data_module=data_module,
        index_module=index_module,
    )
    serving_runtime = ServingRuntime(
        config=config,
        neo4j_manager=graph_manager,
        data_module=data_module,
        index_module=index_module,
        query_tracer=query_tracer,
    )
    infrastructure = SystemInfrastructureView(
        query_tracer=query_tracer,
        neo4j_manager=graph_manager,
        data_module=data_module,
        index_module=index_module,
    )
    return build_runtime, serving_runtime, infrastructure


def accept_grouped_views(
    infrastructure: SystemInfrastructureView,
    retrieval: SystemRetrievalView,
    services: SystemServicesView,
) -> tuple[SystemInfrastructureView, SystemRetrievalView, SystemServicesView]:
    return infrastructure, retrieval, services
```

- [ ] **Step 2: Run mypy on the fixture and verify RED**

Run:

```powershell
python -m mypy tests/typecheck/type_contracts.py --config-file pyproject.toml
```

Expected: FAIL because runtime state and provider contracts still expose `Any` and the default providers do not yet satisfy the stricter protocols. If mypy is not installed, record `No module named mypy` and continue with the implementation steps.

- [ ] **Step 3: Type runtime state with ports and existing service contracts**

In `rag_modules/app/runtime_state.py`, replace the imports with:

```python
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from ..artifacts import ArtifactManifest
from ..configuration.models import GraphRAGConfig
from ..graph.retrieval import GraphRAGRetrieval
from ..retrieval import HybridRetrievalModule
from ..retrieval.runtime_profile import RetrievalRuntimeProfile
from ..routing import RoutingWorkflowProtocol
from .runtime_contracts import (
    GraphDataModulePort,
    Neo4jManagerPort,
    QueryTracerPort,
    VectorIndexModulePort,
)

if TYPE_CHECKING:
    from ..generation.service import GenerationWorkflowService
    from ..query_understanding.service import QueryUnderstandingService
    from .services import QuestionAnswerService
    from .services.answer_workflow import AnswerWorkflow
    from .services.knowledge_base_service import KnowledgeBaseService
```

Replace `SharedRuntime` fields with:

```python
    neo4j_manager: Neo4jManagerPort
    data_module: GraphDataModulePort | None = None
    index_module: VectorIndexModulePort | None = None
```

Replace build and serving fields with:

```python
    knowledge_base_service: KnowledgeBaseService | None = None
```

```python
    query_tracer: QueryTracerPort | None = None
    generation_module: GenerationWorkflowService | None = None
    retrieval_runtime_profile: RetrievalRuntimeProfile | None = None
    query_understanding_service: QueryUnderstandingService | None = None
    traditional_retrieval: HybridRetrievalModule | None = None
    graph_rag_retrieval: GraphRAGRetrieval | None = None
    query_router: RoutingWorkflowProtocol | None = None
    answer_workflow: AnswerWorkflow | None = None
    question_answer_service: QuestionAnswerService | None = None
```

Update property return types:

```python
    def generation_service(self) -> GenerationWorkflowService | None:
        return self.generation_module

    @property
    def routing_workflow(self) -> RoutingWorkflowProtocol | None:
        return self.query_router
```

- [ ] **Step 4: Type grouped runtime views and builder helpers**

In `rag_modules/app/runtime_views.py`, replace `Any` imports and fields with:

```python
from typing import TYPE_CHECKING

from ..graph.retrieval import GraphRAGRetrieval
from ..retrieval import HybridRetrievalModule
from ..retrieval.runtime_profile import RetrievalRuntimeProfile
from ..routing import RoutingWorkflowProtocol
from .runtime_contracts import (
    GraphDataModulePort,
    Neo4jManagerPort,
    QueryTracerPort,
    VectorIndexModulePort,
)

if TYPE_CHECKING:
    from ..generation.service import GenerationWorkflowService
    from ..query_understanding.service import QueryUnderstandingService
    from .services import QuestionAnswerService
    from .services.answer_workflow import AnswerWorkflow
    from .services.knowledge_base_service import KnowledgeBaseService
```

Use these dataclass fields:

```python
    query_tracer: QueryTracerPort | None = None
    neo4j_manager: Neo4jManagerPort | None = None
    data_module: GraphDataModulePort | None = None
    index_module: VectorIndexModulePort | None = None
```

```python
    retrieval_runtime_profile: RetrievalRuntimeProfile | None = None
    query_understanding_service: QueryUnderstandingService | None = None
    traditional_retrieval: HybridRetrievalModule | None = None
    graph_rag_retrieval: GraphRAGRetrieval | None = None
    routing_workflow: RoutingWorkflowProtocol | None = None
```

```python
    generation_service: GenerationWorkflowService | None = None
    answer_workflow: AnswerWorkflow | None = None
    question_answer_service: QuestionAnswerService | None = None
    knowledge_base_service: KnowledgeBaseService | None = None
```

In `rag_modules/app/runtime_view_builder.py`, import ports and annotate helpers:

```python
from .runtime_contracts import GraphDataModulePort, Neo4jManagerPort, VectorIndexModulePort
```

```python
    def _resolve_neo4j_manager(
        *,
        build_runtime: BuildRuntime | None,
        serving_runtime: ServingRuntime | None,
    ) -> Neo4jManagerPort | None:
```

```python
    def _resolve_data_module(
        *,
        build_runtime: BuildRuntime | None,
        serving_runtime: ServingRuntime | None,
    ) -> GraphDataModulePort | None:
```

```python
    def _resolve_index_module(
        *,
        build_runtime: BuildRuntime | None,
        serving_runtime: ServingRuntime | None,
    ) -> VectorIndexModulePort | None:
```

- [ ] **Step 5: Type provider contracts and default providers**

In `rag_modules/app/provider_components/contracts.py`, import the ports:

```python
from ..runtime_contracts import (
    GraphDataModulePort,
    Neo4jManagerPort,
    QueryTracerPort,
    VectorIndexModulePort,
)
```

Replace infrastructure method signatures with:

```python
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

    def provide_query_tracer(
        self,
        config: GraphRAGConfig,
        existing: QueryTracerPort | None = None,
        *,
        sink: QueryTraceSink | None = None,
    ) -> QueryTracerPort: ...
```

Replace service/retrieval provider parameters so Neo4j, data, index, and tracer use these ports:

```python
        neo4j_manager: Neo4jManagerPort,
        data_module: GraphDataModulePort,
        index_module: VectorIndexModulePort,
        query_tracer: QueryTracerPort,
```

In `rag_modules/app/provider_components/infrastructure.py`, add return and parameter annotations matching the protocol:

```python
    def provide_neo4j_manager(
        self,
        config: GraphRAGConfig,
        existing: Neo4jManagerPort | None = None,
    ) -> Neo4jManagerPort:
```

```python
    def provide_data_module(
        self,
        config: GraphRAGConfig,
        neo4j_manager: Neo4jManagerPort,
        existing: GraphDataModulePort | None = None,
    ) -> GraphDataModulePort:
```

```python
    def provide_index_module(
        self,
        config: GraphRAGConfig,
        existing: VectorIndexModulePort | None = None,
    ) -> VectorIndexModulePort:
```

```python
    def provide_artifact_manifest_store(
        self,
        config: GraphRAGConfig,
        existing: ArtifactManifestStorePort | None = None,
    ) -> ArtifactManifestStorePort:
```

```python
    def provide_document_artifact_cache(
        self,
        config: GraphRAGConfig,
        existing: DocumentArtifactCachePort | None = None,
        *,
        manifest_store: ArtifactManifestStorePort | None = None,
    ) -> DocumentArtifactCachePort:
```

```python
    def provide_query_tracer(
        self,
        config: GraphRAGConfig,
        existing: QueryTracerPort | None = None,
        *,
        sink: QueryTraceSink | None = None,
    ) -> QueryTracerPort:
```

In `rag_modules/app/provider_components/retrieval.py` and `services.py`, update parameters to use `Neo4jManagerPort`, `GraphDataModulePort`, `VectorIndexModulePort`, and `QueryTracerPort` where applicable.

- [ ] **Step 6: Run type fixture and runtime assembly tests**

Run:

```powershell
python -m pytest tests/test_runtime_type_contracts.py tests/test_application_assembly.py tests/test_app_system_runtime.py -q
```

Expected: PASS.

Run:

```powershell
python -m mypy tests/typecheck/type_contracts.py --config-file pyproject.toml
```

Expected: PASS when mypy is installed. If mypy is unavailable, keep the exact missing-module output for the final handoff.

### Task 3: Retrieval And Generation Port Tightening

**Files:**
- Modify: `rag_modules/retrieval/candidate_sources.py`
- Modify: `rag_modules/retrieval/hybrid_components.py`
- Modify: `rag_modules/retrieval/hybrid_runtime.py`
- Modify: `rag_modules/retrieval/hybrid_runtime_state.py`
- Modify: `rag_modules/retrieval/runtime_adapter_factory.py`
- Modify: `rag_modules/generation/decision.py`
- Modify: `rag_modules/generation/context_factory.py`
- Modify: `rag_modules/generation/planner.py`
- Modify: `rag_modules/generation/execution/engine.py`
- Modify: `rag_modules/generation/execution/streaming.py`

- [ ] **Step 1: Update retrieval candidate-source runtime types**

In `rag_modules/retrieval/candidate_sources.py`, remove `Any` from imports and add:

```python
from ..app.runtime_contracts import HybridCandidateRuntimePort
```

Change runtime fields and factory signatures:

```python
    runtime: HybridCandidateRuntimePort
```

```python
        runtime: HybridCandidateRuntimePort,
```

The affected classes are `DualLevelCandidateSource`, `VectorCandidateSource`, `Bm25CandidateSource`, `HybridCandidateSourceFactory`, and `DefaultHybridCandidateSourceFactory`.

- [ ] **Step 2: Type hybrid assembly inputs**

In `rag_modules/retrieval/hybrid_components.py`, import:

```python
from ..app.runtime_contracts import GraphDataModulePort, Neo4jManagerPort, VectorIndexModulePort
from ..configuration.models import GraphRAGConfig
```

Replace `config: Any`, `milvus_module: Any`, `data_module: Any`, and `neo4j_manager: Any` in the factory protocol and default implementation with:

```python
        config: GraphRAGConfig,
        milvus_module: VectorIndexModulePort,
        data_module: GraphDataModulePort,
        llm_client: object,
        neo4j_manager: Neo4jManagerPort,
```

In `rag_modules/retrieval/hybrid_runtime.py`, add constructor annotations:

```python
        config: GraphRAGConfig,
        milvus_module: VectorIndexModulePort,
        neo4j_manager: Neo4jManagerPort,
        graph_indexing: GraphIndexingModule,
        bm25_retriever: BM25Retriever,
        parent_enricher: ParentDocumentEnricher,
```

Add property return annotations:

```python
    def driver(self) -> object | None:
```

```python
    def vector_retriever(self) -> VectorRetriever | None:
```

```python
    def dual_level_service(self) -> DualLevelRetriever | None:
```

In `rag_modules/retrieval/hybrid_runtime_state.py`, replace:

```python
    driver: Any = None
```

with:

```python
    driver: object | None = None
```

- [ ] **Step 3: Type retrieval adapter factory inputs**

In `rag_modules/retrieval/runtime_adapter_factory.py`, import:

```python
from ..app.runtime_contracts import VectorIndexModulePort
from .adapters import GraphKVRetriever, VectorRetriever
from .keyword_service import QueryKeywordExtractor
```

Replace signatures with:

```python
    def create_vector_retriever(
        self,
        *,
        milvus_module: VectorIndexModulePort,
        driver: object | None,
        database: str,
    ) -> VectorRetriever: ...
```

```python
    def create_dual_level_retriever(
        self,
        *,
        graph_indexing: object,
        graph_kv_retriever: GraphKVRetriever,
        keyword_extractor: QueryKeywordExtractor,
        driver: object | None,
        database: str,
    ) -> DualLevelRetriever: ...
```

Use the same annotations on `DefaultHybridRuntimeAdapterFactory`.

- [ ] **Step 4: Type generation analysis inputs**

In `rag_modules/generation/decision.py`, replace `Any` with:

```python
from ..runtime import AnalysisInput
```

Use:

```python
    analysis: AnalysisInput = None,
```

In `rag_modules/generation/context_factory.py`, import and use:

```python
from ..runtime import AnalysisInput, ensure_optional_query_analysis
```

Change both builder signatures to:

```python
        analysis: AnalysisInput = None,
```

When creating `AnswerContext`, pass normalized analysis:

```python
            analysis=ensure_optional_query_analysis(analysis),
```

In `rag_modules/generation/planner.py`, import:

```python
from ..runtime import AnalysisInput, AnswerContext, analysis_strategy_name
```

Use:

```python
        analysis: AnalysisInput = None,
```

for `_build_answer_plan_for_package()` and `_can_use_rule_plan()`.

In `rag_modules/generation/execution/engine.py`, import:

```python
from ...runtime import AnalysisInput, AnswerContext, GenerationSnapshot, RetrievalOutcome
```

Use `analysis: AnalysisInput = None` in `generate()`, `generate_with_trace()`, and `_resolve_answer_context()`. In `_resolve_answer_context()`, normalize before constructing fallback context:

```python
        context = answer_context or AnswerContext(
            question=question,
            retrieval=RetrievalOutcome(query=question),
            analysis=ensure_optional_query_analysis(analysis),
        )
```

In `rag_modules/generation/execution/streaming.py`, import `Callable` and `Generator`:

```python
from collections.abc import Callable, Generator
```

Use:

```python
        analysis: AnalysisInput = None,
```

for `stream()` and `stream_with_trace()`, annotate `stream()`:

```python
    ) -> Generator[str, None, GenerationSnapshot]:
```

and annotate callback:

```python
        chunk_callback: Callable[[str], None] | None = None,
```

- [ ] **Step 5: Run focused retrieval and generation tests**

Run:

```powershell
python -m pytest tests/test_runtime_type_contracts.py tests/test_retrieval_candidate_generator.py tests/test_hybrid_search_service.py tests/test_generation_executor.py tests/test_generation_integration_facade.py -q
```

Expected: PASS.

### Task 4: Mypy Ratchet And Final Verification

**Files:**
- Modify: `pyproject.toml`
- All files changed in Tasks 1-3

- [ ] **Step 1: Add focused mypy inputs and overrides**

In `pyproject.toml`, update the mypy `files` list:

```toml
files = ["rag_modules", "main.py", "main_build_service.py", "config.py", "tests/typecheck"]
```

Add this override block below `[tool.mypy]`:

```toml
[[tool.mypy.overrides]]
module = [
  "rag_modules.app.runtime_contracts",
  "rag_modules.app.runtime_state",
  "rag_modules.app.runtime_views",
  "rag_modules.app.runtime_view_builder",
  "rag_modules.app.provider_components.contracts",
  "rag_modules.app.provider_components.infrastructure",
  "rag_modules.app.provider_components.retrieval",
  "rag_modules.app.provider_components.services",
  "rag_modules.retrieval.candidate_sources",
  "rag_modules.retrieval.hybrid_components",
  "rag_modules.retrieval.hybrid_runtime",
  "rag_modules.retrieval.hybrid_runtime_state",
  "rag_modules.retrieval.runtime_adapter_factory",
  "rag_modules.generation.decision",
  "rag_modules.generation.context_factory",
  "rag_modules.generation.planner",
  "rag_modules.generation.execution.engine",
  "rag_modules.generation.execution.streaming",
  "rag_modules.runtime.analysis_models",
  "tests.typecheck.type_contracts",
]
check_untyped_defs = true
disallow_untyped_defs = true
warn_return_any = true
warn_unused_ignores = true
no_implicit_optional = true
```

- [ ] **Step 2: Run the focused mypy gate**

Run:

```powershell
python -m mypy --config-file pyproject.toml
```

Expected: PASS when mypy is installed. If the command fails with `No module named mypy`, do not install dependencies without approval; record the blocker and continue with pytest and ruff-format checks.

- [ ] **Step 3: Run behavior regression tests**

Run:

```powershell
python -m pytest tests/test_runtime_type_contracts.py tests/test_application_assembly.py tests/test_app_system_runtime.py tests/test_generation_executor.py tests/test_generation_integration_facade.py tests/test_retrieval_candidate_generator.py tests/test_hybrid_search_service.py tests/test_hybrid_retrieval_runtime.py -q
```

Expected: PASS.

- [ ] **Step 4: Run formatting/lint check for touched files**

Run:

```powershell
python -m ruff check rag_modules/app/runtime_contracts.py rag_modules/app/runtime_state.py rag_modules/app/runtime_views.py rag_modules/app/runtime_view_builder.py rag_modules/app/provider_components/contracts.py rag_modules/app/provider_components/infrastructure.py rag_modules/app/provider_components/retrieval.py rag_modules/app/provider_components/services.py rag_modules/retrieval/candidate_sources.py rag_modules/retrieval/hybrid_components.py rag_modules/retrieval/hybrid_runtime.py rag_modules/retrieval/hybrid_runtime_state.py rag_modules/retrieval/runtime_adapter_factory.py rag_modules/generation/decision.py rag_modules/generation/context_factory.py rag_modules/generation/planner.py rag_modules/generation/execution/engine.py rag_modules/generation/execution/streaming.py rag_modules/runtime/analysis_models.py rag_modules/runtime/__init__.py tests/test_runtime_type_contracts.py tests/typecheck/type_contracts.py
```

Expected: PASS. If ruff is not installed, record `No module named ruff`.

- [ ] **Step 5: Check git status and preserve unrelated changes**

Run:

```powershell
git -c safe.directory=E:/all-in-rag-intelligent-customer status --short
```

Expected: the type-contract files and plan are modified or added. Pre-existing unrelated changes such as public-surface deletions or docs remain present and must not be reverted.

## Self-Review

- Spec coverage: Tasks 1-2 cover runtime state, runtime views, and provider contracts. Task 3 covers retrieval/generation ports and analysis normalization. Task 4 covers the mypy ratchet and verification.
- Placeholder scan: The plan contains no open placeholders. Protocol method bodies use Python ellipsis as valid stub syntax.
- Type consistency: The ports introduced in Task 1 are reused by runtime state, grouped views, provider contracts, and retrieval candidate sources in later tasks.
