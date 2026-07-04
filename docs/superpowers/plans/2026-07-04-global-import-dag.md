# Global Layered Import DAG Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the current cyclic `rag_modules` dependency graph with a fully classified, allow-listed DAG, without compatibility facades or provider fallbacks.

**Architecture:** Introduce a pure shared kernel, make configuration assembly the only source of resolved policy defaults, replace the aggregate runtime-contract modules with narrow consumer-owned ports, and construct concrete DashScope/Milvus adapters only in app composition. Finish with an AST import-policy test that rejects unclassified modules, forbidden edges, and cycles across every production module.

**Tech Stack:** Python 3.11, dataclasses, Pydantic 2, FastAPI, pytest, AST, Ruff, mypy

---

## File and ownership map

New canonical files:

- `rag_modules/kernel/json_types.py`: JSON aliases/coercion.
- `rag_modules/kernel/documents.py`: `TextDocument`.
- `rag_modules/kernel/artifacts.py`: artifact manifest/result/signature/statistics DTOs.
- `rag_modules/kernel/artifact_validation.py`: pure artifact/index mismatch checks.
- `rag_modules/kernel/routing.py`: search strategy and route statistics DTOs.
- `rag_modules/kernel/retrieval.py`: candidate-source degradation enum/normalizer.
- `rag_modules/kernel/semantic_schema.py`: semantic schema version and relation constants.
- `rag_modules/foundation/resilience.py`: provider-neutral circuit-breaker primitives.
- `rag_modules/infra/http.py`: pooled `requests.Session` construction.
- `rag_modules/contracts/query_constraints.py`: query-constraint DTO and pure parsing helpers.
- `rag_modules/query_understanding/constraint_extractor.py`: behavioral constraint extraction.
- `rag_modules/contracts/runtime/`: analysis, error, generation, graph, policy, retrieval, route,
  trace, and workflow DTOs formerly owned by the runtime service package.
- `rag_modules/query_understanding/ports.py`: planning LLM protocol.
- `rag_modules/generation/ports.py`: generation LLM/streaming protocols.
- `rag_modules/retrieval/ports.py`: retrieval collaborators.
- `rag_modules/graph/ports.py`: graph collaborators.
- `rag_modules/routing/ports.py`: routing collaborators.
- `rag_modules/build_pipeline/ports.py`: build collaborators.
- `rag_modules/runtime/ports.py`: runtime lifecycle/statistics collaborators.
- `rag_modules/app/ports.py`: application tracing/provider collaborators.
- `rag_modules/infra/milvus/ports.py`: `EmbeddingClientPort` consumed by Milvus.
- `rag_modules/infra/providers/dashscope/{http,embedding,rerank}.py`: concrete DashScope adapters.
- `tests/import_dag_policy.py`: immutable node classifier and exact allowed-edge mapping.
- `tests/test_import_dag.py`: AST enforcement and cycle diagnostics.

Deleted ownership paths:

- `rag_modules/runtime_contracts.py`
- `rag_modules/app/runtime_contracts.py`
- `rag_modules/dashscope_clients.py`
- `rag_modules/build_pipeline/document_artifacts/models.py`
- `rag_modules/routing/statistics.py`
- `rag_modules/runtime/json_types.py`
- `rag_modules/runtime/artifacts/manifest.py`
- `rag_modules/runtime/{analysis_models,error_models,generation_models,graph_models,policy_models,retrieval_models,route_models,trace_models,workflow_models,request_control}.py`
- `rag_modules/retrieval/hybrid_outcome.py`
- `rag_modules/domain/shared/query_constraints.py`
- `rag_modules/infra/resilience.py`
- root feature helpers after their definitions move to owning packages:
  `answer_evidence_builder.py`, `entity_linker.py`, `fusion.py`, `parent_doc_enricher.py`,
  `retrieval_cache.py`, and `retrieval_observability.py`

No deleted module receives a forwarding replacement.

### Task 1: Establish the pure kernel and canonical shared types

**Files:**
- Create: `rag_modules/kernel/__init__.py`
- Create: `rag_modules/kernel/json_types.py`
- Create: `rag_modules/kernel/documents.py`
- Create: `rag_modules/kernel/artifacts.py`
- Create: `rag_modules/kernel/artifact_validation.py`
- Create: `rag_modules/kernel/routing.py`
- Create: `rag_modules/kernel/retrieval.py`
- Create: `rag_modules/kernel/semantic_schema.py`
- Create: `rag_modules/contracts/query_constraints.py`
- Create: `rag_modules/contracts/graph.py`
- Create: `rag_modules/contracts/runtime/__init__.py`
- Create: `rag_modules/contracts/runtime/analysis.py`
- Create: `rag_modules/contracts/runtime/errors.py`
- Create: `rag_modules/contracts/runtime/generation.py`
- Create: `rag_modules/contracts/runtime/graph.py`
- Create: `rag_modules/contracts/runtime/policy.py`
- Create: `rag_modules/contracts/runtime/retrieval.py`
- Create: `rag_modules/contracts/runtime/routing.py`
- Create: `rag_modules/contracts/runtime/tracing.py`
- Create: `rag_modules/contracts/runtime/workflows.py`
- Create: `rag_modules/query_understanding/constraint_extractor.py`
- Modify: all `rag_modules/**/*.py` imports of `runtime.json_types`, `runtime.artifacts`, `text_document`, `build_pipeline.document_artifacts.models`, and `routing.statistics`
- Modify: matching tests under `tests/`
- Delete: `rag_modules/text_document.py`
- Delete: `rag_modules/build_pipeline/document_artifacts/models.py`
- Delete: `rag_modules/routing/statistics.py`
- Delete: `rag_modules/runtime/json_types.py`
- Delete: `rag_modules/runtime/artifacts/manifest.py`
- Delete: `rag_modules/runtime/analysis_models.py`
- Delete: `rag_modules/runtime/error_models.py`
- Delete: `rag_modules/runtime/generation_models.py`
- Delete: `rag_modules/runtime/graph_models.py`
- Delete: `rag_modules/runtime/policy_models.py`
- Delete: `rag_modules/runtime/retrieval_models.py`
- Delete: `rag_modules/runtime/route_models.py`
- Delete: `rag_modules/runtime/trace_models.py`
- Delete: `rag_modules/runtime/workflow_models.py`
- Delete: `rag_modules/runtime/request_control.py`
- Delete: `rag_modules/runtime/artifact_validation.py`
- Delete: `rag_modules/retrieval/hybrid_outcome.py`
- Delete: `rag_modules/domain/shared/query_constraints.py`
- Test: `tests/test_kernel_contracts.py`

- [ ] **Step 1: Write the failing kernel ownership tests**

Create `tests/test_kernel_contracts.py`:

```python
from __future__ import annotations

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
KERNEL = ROOT / "rag_modules" / "kernel"


def test_kernel_owns_shared_dtos() -> None:
    from rag_modules.kernel.artifacts import (
        ArtifactManifest,
        DocumentArtifactResult,
        DocumentArtifactSignatures,
        DocumentArtifactStats,
    )
    from rag_modules.kernel.documents import TextDocument
    from rag_modules.kernel.retrieval import CandidateSourceDegradationStrategy
    from rag_modules.kernel.routing import RouteStatistics, SearchStrategy
    from rag_modules.contracts.graph import GraphQuery
    from rag_modules.contracts.runtime import (
        GenerationSnapshot,
        GraphRetrievalSnapshot,
        HybridRetrievalOutcome,
        QueryAnalysis,
        RouteResolution,
        RuntimeErrorDetail,
    )

    assert ArtifactManifest.missing().is_missing
    assert DocumentArtifactResult.__module__ == "rag_modules.kernel.artifacts"
    assert DocumentArtifactSignatures.__module__ == "rag_modules.kernel.artifacts"
    assert DocumentArtifactStats.__module__ == "rag_modules.kernel.artifacts"
    assert TextDocument.__module__ == "rag_modules.kernel.documents"
    assert CandidateSourceDegradationStrategy.CONTINUE.value == "continue"
    assert RouteStatistics().total_queries == 0
    assert SearchStrategy.COMBINED.value == "combined"
    assert GraphQuery.__module__ == "rag_modules.contracts.graph"
    assert GenerationSnapshot.__module__.startswith("rag_modules.contracts.runtime")
    assert GraphRetrievalSnapshot.__module__.startswith("rag_modules.contracts.runtime")
    assert HybridRetrievalOutcome.__module__.startswith("rag_modules.contracts.runtime")
    assert QueryAnalysis.__module__.startswith("rag_modules.contracts.runtime")
    assert RouteResolution.__module__.startswith("rag_modules.contracts.runtime")
    assert RuntimeErrorDetail.__module__.startswith("rag_modules.contracts.runtime")


@pytest.mark.parametrize("path", sorted(KERNEL.glob("*.py")))
def test_kernel_does_not_import_feature_packages(path: Path) -> None:
    tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
    forbidden = {
        "app",
        "build_pipeline",
        "configuration",
        "generation",
        "graph",
        "infra",
        "interfaces",
        "query_policy",
        "query_understanding",
        "retrieval",
        "routing",
        "runtime",
    }
    violations: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            parts = node.module.split(".")
            if "rag_modules" in parts:
                target = parts[parts.index("rag_modules") + 1]
                if target in forbidden:
                    violations.append(f"{path.name}:{node.lineno}:{node.module}")
    assert not violations, "\n".join(violations)
```

- [ ] **Step 2: Run the kernel test and verify RED**

Run:

```powershell
python -m pytest tests/test_kernel_contracts.py -q
```

Expected: FAIL because `rag_modules.kernel` does not exist.

- [ ] **Step 3: Move shared definitions into kernel**

Use `apply_patch` to create `kernel/retrieval.py` with the canonical enum and normalizer:

```python
from __future__ import annotations

from enum import Enum


class CandidateSourceDegradationStrategy(str, Enum):
    CONTINUE = "continue"
    FAIL_FAST = "fail_fast"


def candidate_source_degradation_strategy(
    value: CandidateSourceDegradationStrategy | str,
) -> CandidateSourceDegradationStrategy:
    if isinstance(value, CandidateSourceDegradationStrategy):
        return value
    normalized = str(value).strip().lower()
    try:
        return CandidateSourceDegradationStrategy(normalized)
    except ValueError:
        supported = ", ".join(item.value for item in CandidateSourceDegradationStrategy)
        raise ValueError(f"candidate source degradation strategy must be one of: {supported}") from None


__all__ = ["CandidateSourceDegradationStrategy", "candidate_source_degradation_strategy"]
```

Move the existing implementations without behavioral edits:

- `runtime/json_types.py` -> `kernel/json_types.py`
- `text_document.py` -> `kernel/documents.py`
- artifact stage/manifest definitions from `runtime/artifacts/manifest.py` and the three document
  artifact dataclasses from `build_pipeline/document_artifacts/models.py` ->
  `kernel/artifacts.py`
- `SearchStrategy` from `runtime/policy_models.py` and the route counters from
  `routing/statistics.py` -> `kernel/routing.py`; rename the data object to `RouteStatistics` and
  keep `record()`, `to_dict()`, and `summary()`.
- semantic schema constants from `domain/shared/semantic_schema.py` ->
  `kernel/semantic_schema.py`; domain semantic enrichment imports the constants from kernel.
- `QueryConstraints`, `loads_json_object()`, and `parse_minutes()` from
  `domain/shared/query_constraints.py` -> `contracts/query_constraints.py`.
- `QueryConstraintExtractor` from `domain/shared/query_constraints.py` ->
  `query_understanding/constraint_extractor.py`; replace its method-local feature import with a
  normal import of `infer_query_semantic_profile` and inject resolved semantic settings.
- `GraphQuery` from `graph/retrieval_types.py` -> `contracts/graph.py`.
- runtime DTO modules -> the same responsibility-named files under `contracts/runtime/`.
- candidate/graph/generation/routing error codes and detail factories from
  `runtime/error_models.py` -> `contracts/runtime/errors.py`; API mappers import those constants
  from contracts rather than retrieval implementations.
- `HybridRetrievalOutcome` from `retrieval/hybrid_outcome.py` ->
  `contracts/runtime/retrieval.py` beside `RetrievalOutcome`.
- pure functions from `runtime/artifact_validation.py` -> `kernel/artifact_validation.py`.

`kernel/__init__.py` exports only canonical types:

```python
from .artifacts import (
    ArtifactManifest,
    ArtifactStage,
    DocumentArtifactResult,
    DocumentArtifactSignatures,
    DocumentArtifactStats,
)
from .documents import TextDocument
from .retrieval import CandidateSourceDegradationStrategy
from .routing import RouteStatistics, SearchStrategy

__all__ = [
    "ArtifactManifest",
    "ArtifactStage",
    "CandidateSourceDegradationStrategy",
    "DocumentArtifactResult",
    "DocumentArtifactSignatures",
    "DocumentArtifactStats",
    "RouteStatistics",
    "SearchStrategy",
    "TextDocument",
]
```

Replace imports repository-wide with these exact canonical targets:

```text
rag_modules.runtime.json_types                 -> rag_modules.kernel.json_types
rag_modules.runtime.artifacts.ArtifactManifest -> rag_modules.kernel.artifacts.ArtifactManifest
rag_modules.text_document.TextDocument         -> rag_modules.kernel.documents.TextDocument
rag_modules.build_pipeline.document_artifacts.models.* -> rag_modules.kernel.artifacts.*
rag_modules.routing.statistics.RouteStatisticsTracker  -> rag_modules.kernel.routing.RouteStatistics
rag_modules.runtime.SearchStrategy             -> rag_modules.kernel.routing.SearchStrategy
rag_modules.runtime.{analysis,error,generation,graph,policy,retrieval,route,trace,workflow} DTOs
                                                -> rag_modules.contracts.runtime
rag_modules.graph.retrieval_types.GraphQuery    -> rag_modules.contracts.graph.GraphQuery
rag_modules.retrieval.hybrid_outcome.HybridRetrievalOutcome
                                                -> rag_modules.contracts.runtime.HybridRetrievalOutcome
rag_modules.domain.shared.query_constraints.QueryConstraints
                                                -> rag_modules.contracts.query_constraints.QueryConstraints
```

Delete the old definition files/exports; update `runtime/artifacts/__init__.py`,
`build_pipeline/document_artifacts/__init__.py`, `build_pipeline/__init__.py`, `routing/__init__.py`,
`runtime/__init__.py`, `contracts/__init__.py`, and `domain/shared/__init__.py` so the first two expose
only their canonical owned surfaces and domain no longer exports query-constraint types. Remove
the enum/normalizer from `retrieval/candidate_generator.py`; it imports the kernel enum but does
not re-export it.

- [ ] **Step 4: Run kernel and touched artifact/routing tests**

Run:

```powershell
python -m pytest tests/test_kernel_contracts.py tests/test_document_artifact_cache.py tests/test_build_pipeline_manifest_lifecycle.py tests/test_route_search_orchestrator.py tests/test_milvus_blue_green.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit the kernel migration**

```powershell
git add rag_modules/kernel rag_modules/runtime rag_modules/build_pipeline rag_modules/routing rag_modules/text_document.py tests
git commit -m "refactor: establish shared kernel types"
```

### Task 2: Make configuration assembly the only default source

**Files:**
- Modify: `rag_modules/contracts/query_settings.py`
- Modify: `rag_modules/contracts/query.py`
- Modify: `rag_modules/configuration/assembly.py`
- Modify: `rag_modules/configuration/loader.py`
- Modify: `rag_modules/configuration/models.py`
- Modify: `rag_modules/configuration/testing.py`
- Modify: `rag_modules/configuration/model_sections/retrieval.py`
- Modify: `rag_modules/query_policy/models.py`
- Modify: `rag_modules/query_policy/parsers/runtime_defaults.py`
- Modify: `rag_modules/retrieval/runtime_profile/shared.py`
- Modify: `rag_modules/retrieval/runtime_profile/factory.py`
- Modify: production no-argument constructions found by `rg "Query(Planner|Semantic)RuntimeSettings\(\)" rag_modules`
- Test: `tests/test_query_policy_injection.py`
- Test: `tests/test_configuration_defaults.py`
- Test: `tests/test_query_semantics.py`

- [ ] **Step 1: Add failing tests for policy-overlay injection and pure contracts**

Append to `tests/test_query_policy_injection.py`:

```python
def test_contract_settings_do_not_import_query_policy() -> None:
    import ast
    from pathlib import Path

    path = Path("rag_modules/contracts/query_settings.py")
    tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
    imports = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    }
    assert not any("query_policy" in module for module in imports)


def test_configuration_models_do_not_import_feature_implementations() -> None:
    import ast
    from pathlib import Path

    forbidden = ("rag_modules.query_understanding", "rag_modules.retrieval")
    violations: list[str] = []
    for path in Path("rag_modules/configuration").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                if node.module.startswith(forbidden):
                    violations.append(f"{path}:{node.lineno}:{node.module}")
    assert not violations, "\n".join(violations)


def test_selected_policy_defaults_are_applied_before_explicit_overrides() -> None:
    from rag_modules.configuration.testing import build_test_config

    config = build_test_config(
        {
            "query_understanding": {"planner": {"cache_size": 17}},
            "retrieval": {"candidate_source_degradation_strategy": "fail_fast"},
        }
    )
    assert config.query_understanding.planner.cache_size == 17
    assert config.query_understanding.planner.timeout_seconds == 20
    assert config.retrieval.candidate_source_degradation_strategy == "fail_fast"
```

Add to `tests/test_configuration_defaults.py`:

```python
def test_runtime_settings_are_built_from_resolved_configuration() -> None:
    from rag_modules.configuration.testing import (
        build_test_config,
        planner_runtime_settings,
        semantic_runtime_settings,
    )

    config = build_test_config()
    planner = planner_runtime_settings(config)
    semantics = semantic_runtime_settings(config)
    assert planner.model_name == config.models.llm_model
    assert planner.cache_size == config.query_understanding.planner.cache_size
    assert semantics.reasoning_complexity_threshold == (
        config.query_understanding.semantics.scoring.reasoning_complexity_threshold
    )
```

- [ ] **Step 2: Run focused tests and verify RED**

Run:

```powershell
python -m pytest tests/test_query_policy_injection.py tests/test_configuration_defaults.py -q
```

Expected: FAIL because contracts import query-policy models and the runtime-settings test helpers
do not exist.

- [ ] **Step 3: Add the policy overlay to configuration assembly**

In `configuration/assembly.py`, add a pure conversion function. Every key maps to an existing
configuration field; do not return policy dataclasses:

```python
def query_policy_default_overlay(bundle: QueryPolicyBundle) -> dict[str, object]:
    runtime = bundle.runtime_defaults
    planner = runtime.planner
    semantics = runtime.semantics
    candidate_sources = runtime.candidate_sources
    return {
        "query_understanding": {
            "planner": {
                "cache_size": planner.cache_size,
                "fast_rule_planning": planner.fast_rule_planning,
                "llm_temperature": planner.llm_temperature,
                "llm_max_tokens": planner.llm_max_tokens,
            },
            "semantics": semantics.to_config_dict(),
        },
        "models": {
            "llm_model": planner.model_name,
            "llm_timeout_seconds": planner.timeout_seconds,
        },
        "retrieval": {
            "candidate_source_failure_threshold": candidate_sources.failure_threshold,
            "candidate_source_recovery_seconds": candidate_sources.recovery_timeout_seconds,
            "candidate_source_degradation_strategy": candidate_sources.degradation_strategy,
        },
        "graph": {
            "entity_linker_query_type_label_priorities": {
                key: list(values)
                for key, values in bundle.relations.entity_linker_query_type_priorities.items()
            },
            "entity_linker_relation_label_priorities": {
                key: list(values)
                for key, values in bundle.relations.entity_linker_relation_priorities.items()
            },
        },
    }
```

Add `to_config_dict()` to `QuerySemanticRuntimeDefaultsPolicy`; it returns nested `scoring`,
`extraction`, `routing`, `traversal`, and `adaptive_traversal` dictionaries whose keys exactly match
the fields already defined in `configuration/model_sections/query_understanding.py`.

In `load_config()`, enforce this precedence:

```python
domain_payload = _default_domain_payload()
selector = resolve_query_policy_selector(domain_payload, resolved_profile.overrides, env_source)
policy_bundle = resolve_query_policy_bundle_from_selector(selector)
apply_overrides(domain_payload, query_policy_default_overlay(policy_bundle))
apply_overrides(domain_payload, resolved_profile.overrides)
apply_overrides(domain_payload, env_overrides)
apply_overrides(domain_payload, overrides or {})
```

Keep validation after each external source merge, as in the current loader.

- [ ] **Step 4: Remove policy defaults from contracts and runtime profiles**

Delete these imports and module globals from `contracts/query_settings.py`:

```python
from ..query_policy.models import PlannerRuntimeDefaultsPolicy, QuerySemanticRuntimeDefaultsPolicy

_PLANNER_DEFAULTS = PlannerRuntimeDefaultsPolicy()
_SEMANTIC_DEFAULTS = QuerySemanticRuntimeDefaultsPolicy()
```

Change `QueryPlannerRuntimeSettings.from_config()` and
`QuerySemanticRuntimeSettings.from_config()` so every value comes from `GraphRAGConfig`; remove
fallback reads of `_PLANNER_DEFAULTS` and `_SEMANTIC_DEFAULTS`. Make feature constructors require
resolved settings instead of calling `QuerySemanticRuntimeSettings()`.

Add deterministic helpers to `configuration/testing.py`:

```python
def planner_runtime_settings(config: GraphRAGConfig) -> QueryPlannerRuntimeSettings:
    return QueryPlannerRuntimeSettings.from_config(config)


def semantic_runtime_settings(config: GraphRAGConfig) -> QuerySemanticRuntimeSettings:
    return QuerySemanticRuntimeSettings.from_config(config)
```

Replace test no-argument settings with:

```python
config = build_test_config()
settings = semantic_runtime_settings(config)
```

In production, pass settings from `RetrievalRuntimeProfileFactory.build(config)` into query
planning, scoring, graph resolution, keyword retrieval, and `QueryPlan.from_dict()`; remove local
fallback construction from those functions.

Change `RetrievalSettings` to import and validate the kernel enum:

```python
from ...kernel.retrieval import (
    CandidateSourceDegradationStrategy,
    candidate_source_degradation_strategy,
)

strategy = candidate_source_degradation_strategy(
    self.candidate_source_degradation_strategy
)
```

Delete policy model instantiation from `retrieval/runtime_profile/shared.py`. Its settings classes
receive concrete values only through `from_config()`.

In `configuration/model_sections/graph.py`, replace query-understanding registry factories with
`Field(default_factory=dict)`. The policy overlay above supplies the real defaults before Pydantic
validation, eliminating the `configuration -> query_understanding` edge.

- [ ] **Step 5: Run configuration, policy, and semantic suites**

Run:

```powershell
python -m pytest tests/test_configuration_defaults.py tests/test_configuration_profiles.py tests/test_configuration_section_loaders.py tests/test_query_policy.py tests/test_query_policy_injection.py tests/test_query_semantics.py tests/test_query_understanding_config.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit default injection**

```powershell
git add rag_modules/contracts rag_modules/configuration rag_modules/query_policy rag_modules/query_understanding rag_modules/retrieval rag_modules/graph tests
git commit -m "refactor: inject policy defaults through configuration"
```

### Task 3: Replace aggregate runtime contracts with consumer-owned ports

**Files:**
- Create: `rag_modules/query_understanding/ports.py`
- Create: `rag_modules/generation/ports.py`
- Create: `rag_modules/retrieval/ports.py`
- Create: `rag_modules/graph/ports.py`
- Create: `rag_modules/routing/ports.py`
- Create: `rag_modules/build_pipeline/ports.py`
- Create: `rag_modules/runtime/ports.py`
- Create: `rag_modules/app/ports.py`
- Create: `rag_modules/infra/milvus/ports.py`
- Modify: every importer listed by `rg -l "runtime_contracts" rag_modules tests`
- Delete: `rag_modules/runtime_contracts.py`
- Delete: `rag_modules/app/runtime_contracts.py`
- Test: `tests/test_consumer_owned_ports.py`
- Test: `tests/test_runtime_type_contracts.py`
- Test: `tests/typecheck/type_contracts.py`

- [ ] **Step 1: Add failing port ownership tests**

Create `tests/test_consumer_owned_ports.py`:

```python
from __future__ import annotations

from pathlib import Path


def test_aggregate_runtime_contract_modules_are_deleted() -> None:
    assert not Path("rag_modules/runtime_contracts.py").exists()
    assert not Path("rag_modules/app/runtime_contracts.py").exists()


def test_each_consumer_owns_its_ports() -> None:
    from rag_modules.app.ports import QueryTracerPort
    from rag_modules.build_pipeline.ports import GraphDataModulePort, VectorIndexModulePort
    from rag_modules.generation.ports import GenerationLLMClientPort
    from rag_modules.graph.ports import GraphDriverPort
    from rag_modules.infra.milvus.ports import EmbeddingClientPort
    from rag_modules.query_understanding.ports import PlanningLLMClientPort
    from rag_modules.retrieval.ports import RerankClientPort
    from rag_modules.routing.ports import GraphRetrievalPort, HybridRetrievalPort

    assert QueryTracerPort.__module__ == "rag_modules.app.ports"
    assert GraphDataModulePort.__module__ == "rag_modules.build_pipeline.ports"
    assert VectorIndexModulePort.__module__ == "rag_modules.build_pipeline.ports"
    assert GenerationLLMClientPort.__module__ == "rag_modules.generation.ports"
    assert GraphDriverPort.__module__ == "rag_modules.graph.ports"
    assert EmbeddingClientPort.__module__ == "rag_modules.infra.milvus.ports"
    assert PlanningLLMClientPort.__module__ == "rag_modules.query_understanding.ports"
    assert RerankClientPort.__module__ == "rag_modules.retrieval.ports"
    assert GraphRetrievalPort.__module__ == "rag_modules.routing.ports"
    assert HybridRetrievalPort.__module__ == "rag_modules.routing.ports"
```

- [ ] **Step 2: Run the port test and verify RED**

Run:

```powershell
python -m pytest tests/test_consumer_owned_ports.py -q
```

Expected: FAIL because the new port modules do not exist and aggregate modules remain.

- [ ] **Step 3: Create narrow structural protocols**

Move protocol signatures from `runtime_contracts.py` according to consumer use. Use distinct names
where requirements differ. For example, `infra/milvus/ports.py` is exactly:

```python
from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol


class EmbeddingClientPort(Protocol):
    def embed_query(self, text: str, *, timeout_seconds: float | None = None) -> list[float]: ...

    def embed_documents(
        self,
        texts: Sequence[str],
        *,
        timeout_seconds: float | None = None,
    ) -> list[list[float]]: ...


__all__ = ["EmbeddingClientPort"]
```

`routing/ports.py` owns only routing inputs:

```python
from __future__ import annotations

from typing import Protocol

from ..contracts import EvidenceDocument, QueryPlan, RetrievalRequest
from ..kernel.routing import RouteStatistics
from ..contracts.graph import GraphQuery
from ..contracts.runtime import GraphRetrievalSnapshot, HybridRetrievalOutcome


class HybridRetrievalPort(Protocol):
    def hybrid_evidence_search(self, request: RetrievalRequest) -> HybridRetrievalOutcome: ...

    def enrich_to_parent_evidence_documents(
        self,
        request: RetrievalRequest,
        docs: list[EvidenceDocument],
        top_n: int | None = None,
    ) -> list[EvidenceDocument]: ...


class GraphRetrievalPort(Protocol):
    def graph_rag_evidence_search_with_trace(
        self,
        request: RetrievalRequest,
    ) -> tuple[list[EvidenceDocument], GraphRetrievalSnapshot]: ...

    def graph_query_from_plan(self, plan: QueryPlan) -> GraphQuery: ...


class RouteStatisticsPort(Protocol):
    def get_route_statistics(self) -> RouteStatistics: ...


__all__ = ["GraphRetrievalPort", "HybridRetrievalPort", "RouteStatisticsPort"]
```

Do not import implementation packages merely to make protocol return types exact. Move genuinely
shared return DTOs to kernel/contracts first, or use a consumer-local DTO.

- [ ] **Step 4: Migrate imports and delete the aggregate modules**

Apply this ownership mapping to every current importer:

```text
query_understanding/* LLMClientPort -> query_understanding.ports.PlanningLLMClientPort
generation/* LLM/Streaming ports    -> generation.ports
retrieval/* candidate/driver/vector/rerank ports -> retrieval.ports
graph/* Neo4j/LLM ports             -> graph.ports
routing/* hybrid/graph ports        -> routing.ports
build_pipeline/* data/vector ports  -> build_pipeline.ports
runtime/* lifecycle/stats ports     -> runtime.ports
app/* provider/tracer ports         -> app.ports
infra/milvus/* embedding port       -> infra.milvus.ports
```

Update `tests/test_runtime_type_contracts.py` and `tests/typecheck/type_contracts.py` to import each
protocol from its consumer. Remove both aggregate modules only after `rg -n "runtime_contracts"
rag_modules tests` returns no matches.

- [ ] **Step 5: Run ports, type contracts, and mypy**

Run:

```powershell
python -m pytest tests/test_consumer_owned_ports.py tests/test_runtime_type_contracts.py tests/test_type_contract_ratchets.py -q
python -m mypy rag_modules tests/typecheck
```

Expected: PASS, and mypy reports `Success: no issues found`.

- [ ] **Step 6: Commit consumer-owned ports**

```powershell
git add rag_modules tests pyproject.toml
git commit -m "refactor: split runtime contracts by consumer"
```

### Task 4: Move DashScope providers and make Milvus injection mandatory

**Files:**
- Create: `rag_modules/infra/providers/__init__.py`
- Create: `rag_modules/infra/providers/dashscope/__init__.py`
- Create: `rag_modules/infra/providers/dashscope/http.py`
- Create: `rag_modules/infra/providers/dashscope/embedding.py`
- Create: `rag_modules/infra/providers/dashscope/rerank.py`
- Create: `rag_modules/foundation/__init__.py`
- Create: `rag_modules/foundation/resilience.py`
- Create: `rag_modules/infra/http.py`
- Modify: `rag_modules/infra/milvus/client.py`
- Modify: `rag_modules/infra/milvus/module.py`
- Modify: `rag_modules/app/providers/infrastructure.py`
- Modify: `rag_modules/app/providers/retrieval_runtime.py`
- Modify: `rag_modules/app/providers/contracts.py`
- Modify: `rag_modules/retrieval/post_processor.py`
- Delete: `rag_modules/dashscope_clients.py`
- Delete: `rag_modules/infra/resilience.py`
- Test: `tests/test_model_client_ports.py`
- Test: `tests/test_retrieval_service_factories.py`
- Test: `tests/test_application_assembly.py`

- [ ] **Step 1: Add failing provider-isolation tests**

Append to `tests/test_model_client_ports.py`:

```python
def test_dashscope_is_owned_by_infra_provider_package() -> None:
    from pathlib import Path

    from rag_modules.infra.providers.dashscope import (
        DashScopeEmbeddingClient,
        DashScopeRerankClient,
    )

    assert DashScopeEmbeddingClient.__module__.startswith(
        "rag_modules.infra.providers.dashscope"
    )
    assert DashScopeRerankClient.__module__.startswith(
        "rag_modules.infra.providers.dashscope"
    )
    assert not Path("rag_modules/dashscope_clients.py").exists()


def test_milvus_requires_an_embedding_port() -> None:
    import inspect

    from rag_modules.infra.milvus import MilvusIndexConstructionModule

    parameter = inspect.signature(MilvusIndexConstructionModule.__init__).parameters[
        "embedding_client"
    ]
    assert parameter.default is inspect.Parameter.empty
```

Add a source-boundary assertion:

```python
def test_milvus_does_not_import_dashscope() -> None:
    from pathlib import Path

    violations = []
    for path in Path("rag_modules/infra/milvus").glob("*.py"):
        text = path.read_text(encoding="utf-8-sig")
        if "dashscope" in text.lower():
            violations.append(str(path))
    assert not violations


def test_milvus_does_not_close_injected_embedding_provider() -> None:
    from rag_modules.infra.milvus import MilvusIndexConstructionModule

    class CloseTrackingEmbedding:
        def __init__(self) -> None:
            self.close_calls = 0

        def close(self) -> None:
            self.close_calls += 1

    embedding = CloseTrackingEmbedding()
    module = object.__new__(MilvusIndexConstructionModule)
    module.embedding_client = embedding
    module.embeddings = embedding
    module.client = None
    module.close()
    assert embedding.close_calls == 0
```

- [ ] **Step 2: Run provider tests and verify RED**

Run:

```powershell
python -m pytest tests/test_model_client_ports.py -q
```

Expected: FAIL because DashScope remains at the root and Milvus still has an optional embedding
client/fallback.

- [ ] **Step 3: Split the DashScope implementation**

Move common HTTP behavior to `dashscope/http.py`:

```python
from __future__ import annotations

from collections.abc import Mapping

import requests


class DashScopeHttpClient:
    def __init__(self, api_key: str, base_url: str, timeout: int, session: requests.Session) -> None:
        if not api_key:
            raise ValueError("Please set DASHSCOPE_API_KEY or OPENAI_API_KEY.")
        self.api_key = api_key
        self.base_url = base_url
        self.timeout = timeout
        self.session = session

    def post_json(
        self,
        payload: Mapping[str, object],
        *,
        timeout_seconds: float | None = None,
    ) -> dict[str, object]:
        response = self.session.post(
            self.base_url,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            json=dict(payload),
            timeout=self.timeout if timeout_seconds is None else timeout_seconds,
        )
        response.raise_for_status()
        return dict(response.json())

    def close(self) -> None:
        self.session.close()
```

Move embedding and rerank behavior unchanged into their respective modules, using
`DashScopeHttpClient` plus the existing circuit breaker. Export both concrete adapters only from
`infra/providers/dashscope/__init__.py`.

Split the old `infra/resilience.py`: move `CircuitBreaker`, `CircuitBreakerSnapshot`, and
`CircuitOpenError` unchanged to `foundation/resilience.py`; move
`build_pooled_requests_session()` to `infra/http.py`. Update generation and retrieval to import the
circuit breaker from foundation, and DashScope to import both layers. Delete `infra/resilience.py`.

- [ ] **Step 4: Remove Milvus fallback construction**

Make the parameter required and provider-neutral in `infra/milvus/module.py`:

```python
def __init__(
    self,
    *,
    embedding_client: EmbeddingClientPort,
    host: str = "localhost",
    port: int = 19530,
    collection_name: str = "cooking_knowledge",
    dimension: int = 512,
    vector_search_ef: int = 128,
    vector_search_max_k: int = 50,
    blue_green_enabled: bool = True,
    collection_alias_suffix: str = "__active",
) -> None:
    self.embedding_client = embedding_client
```

Delete embedding-provider credentials and HTTP/circuit-breaker arguments from Milvus. Replace
`_setup_embeddings()` with:

```python
def _setup_embeddings(self) -> None:
    self.embeddings = self.embedding_client
```

Milvus no longer closes the injected embedding client. App runtime shutdown owns and closes the
provider once.

- [ ] **Step 5: Construct and inject providers in app composition**

In `_DefaultInfrastructureProvider`, add:

```python
def provide_embedding_client(self, config: GraphRAGConfig) -> DashScopeEmbeddingClient:
    models = config.models
    return DashScopeEmbeddingClient(
        api_key=models.api_key,
        model_name=models.embedding_model,
        base_url=models.embedding_base_url,
        dimension=models.embedding_dimension,
        batch_size=models.embedding_batch_size,
        timeout=models.embedding_timeout_seconds,
        http_pool_connections=models.http_pool_connections,
        http_pool_maxsize=models.http_pool_maxsize,
        circuit_breaker_failure_threshold=models.circuit_breaker_failure_threshold,
        circuit_breaker_recovery_seconds=models.circuit_breaker_recovery_seconds,
    )
```

Store the result as `embedding_client` and pass it to
`MilvusIndexConstructionModule(embedding_client=embedding_client)`. Add a matching
`provide_rerank_client()` and inject it into retrieval post-processing through
`retrieval.ports.RerankClientPort`. Remove concrete provider construction from retrieval.

- [ ] **Step 6: Run provider and assembly tests**

Run:

```powershell
python -m pytest tests/test_model_client_ports.py tests/test_retrieval_service_factories.py tests/test_application_assembly.py tests/test_build_runtime_factory.py tests/test_serving_runtime_factory.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit provider isolation**

```powershell
git add rag_modules/infra rag_modules/app rag_modules/retrieval tests
git commit -m "refactor: isolate dashscope providers from milvus"
```

### Task 5: Invert routing, runtime, and build orchestration dependencies

**Files:**
- Modify: `rag_modules/routing/contracts.py`
- Modify: `rag_modules/routing/search_orchestrator.py`
- Modify: `rag_modules/routing/strategies/base.py`
- Modify: `rag_modules/routing/workflow_service.py`
- Modify: `rag_modules/runtime/artifact_ports.py`
- Modify: `rag_modules/runtime/stats_ports.py`
- Modify: `rag_modules/runtime/stats_adapters.py`
- Modify: `rag_modules/build_pipeline/contracts.py`
- Modify: `rag_modules/build_pipeline/knowledge_base_workflow.py`
- Modify: `rag_modules/build_pipeline/schema_sync.py`
- Modify: `rag_modules/build_pipeline/graph_preparation/models.py`
- Modify: `rag_modules/graph/rag_retrieval.py`
- Modify: `rag_modules/graph/retrieval_components.py`
- Modify: `rag_modules/graph/retrieval_executor.py`
- Modify: `rag_modules/graph/cache_stats.py`
- Modify: `rag_modules/infra/semantic_graph_writer.py`
- Modify: `rag_modules/app/providers/contracts.py`
- Modify: `rag_modules/app/providers/services.py`
- Modify: `rag_modules/app/providers/build_pipeline.py`
- Modify: `scripts/import_semantic_schema.py`
- Delete: `rag_modules/graph/data_preparation.py`
- Delete: `rag_modules/graph/schema.py`
- Test: `tests/test_route_search_orchestrator.py`
- Test: `tests/test_knowledge_base_workflow.py`
- Test: `tests/test_runtime_diagnostics_service.py`

- [ ] **Step 1: Add failing source-boundary tests**

Add to `tests/test_dependency_isolation.py`:

```python
def test_orchestrators_depend_on_ports_not_implementations() -> None:
    forbidden = {
        "rag_modules.routing": {"rag_modules.retrieval", "rag_modules.graph"},
        "rag_modules.runtime": {"rag_modules.build_pipeline", "rag_modules.routing"},
        "rag_modules.build_pipeline": {"rag_modules.infra", "rag_modules.graph"},
        "rag_modules.graph": {"rag_modules.build_pipeline", "rag_modules.infra", "rag_modules.retrieval"},
    }
    violations = scan_package_imports(forbidden)
    assert not violations, "\n".join(violations)
```

Implement `scan_package_imports()` in the test using the existing AST relative-import resolver
from `PublicSurfaceBoundaryTests`, returning `path:line:source -> target` strings.

- [ ] **Step 2: Run boundary tests and verify RED**

Run:

```powershell
python -m pytest tests/test_dependency_isolation.py -q
```

Expected: FAIL on current routing-to-retrieval/graph, runtime-to-build/routing, and
build-to-infrastructure imports.

- [ ] **Step 3: Route only through routing-owned ports**

Change routing constructors and fields to `HybridRetrievalPort`, `GraphRetrievalPort`, and a
query-understanding protocol declared in `routing/ports.py`. Return kernel/contracts DTOs from
these protocols. Remove implementation imports from routing modules.

Change `RoutingWorkflowProtocol.get_route_statistics()` to return `RouteStatistics`; diagnostics
adapters perform JSON conversion with `summary()`.

Graph may depend on query-understanding's pure inference API, but not retrieval runtime profiles,
build facades, or infrastructure factories. Replace `RetrievalRuntimeProfile` constructor
parameters in `graph/rag_retrieval.py` and `graph/retrieval_components.py` with the exact pieces
used by graph: `QuerySemanticRuntimeSettings`, `QueryPolicyBundle`, and graph configuration. App
composition passes `retrieval_profile.semantics` during assembly.

Make `GraphRetrievalExecutor` require an injected `GraphManagerPort`; delete the
`create_neo4j_driver()` fallback and `_owns_driver` branch. `GraphCacheStatsStore` receives an
injected manifest-store protocol from `graph/ports.py` instead of constructing/importing the
runtime store.

- [ ] **Step 4: Keep artifact and statistics DTOs below runtime/build**

Change `runtime/artifact_ports.py` to import `DocumentArtifactResult` and `ArtifactManifest` only
from `kernel.artifacts`. Move its protocol definitions into `runtime/ports.py`, then delete
`runtime/artifact_ports.py` after callers migrate.

Change `runtime/stats_ports.py` so it owns local structural inputs instead of importing routing or
build ports:

```python
class RouteStatsSource(Protocol):
    def get_route_statistics(self) -> RouteStatistics: ...


class GraphStatsSource(Protocol):
    def get_statistics(self) -> JsonObject: ...


class VectorStatsSource(Protocol):
    def get_collection_stats(self, collection_name: str | None = None) -> JsonObject: ...
```

Update adapters and app providers to accept these structural shapes. `build_pipeline/contracts.py`
imports artifact DTOs from kernel and its collaborator protocols from `build_pipeline/ports.py`.
Move the build-consumed `ArtifactManifestStorePort`, `RuntimeArtifactAccessPort`, and
`RuntimeStatsAccessPort` shapes into `build_pipeline/ports.py`. `KnowledgeBaseWorkflow` requires
all three collaborators; delete its `DefaultRuntimeArtifactAccess()` and
`DefaultRuntimeStatsAccess()` fallbacks. App providers inject the concrete runtime adapters.
`vector_reuse.py` imports `vector_artifact_mismatch_reason` from
`kernel.artifact_validation.py`.

Change `SemanticGraphSchemaSyncService` to receive a `SemanticGraphWriterPort` declared in
`build_pipeline/ports.py`:

```python
class SemanticGraphWriterPort(Protocol):
    def persist_from_documents(self, documents: list[TextDocument]) -> JsonObject: ...
```

App's build provider constructs `infra.semantic_graph_writer.SemanticGraphSchemaWriter` with the
already assembled Neo4j manager and injects it into the service. The build package no longer
imports `graph.SemanticGraphSchemaWriter` or infra.

Delete `graph/data_preparation.py` and `graph/schema.py`. Update
`scripts/import_semantic_schema.py` to import `GraphDataPreparationModule` from
`build_pipeline.graph_preparation`; remove `GraphNode.__module__`/`GraphRelation.__module__` path
spoofing and the root `rag_modules.GraphDataPreparationModule` export.

- [ ] **Step 5: Run orchestration suites**

Run:

```powershell
python -m pytest tests/test_dependency_isolation.py tests/test_route_search_orchestrator.py tests/test_route_execution_strategies.py tests/test_knowledge_base_workflow.py tests/test_runtime_diagnostics_service.py tests/test_build_pipeline_stats_presenter.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit orchestration inversion**

```powershell
git add rag_modules/routing rag_modules/runtime rag_modules/build_pipeline rag_modules/app tests
git commit -m "refactor: invert orchestration dependencies"
```

### Task 6: Move root feature helpers into their owners and remove remaining back edges

**Files:**
- Move: `rag_modules/answer_evidence_builder.py` -> `rag_modules/evidence_processing/answer_builder.py`
- Move: `rag_modules/entity_linker.py` -> `rag_modules/graph/entity_linker.py`
- Move: `rag_modules/fusion.py` -> `rag_modules/retrieval/fusion.py`
- Move: `rag_modules/parent_doc_enricher.py` -> `rag_modules/retrieval/parent_doc_enricher.py`
- Move: `rag_modules/retrieval_cache.py` -> `rag_modules/retrieval/cache.py`
- Move: `rag_modules/retrieval_observability.py` -> `rag_modules/observability/retrieval_snapshots.py`
- Modify: `rag_modules/__init__.py`
- Modify: `rag_modules/graph/__init__.py`
- Modify: `rag_modules/retrieval/__init__.py`
- Modify: `rag_modules/routing/__init__.py`
- Modify: all importing production modules/tests
- Test: `tests/test_dependency_isolation.py`
- Test: `tests/test_answer_evidence_builder.py`
- Test: `tests/test_retrieval_cache.py`
- Test: `tests/test_recipe_constraint_matcher.py`

- [ ] **Step 1: Add failing ownership tests**

Add to `tests/test_dependency_isolation.py`:

```python
def test_root_feature_helpers_are_retired() -> None:
    retired = {
        "answer_evidence_builder.py",
        "entity_linker.py",
        "fusion.py",
        "parent_doc_enricher.py",
        "retrieval_cache.py",
        "retrieval_observability.py",
    }
    root = ROOT / "rag_modules"
    assert not sorted(name for name in retired if (root / name).exists())


def test_root_package_is_not_a_lazy_feature_facade() -> None:
    import rag_modules

    assert getattr(rag_modules, "__all__", []) == []
    source = (ROOT / "rag_modules" / "__init__.py").read_text(encoding="utf-8-sig")
    assert "import_module" not in source
    assert "__getattr__" not in source


def test_domain_does_not_import_query_understanding() -> None:
    violations = scan_package_imports(
        {"rag_modules.domain": {"rag_modules.query_understanding"}}
    )
    assert not violations, "\n".join(violations)
```

- [ ] **Step 2: Run ownership tests and verify RED**

Run:

```powershell
python -m pytest tests/test_dependency_isolation.py -q
```

Expected: FAIL because the six root helpers exist and domain dynamically imports query
understanding.

- [ ] **Step 3: Move helpers and imports without wrappers**

Use `apply_patch` to create each destination with the existing implementation, update every import
to the destination, then delete the source. Do not export old module names from `rag_modules`.
Replace `rag_modules/__init__.py` with a package docstring and `__all__: list[str] = []`; delete its
lazy `_EXPORTS`, `__getattr__`, and `import_module` machinery. Callers import canonical owning
packages directly.

Keep canonical lazy package exports only for definitions still owned by that package. Remove
`GraphDataPreparationModule`, `GraphNode`, `GraphRelation`, `GraphQuery`, and
`SemanticGraphSchemaWriter` from `graph/__init__.py`; remove `HybridRetrievalOutcome` from
`retrieval/__init__.py`; remove `RouteStatisticsTracker` from `routing/__init__.py`. Do not replace
them with aliases to kernel/contracts.

- [ ] **Step 4: Remove feature-to-feature back edges**

Run the read-only inventory:

```powershell
python -m pytest tests/test_dependency_isolation.py -q
```

For the exact prohibited families asserted in the test, replace remaining concrete imports with
the already created consumer ports and kernel/contracts DTOs. The expected prohibited-edge count
after this step is zero; do not add exceptions.

- [ ] **Step 5: Run moved-helper behavior tests**

Run:

```powershell
python -m pytest tests/test_answer_evidence_builder.py tests/test_retrieval_cache.py tests/test_retrieval_candidate_generator.py tests/test_recipe_constraint_matcher.py tests/test_graph_retrieval_executor.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit root ownership convergence**

```powershell
git add rag_modules tests
git commit -m "refactor: move root helpers into feature owners"
```

### Task 7: Install the global import DAG and exact edge allow-list

**Files:**
- Create: `tests/import_dag_policy.py`
- Create: `tests/test_import_dag.py`
- Modify: none expected; a production-edge failure returns to the owning migration in Tasks 1-6
  instead of widening the allow-list
- Test: `tests/test_import_dag.py`

- [ ] **Step 1: Write the failing global DAG test**

Create `tests/import_dag_policy.py` with all production nodes and reviewed allowed dependencies:

```python
from __future__ import annotations

ALLOWED_DYNAMIC_IMPORT_FILES = frozenset(
    {
        "rag_modules/graph/__init__.py",
        "rag_modules/infra/__init__.py",
        "rag_modules/query_understanding/__init__.py",
        "rag_modules/retrieval/__init__.py",
        "rag_modules/routing/__init__.py",
    }
)

NODE_PREFIXES = {
    "package_root": ("rag_modules",),
    "foundation": ("rag_modules.foundation",),
    "kernel": ("rag_modules.kernel",),
    "contracts": ("rag_modules.contracts",),
    "domain": ("rag_modules.domain",),
    "query_policy": ("rag_modules.query_policy",),
    "configuration": ("rag_modules.configuration",),
    "evidence_processing": ("rag_modules.evidence_processing",),
    "query_understanding": ("rag_modules.query_understanding",),
    "graph_index": ("rag_modules.graph_index",),
    "retrieval": ("rag_modules.retrieval",),
    "graph": ("rag_modules.graph",),
    "generation": ("rag_modules.generation",),
    "routing": ("rag_modules.routing",),
    "build_pipeline": ("rag_modules.build_pipeline",),
    "runtime": ("rag_modules.runtime",),
    "infra": ("rag_modules.infra",),
    "observability": ("rag_modules.observability",),
    "app": ("rag_modules.app",),
    "interfaces": ("rag_modules.interfaces",),
    "evaluation": ("rag_modules.evaluation",),
    "langchain_adapter": ("rag_modules.langchain_document_adapter",),
    "safe_logging": ("rag_modules.safe_logging",),
    "telemetry": ("rag_modules.telemetry",),
    "trace_privacy": ("rag_modules.trace_privacy",),
    "public_surface": ("rag_modules.public_surface_manifest",),
}

ALLOWED_IMPORTS = {
    "package_root": frozenset(),
    "foundation": frozenset(),
    "kernel": frozenset(),
    "contracts": frozenset({"kernel"}),
    "domain": frozenset({"kernel", "contracts"}),
    "query_policy": frozenset({"kernel", "contracts"}),
    "configuration": frozenset({"kernel", "contracts", "query_policy"}),
    "evidence_processing": frozenset({"kernel", "contracts", "domain", "safe_logging"}),
    "query_understanding": frozenset(
        {"kernel", "contracts", "domain", "query_policy", "configuration", "safe_logging"}
    ),
    "graph_index": frozenset(
        {"kernel", "contracts", "domain", "query_policy", "query_understanding"}
    ),
    "retrieval": frozenset(
        {
            "kernel",
            "contracts",
            "domain",
            "query_policy",
            "configuration",
            "evidence_processing",
            "graph_index",
            "query_understanding",
            "foundation",
            "safe_logging",
        }
    ),
    "graph": frozenset(
        {
            "kernel",
            "contracts",
            "domain",
            "query_policy",
            "configuration",
            "evidence_processing",
            "graph_index",
            "query_understanding",
            "safe_logging",
        }
    ),
    "generation": frozenset(
        {
            "kernel",
            "contracts",
            "query_policy",
            "configuration",
            "evidence_processing",
            "foundation",
            "safe_logging",
        }
    ),
    "routing": frozenset(
        {"kernel", "contracts", "domain", "query_policy", "configuration", "safe_logging"}
    ),
    "build_pipeline": frozenset(
        {"kernel", "contracts", "domain", "configuration", "safe_logging"}
    ),
    "runtime": frozenset({"kernel", "contracts", "domain", "configuration", "safe_logging"}),
    "infra": frozenset(
        {"kernel", "contracts", "configuration", "foundation", "safe_logging"}
    ),
    "observability": frozenset(
        {"kernel", "contracts", "configuration", "safe_logging", "trace_privacy"}
    ),
    "app": frozenset(
        {
            "kernel",
            "contracts",
            "domain",
            "query_policy",
            "configuration",
            "query_understanding",
            "retrieval",
            "graph",
            "generation",
            "routing",
            "build_pipeline",
            "runtime",
            "infra",
            "observability",
            "safe_logging",
            "telemetry",
            "foundation",
        }
    ),
    "interfaces": frozenset(
        {
            "kernel",
            "contracts",
            "configuration",
            "runtime",
            "app",
            "safe_logging",
            "telemetry",
        }
    ),
    "evaluation": frozenset({"kernel", "contracts"}),
    "langchain_adapter": frozenset({"kernel"}),
    "safe_logging": frozenset(),
    "telemetry": frozenset(),
    "trace_privacy": frozenset({"kernel", "contracts"}),
    "public_surface": frozenset(),
}
```

Create `tests/test_import_dag.py` with:

```python
from __future__ import annotations

import ast
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from tests.import_dag_policy import (
    ALLOWED_DYNAMIC_IMPORT_FILES,
    ALLOWED_IMPORTS,
    NODE_PREFIXES,
)

ROOT = Path(__file__).resolve().parents[1]
PACKAGE_ROOT = ROOT / "rag_modules"


@dataclass(frozen=True)
class ImportEdge:
    source: str
    target: str
    path: Path
    line: int


def module_name(path: Path) -> str:
    relative = path.relative_to(ROOT).with_suffix("")
    parts = list(relative.parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def architectural_node(module: str) -> str | None:
    matches = [
        (len(prefix), node)
        for node, prefixes in NODE_PREFIXES.items()
        for prefix in prefixes
        if module == prefix or module.startswith(f"{prefix}.")
    ]
    if not matches:
        return None
    longest = max(length for length, _ in matches)
    owners = {node for length, node in matches if length == longest}
    if len(owners) != 1:
        return None
    return owners.pop()


def resolve_from_import(
    source: str,
    *,
    is_package: bool,
    level: int,
    module: str | None,
) -> str:
    if level == 0:
        return module or ""
    package = source.split(".") if is_package else source.split(".")[:-1]
    package = package[: len(package) - (level - 1)]
    suffix = (module or "").split(".") if module else []
    return ".".join([*package, *suffix])


def import_edges() -> tuple[list[str], list[str], list[ImportEdge]]:
    unclassified: list[str] = []
    dynamic_imports: list[str] = []
    edges: list[ImportEdge] = []
    for path in sorted(PACKAGE_ROOT.rglob("*.py")):
        source_module = module_name(path)
        source_node = architectural_node(source_module)
        if source_node is None:
            unclassified.append(source_module)
            continue
        tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
        relative_path = path.relative_to(ROOT).as_posix()
        if relative_path in ALLOWED_DYNAMIC_IMPORT_FILES:
            for node in ast.walk(tree):
                if not isinstance(node, ast.Dict):
                    continue
                for value in node.values:
                    if (
                        isinstance(value, ast.Constant)
                        and isinstance(value.value, str)
                        and value.value.startswith(".")
                    ):
                        level = len(value.value) - len(value.value.lstrip("."))
                        target_module = resolve_from_import(
                            source_module,
                            is_package=True,
                            level=level,
                            module=value.value.lstrip("."),
                        )
                        target_node = architectural_node(target_module)
                        if target_node is None:
                            unclassified.append(target_module)
                        elif target_node != source_node:
                            edges.append(
                                ImportEdge(source_node, target_node, path, value.lineno)
                            )
        for item in ast.walk(tree):
            targets: list[str] = []
            if isinstance(item, ast.Import):
                targets = [alias.name for alias in item.names]
            elif isinstance(item, ast.ImportFrom):
                targets = [
                    resolve_from_import(
                        source_module,
                        is_package=path.name == "__init__.py",
                        level=item.level,
                        module=item.module,
                    )
                ]
            elif (
                isinstance(item, ast.Call)
                and isinstance(item.func, ast.Attribute)
                and item.func.attr == "import_module"
            ):
                if (
                    item.args
                    and isinstance(item.args[0], ast.Constant)
                    and isinstance(item.args[0].value, str)
                ):
                    targets = [item.args[0].value]
                else:
                    if relative_path not in ALLOWED_DYNAMIC_IMPORT_FILES:
                        dynamic_imports.append(
                            f"{path.relative_to(ROOT)}:{item.lineno}: non-literal import_module"
                        )
            for target_module in targets:
                if not target_module.startswith("rag_modules"):
                    continue
                target_node = architectural_node(target_module)
                if target_node is None:
                    unclassified.append(target_module)
                elif target_node != source_node:
                    edges.append(ImportEdge(source_node, target_node, path, item.lineno))
    return sorted(set(unclassified)), sorted(set(dynamic_imports)), edges


def cyclic_components(edges: list[ImportEdge]) -> list[tuple[str, ...]]:
    adjacency: dict[str, set[str]] = defaultdict(set)
    for edge in edges:
        adjacency[edge.source].add(edge.target)
    index = 0
    stack: list[str] = []
    on_stack: set[str] = set()
    indices: dict[str, int] = {}
    lowlinks: dict[str, int] = {}
    components: list[tuple[str, ...]] = []

    def visit(node: str) -> None:
        nonlocal index
        indices[node] = lowlinks[node] = index
        index += 1
        stack.append(node)
        on_stack.add(node)
        for target in adjacency[node]:
            if target not in indices:
                visit(target)
                lowlinks[node] = min(lowlinks[node], lowlinks[target])
            elif target in on_stack:
                lowlinks[node] = min(lowlinks[node], indices[target])
        if lowlinks[node] == indices[node]:
            component: list[str] = []
            while stack:
                target = stack.pop()
                on_stack.remove(target)
                component.append(target)
                if target == node:
                    break
            if len(component) > 1:
                components.append(tuple(sorted(component)))

    for node in ALLOWED_IMPORTS:
        if node not in indices:
            visit(node)
    return sorted(components)


def concrete_cycle(component: tuple[str, ...], edges: list[ImportEdge]) -> str:
    members = set(component)
    adjacency: dict[str, list[str]] = defaultdict(list)
    for edge in edges:
        if edge.source in members and edge.target in members:
            adjacency[edge.source].append(edge.target)

    start = component[0]
    path: list[str] = []
    active: set[str] = set()

    def visit(node: str) -> list[str] | None:
        path.append(node)
        active.add(node)
        for target in sorted(adjacency[node]):
            if target in active:
                index = path.index(target)
                return [*path[index:], target]
            result = visit(target)
            if result is not None:
                return result
        active.remove(node)
        path.pop()
        return None

    cycle = visit(start)
    if cycle is None:
        raise AssertionError(f"could not render cyclic component: {component}")
    return " -> ".join(cycle)


def test_every_module_is_classified_and_every_edge_is_allowed() -> None:
    unclassified, dynamic_imports, edges = import_edges()
    forbidden = [
        edge
        for edge in edges
        if edge.target not in ALLOWED_IMPORTS[edge.source]
    ]
    assert not unclassified, "Unclassified modules:\n" + "\n".join(unclassified)
    assert not dynamic_imports, "Unsupported dynamic imports:\n" + "\n".join(dynamic_imports)
    assert not forbidden, "Forbidden edges:\n" + "\n".join(
        f"{edge.path.relative_to(ROOT)}:{edge.line}: {edge.source} -> {edge.target}"
        for edge in forbidden
    )


def test_import_graph_is_acyclic() -> None:
    _, _, edges = import_edges()
    components = cyclic_components(edges)
    assert not components, "Cyclic components:\n" + "\n".join(
        concrete_cycle(component, edges) for component in components
    )
```

- [ ] **Step 2: Run the DAG test and verify RED**

Run:

```powershell
python -m pytest tests/test_import_dag.py -q
```

Expected: FAIL with concrete unclassified modules or forbidden edges. It must not fail from a test
syntax/resolution error.

- [ ] **Step 3: Remove every reported reverse edge**

For each failure, use the fixed transformation rule:

```text
shared data imported upward      -> move the data to kernel/contracts
orchestrator imports implementation -> declare a consumer-owned Protocol and inject in app
feature imports provider         -> construct provider in app and inject through consumer port
domain imports feature behavior  -> move behavior to feature, keep pure data/parser below
old root helper imported         -> use the canonical owning-package module
```

Rerun after each source family. Do not add an edge to `ALLOWED_IMPORTS` unless it already points
strictly downward in the design and the source genuinely owns the orchestration. The final expected
output is two passing tests and zero SCCs.

- [ ] **Step 4: Run the full architecture guard suite**

Run:

```powershell
python -m pytest tests/test_import_dag.py tests/test_dependency_isolation.py tests/test_public_surface_boundaries.py tests/test_public_api_manifest.py tests/test_module_boundary_facades.py tests/test_type_contract_ratchets.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit the executable DAG policy**

```powershell
git add rag_modules tests/import_dag_policy.py tests/test_import_dag.py tests/test_dependency_isolation.py
git commit -m "test: enforce global import dag"
```

### Task 8: Retire old surfaces and document the new architecture

**Files:**
- Modify: `rag_modules/public_surface_manifest.py`
- Modify: `docs/public_surface_retirement_plan.md`
- Modify: `README.md`
- Modify: `pyproject.toml`
- Test: `tests/test_public_surface_boundaries.py`
- Test: `tests/test_public_api_manifest.py`
- Test: `tests/test_entrypoints.py`

- [ ] **Step 1: Add failing retirement assertions**

Add the deleted internal paths to the retired-path test data without compatibility replacements:

```python
RETIRED_INTERNAL_MODULES = {
    "rag_modules.app.runtime_contracts",
    "rag_modules.runtime_contracts",
    "rag_modules.dashscope_clients",
    "rag_modules.build_pipeline.document_artifacts.models",
    "rag_modules.routing.statistics",
    "rag_modules.runtime.json_types",
    "rag_modules.runtime.artifacts.manifest",
    "rag_modules.runtime.analysis_models",
    "rag_modules.runtime.error_models",
    "rag_modules.runtime.generation_models",
    "rag_modules.runtime.graph_models",
    "rag_modules.runtime.policy_models",
    "rag_modules.runtime.retrieval_models",
    "rag_modules.runtime.route_models",
    "rag_modules.runtime.trace_models",
    "rag_modules.runtime.workflow_models",
    "rag_modules.runtime.request_control",
    "rag_modules.runtime.artifact_validation",
    "rag_modules.retrieval.hybrid_outcome",
    "rag_modules.domain.shared.query_constraints",
    "rag_modules.text_document",
    "rag_modules.graph.data_preparation",
    "rag_modules.graph.schema",
    "rag_modules.infra.resilience",
    "rag_modules.answer_evidence_builder",
    "rag_modules.entity_linker",
    "rag_modules.fusion",
    "rag_modules.parent_doc_enricher",
    "rag_modules.retrieval_cache",
    "rag_modules.retrieval_observability",
}
```

Assert that each module has no source file, is absent from `sys.modules`, and is not present in
package `__all__` metadata.

- [ ] **Step 2: Run retirement tests and verify RED if stale metadata remains**

Run:

```powershell
python -m pytest tests/test_public_surface_boundaries.py tests/test_public_api_manifest.py -q
```

Expected: FAIL only if an old export/metadata entry still exists; otherwise PASS proves physical
deletion from earlier tasks.

- [ ] **Step 3: Update public-surface and architecture documentation**

Remove `rag_modules.app.runtime_contracts` from the canonical-facade list in
`docs/public_surface_retirement_plan.md`. Add a hard-cutover table mapping every retired path to its
new owner, explicitly stating that no compatibility import is supported.

Add to `README.md`:

````markdown
### Import architecture gate

Production packages follow the allow-listed DAG in `tests/import_dag_policy.py`. Shared DTOs live
in `rag_modules.kernel`; ports live with their consumers; concrete providers are connected only by
`rag_modules.app` composition.

Run the architecture gate with:

```powershell
python -m pytest tests/test_import_dag.py -q
```
````

Update strict mypy overrides in `pyproject.toml`: remove deleted modules and add
`rag_modules.kernel.*`, all new `ports` modules, and `rag_modules.infra.providers.dashscope.*`.

- [ ] **Step 4: Run retirement and entrypoint tests**

Run:

```powershell
python -m pytest tests/test_public_surface_boundaries.py tests/test_public_api_manifest.py tests/test_entrypoints.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit retirement documentation**

```powershell
git add rag_modules/public_surface_manifest.py docs/public_surface_retirement_plan.md README.md pyproject.toml tests
git commit -m "docs: publish import dag ownership rules"
```

### Task 9: Full verification and release gate

**Files:**
- Modify: only files required by a reproducible verification failure
- Test: full repository

- [ ] **Step 1: Prove deleted paths and forbidden imports are absent**

Run:

```powershell
rg -n "runtime_contracts|dashscope_clients|build_pipeline\.document_artifacts\.models|routing\.statistics" rag_modules tests scripts
```

Expected: no matches except explicit retired-path assertions and documentation strings in boundary
tests.

- [ ] **Step 2: Run Ruff checks**

Run:

```powershell
python -m ruff check rag_modules tests scripts
python -m ruff format --check rag_modules tests scripts
```

Expected: both commands exit 0. If `ruff check --fix` or formatting is needed, inspect the diff and
rerun both commands.

- [ ] **Step 3: Run strict type checking**

Run:

```powershell
python -m mypy rag_modules main.py main_build_service.py tests/typecheck
```

Expected: `Success: no issues found`.

- [ ] **Step 4: Run the full test suite**

Run:

```powershell
python -m pytest -q
```

Expected: all tests pass without external services.

- [ ] **Step 5: Run the offline release gate**

Run:

```powershell
python scripts/release_gate.py
```

Expected: release gate exits 0 and reports every required offline check as passed.

- [ ] **Step 6: Inspect final graph and diff**

Run:

```powershell
python -m pytest tests/test_import_dag.py -q
git status --short
git diff --check HEAD~1
```

Expected: DAG tests pass, `git diff --check` is silent, and status contains only intentional final
verification edits.

- [ ] **Step 7: Commit final verification fixes, if any**

If Step 2-6 required source edits:

```powershell
git add rag_modules tests scripts README.md docs pyproject.toml
git commit -m "fix: satisfy global dag release gate"
```

If no files changed, do not create an empty commit.

## Plan self-review record

- Spec coverage: Tasks 1-8 cover kernel DTOs, configuration default injection, consumer-owned
  ports, DashScope/Milvus isolation, orchestration inversion, root-helper retirement, the global
  allow-list, hard-cutover documentation, and full verification.
- Type consistency: `EmbeddingClientPort`, `RouteStatistics`, resolved query settings, and provider
  factory names remain consistent from their defining task through app assembly and tests.
- Compatibility: every old module is physically deleted and explicitly guarded from recreation;
  no task adds a re-export or runtime alias.
- Verification: Task 9 includes Ruff, mypy, full pytest, the AST DAG test, and the offline release
  gate required by the repository instructions.
