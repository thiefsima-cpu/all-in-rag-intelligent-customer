# Root Shared Module Convergence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move the remaining shared root modules into canonical packages without changing runtime behavior.

**Architecture:** Artifact lifecycle helpers move under `rag_modules.runtime.artifacts`, cross-subsystem recipe/query domain contracts move under `rag_modules.domain.shared`, retrieval post-processing moves into the retrieval package, and query tracing moves under `rag_modules.observability`. No root-level compatibility wrappers are retained.

**Tech Stack:** Python 3.11, pytest, Ruff-compatible imports, existing dataclasses and protocols.

---

## File Structure

- Create: `rag_modules/domain/__init__.py`
- Create: `rag_modules/domain/shared/__init__.py`
- Create: `rag_modules/observability/__init__.py`
- Move: `rag_modules/artifacts.py` to `rag_modules/runtime/artifacts/__init__.py`
- Move: `rag_modules/artifact_documents.py` to `rag_modules/runtime/artifacts/documents.py`
- Move: `rag_modules/artifact_json.py` to `rag_modules/runtime/artifacts/json.py`
- Move: `rag_modules/artifact_manifest.py` to `rag_modules/runtime/artifacts/manifest.py`
- Move: `rag_modules/artifact_manifest_store.py` to `rag_modules/runtime/artifacts/manifest_store.py`
- Move: `rag_modules/artifact_registry.py` to `rag_modules/runtime/artifacts/registry.py`
- Move: `rag_modules/artifact_signatures.py` to `rag_modules/runtime/artifacts/signatures.py`
- Move: `rag_modules/query_constraints.py` to `rag_modules/domain/shared/query_constraints.py`
- Move: `rag_modules/semantic_schema.py` to `rag_modules/domain/shared/semantic_schema.py`
- Move: `rag_modules/retrieval_post_processor.py` to `rag_modules/retrieval/post_processor.py`
- Move: `rag_modules/tracing.py` to `rag_modules/observability/tracing.py`
- Move: `rag_modules/tracing_sinks.py` to `rag_modules/observability/tracing_sinks.py`
- Modify: imports in `rag_modules/`, `scripts/`, `tests/`, and `tests/typecheck/`
- Modify: `tests/test_public_surface_boundaries.py`

### Task 1: Add Root Boundary Regression

**Files:**
- Modify: `tests/test_public_surface_boundaries.py`

- [ ] **Step 1: Write the failing boundary test**

Add this constant near the other root path constants:

```python
MIGRATED_ROOT_SHARED_MODULE_FILES = frozenset(
    {
        "artifact_documents.py",
        "artifact_json.py",
        "artifact_manifest.py",
        "artifact_manifest_store.py",
        "artifact_registry.py",
        "artifact_signatures.py",
        "artifacts.py",
        "query_constraints.py",
        "retrieval_post_processor.py",
        "semantic_schema.py",
        "tracing.py",
        "tracing_sinks.py",
    }
)
```

Add this test method to `PublicSurfaceBoundaryTests`:

```python
    def test_migrated_shared_modules_are_not_at_rag_modules_root(self) -> None:
        remaining = {
            path.name for path in RAG_MODULES_DIR.glob("*.py") if path.name in MIGRATED_ROOT_SHARED_MODULE_FILES
        }

        self.assertEqual(set(), remaining)
```

- [ ] **Step 2: Run the boundary test and verify RED**

Run: `python -m pytest tests/test_public_surface_boundaries.py::PublicSurfaceBoundaryTests::test_migrated_shared_modules_are_not_at_rag_modules_root -q`

Expected: FAIL because the listed files still exist under `rag_modules/`.

### Task 2: Move Artifact Runtime Modules

**Files:**
- Create: `rag_modules/runtime/artifacts/`
- Move: artifact files listed in the file structure
- Modify: imports in artifact modules and consumers
- Test: `tests/test_artifact_registry_hot_refresh.py`, `tests/test_document_artifact_cache.py`

- [ ] **Step 1: Move files**

Run:

```powershell
New-Item -ItemType Directory -Force -Path rag_modules\runtime\artifacts
git mv rag_modules\artifacts.py rag_modules\runtime\artifacts\__init__.py
git mv rag_modules\artifact_documents.py rag_modules\runtime\artifacts\documents.py
git mv rag_modules\artifact_json.py rag_modules\runtime\artifacts\json.py
git mv rag_modules\artifact_manifest.py rag_modules\runtime\artifacts\manifest.py
git mv rag_modules\artifact_manifest_store.py rag_modules\runtime\artifacts\manifest_store.py
git mv rag_modules\artifact_registry.py rag_modules\runtime\artifacts\registry.py
git mv rag_modules\artifact_signatures.py rag_modules\runtime\artifacts\signatures.py
```

- [ ] **Step 2: Update artifact internal imports**

Use these replacements:

```python
from .artifact_documents import ...
```

becomes:

```python
from .documents import ...
```

```python
from .artifact_json import ...
```

becomes:

```python
from .json import ...
```

```python
from .artifact_manifest import ...
```

becomes:

```python
from .manifest import ...
```

```python
from .artifact_manifest_store import ...
```

becomes:

```python
from .manifest_store import ...
```

```python
from .artifact_signatures import ...
```

becomes:

```python
from .signatures import ...
```

`manifest.py` and `signatures.py` import `SEMANTIC_SCHEMA_VERSION` from:

```python
from ...domain.shared.semantic_schema import SEMANTIC_SCHEMA_VERSION
```

- [ ] **Step 3: Update artifact consumers**

Replace imports from root artifact modules with `rag_modules.runtime.artifacts` paths:

```python
from rag_modules.artifact_registry import ArtifactRegistry
```

becomes:

```python
from rag_modules.runtime.artifacts.registry import ArtifactRegistry
```

```python
from ..artifacts import ArtifactManifest
```

from runtime modules becomes:

```python
from .artifacts import ArtifactManifest
```

from build-pipeline modules becomes:

```python
from ...runtime.artifacts import ArtifactManifest
```

### Task 3: Move Domain Shared Modules

**Files:**
- Create: `rag_modules/domain/__init__.py`
- Create: `rag_modules/domain/shared/__init__.py`
- Move: `query_constraints.py`, `semantic_schema.py`
- Modify: graph, retrieval, routing, query understanding, runtime, scripts, and tests imports

- [ ] **Step 1: Move files**

Run:

```powershell
New-Item -ItemType Directory -Force -Path rag_modules\domain\shared
git mv rag_modules\query_constraints.py rag_modules\domain\shared\query_constraints.py
git mv rag_modules\semantic_schema.py rag_modules\domain\shared\semantic_schema.py
```

- [ ] **Step 2: Add package exports**

`rag_modules/domain/__init__.py`:

```python
"""Domain-level shared contracts and helpers."""
```

`rag_modules/domain/shared/__init__.py`:

```python
"""Shared recipe/query domain helpers used across RAG subsystems."""

from .query_constraints import QueryConstraintExtractor, QueryConstraints, RecipeConstraintMatcher, parse_minutes
from .semantic_schema import SEMANTIC_NODE_LABELS, SEMANTIC_NODE_LABELS_SET, SEMANTIC_RELATION_TYPES, SEMANTIC_SCHEMA_VERSION, infer_recipe_semantics

__all__ = [
    "QueryConstraintExtractor",
    "QueryConstraints",
    "RecipeConstraintMatcher",
    "SEMANTIC_NODE_LABELS",
    "SEMANTIC_NODE_LABELS_SET",
    "SEMANTIC_RELATION_TYPES",
    "SEMANTIC_SCHEMA_VERSION",
    "infer_recipe_semantics",
    "parse_minutes",
]
```

- [ ] **Step 3: Update imports**

Examples:

```python
from ..query_constraints import QueryConstraints
```

becomes:

```python
from ..domain.shared.query_constraints import QueryConstraints
```

```python
from ..semantic_schema import SEMANTIC_RELATION_TYPES
```

becomes:

```python
from ..domain.shared.semantic_schema import SEMANTIC_RELATION_TYPES
```

Top-level modules use `from .domain.shared...`; scripts and tests use `from rag_modules.domain.shared...`.

### Task 4: Move Retrieval Post-Processor

**Files:**
- Move: `rag_modules/retrieval_post_processor.py` to `rag_modules/retrieval/post_processor.py`
- Modify: routing and tests imports

- [ ] **Step 1: Move file**

Run: `git mv rag_modules\retrieval_post_processor.py rag_modules\retrieval\post_processor.py`

- [ ] **Step 2: Update local imports inside the moved file**

Use:

```python
from ..dashscope_clients import DashScopeRerankClient
from ..evidence_processing import EvidenceUnitRanker, normalize_evidence_document
from ..runtime_contracts import RerankClientPort
from .contracts import EvidenceDocument, ensure_evidence_documents, to_langchain_documents
from .runtime_profile import RetrievalPostProcessSettings
```

- [ ] **Step 3: Update consumers**

Replace:

```python
from ..retrieval_post_processor import RetrievalPostProcessContext, RetrievalPostProcessor
```

with:

```python
from ..retrieval.post_processor import RetrievalPostProcessContext, RetrievalPostProcessor
```

Tests use `from rag_modules.retrieval.post_processor import ...`.

### Task 5: Move Observability Tracing Modules

**Files:**
- Create: `rag_modules/observability/__init__.py`
- Move: `tracing.py`, `tracing_sinks.py`
- Modify: scripts and tests imports

- [ ] **Step 1: Move files**

Run:

```powershell
New-Item -ItemType Directory -Force -Path rag_modules\observability
git mv rag_modules\tracing.py rag_modules\observability\tracing.py
git mv rag_modules\tracing_sinks.py rag_modules\observability\tracing_sinks.py
```

- [ ] **Step 2: Add package exports**

`rag_modules/observability/__init__.py`:

```python
"""Observability helpers for query tracing and runtime diagnostics."""

from .tracing import QueryTracer
from .tracing_sinks import AsyncQueryTraceSink, JsonlQueryTraceSink, NullQueryTraceSink, QueryTraceSink

__all__ = [
    "AsyncQueryTraceSink",
    "JsonlQueryTraceSink",
    "NullQueryTraceSink",
    "QueryTraceSink",
    "QueryTracer",
]
```

- [ ] **Step 3: Update moved imports**

`observability/tracing.py` imports root helpers through parent-relative paths:

```python
from ..retrieval.contracts import EvidenceDocument, ensure_evidence_documents
from ..retrieval_observability import summarize_documents
from ..runtime import (
    AnswerContext,
    AnswerTraceSnapshot,
    GenerationSnapshot,
    GraphRetrievalSnapshot,
    ModelSuiteSnapshot,
    QueryDiagnostics,
    QueryTraceEvent,
    RetrievalOutcome,
    RetrievalTraceSnapshot,
    RouteSnapshot,
    analysis_strategy_name,
)
from ..runtime.json_types import JsonObject, coerce_json_object
from ..runtime.snapshot_utils import clone_generation_snapshot, clone_graph_snapshot, clone_route_snapshot
from ..trace_privacy import TraceSanitizer
from .tracing_sinks import JsonlQueryTraceSink, NullQueryTraceSink, QueryTraceSink
```

`observability/tracing_sinks.py` imports:

```python
from ..runtime import QueryTraceEvent
from ..trace_privacy import TraceSanitizer
```

### Task 6: Verify Green and Clean Imports

**Files:**
- All migrated files and changed import consumers

- [ ] **Step 1: Run import scan**

Run:

```powershell
rg "rag_modules\.(artifact_|artifacts|query_constraints|retrieval_post_processor|semantic_schema|tracing|tracing_sinks)" rag_modules tests scripts
```

Expected: no stale root imports.

- [ ] **Step 2: Run focused tests**

Run:

```powershell
python -m pytest tests/test_public_surface_boundaries.py::PublicSurfaceBoundaryTests::test_migrated_shared_modules_are_not_at_rag_modules_root tests/test_public_api_manifest.py tests/test_artifact_registry_hot_refresh.py tests/test_document_artifact_cache.py tests/test_query_tracer.py tests/test_infrastructure_trace_provider.py tests/test_model_client_ports.py tests/test_route_search_orchestrator.py tests/test_route_execution_strategies.py tests/test_hybrid_retrieval_executor.py tests/test_hybrid_search_service.py tests/test_retrieval_candidate_generator.py tests/test_runtime_workflow_models.py -q
```

Expected: all selected tests pass.

- [ ] **Step 3: Run public surface boundary suite**

Run:

```powershell
python -m pytest tests/test_public_surface_boundaries.py tests/test_public_api_manifest.py -q
```

Expected: all selected tests pass.

- [ ] **Step 4: Run Ruff or pre-commit equivalent**

Run:

```powershell
pre-commit run --all-files
```

Expected: hooks pass. If hooks auto-format files, inspect `git diff` and re-run targeted tests if imports changed.
