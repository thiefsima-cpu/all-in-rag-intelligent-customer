# API, Generation, And Milvus Module Split Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split the API service, generation executor, and Milvus infrastructure modules into clear canonical packages while preserving current behavior and old import paths.

**Architecture:** Use three independent refactor slices: API service package, generation execution package, and Milvus infrastructure package. Each old file becomes a thin compatibility export; internal imports touched by the refactor move to canonical modules. No git commits are made during this work; checkpoint steps stage files only.

**Tech Stack:** Python 3.11, FastAPI, Pydantic, unittest/pytest, pymilvus, PowerShell.

---

## Scope Check

The approved spec covers three subsystems. Keep them in one implementation plan because the objective is one boundary-cleanup refactor, but execute and verify them independently in this order:

1. API service split.
2. Generation execution split.
3. Milvus infrastructure split.

Each slice must pass its focused tests before the next slice starts.

## File Structure

Create or modify these files:

- Create: `rag_modules/interfaces/api/services/__init__.py`
- Create: `rag_modules/interfaces/api/services/base.py`
- Create: `rag_modules/interfaces/api/services/errors.py`
- Create: `rag_modules/interfaces/api/services/serving.py`
- Create: `rag_modules/interfaces/api/services/build.py`
- Modify: `rag_modules/interfaces/api/service.py`
- Modify: `rag_modules/interfaces/api/routes.py`
- Modify: `tests/test_api_app.py`
- Create: `rag_modules/generation/execution/__init__.py`
- Create: `rag_modules/generation/execution/engine.py`
- Create: `rag_modules/generation/execution/direct.py`
- Create: `rag_modules/generation/execution/two_stage.py`
- Create: `rag_modules/generation/execution/streaming.py`
- Create: `rag_modules/generation/execution/tracing.py`
- Create: `rag_modules/generation/execution/timeouts.py`
- Modify: `rag_modules/generation/executor.py`
- Modify: `rag_modules/generation/module_builder.py`
- Modify: `rag_modules/generation/__init__.py`
- Modify: `tests/test_generation_executor.py`
- Create: `rag_modules/infra/milvus/__init__.py`
- Create: `rag_modules/infra/milvus/module.py`
- Create: `rag_modules/infra/milvus/client.py`
- Create: `rag_modules/infra/milvus/schema.py`
- Create: `rag_modules/infra/milvus/writer.py`
- Create: `rag_modules/infra/milvus/search.py`
- Create: `rag_modules/infra/milvus/blue_green.py`
- Modify: `rag_modules/infra/milvus_index_construction.py`
- Modify: `rag_modules/infra/__init__.py`
- Modify: `rag_modules/app/provider_components/infrastructure.py`
- Modify: `tests/test_milvus_blue_green.py`
- Modify: `tests/test_public_surface_boundaries.py`

## Task 1: Add Canonical Import And Thin-Wrapper Tests

**Files:**
- Modify: `tests/test_api_app.py`
- Modify: `tests/test_generation_executor.py`
- Modify: `tests/test_milvus_blue_green.py`
- Modify: `tests/test_public_surface_boundaries.py`

- [ ] **Step 1: Add API canonical import test**

Add this method inside `ApiAppTests` in `tests/test_api_app.py`:

```python
    def test_api_service_canonical_and_compat_imports_match(self) -> None:
        from rag_modules.interfaces.api import service as compat_service
        from rag_modules.interfaces.api.services import (
            BuildJobConflictError as CanonicalBuildJobConflictError,
            BuildJobNotFoundError as CanonicalBuildJobNotFoundError,
            GraphRAGBuildApiService as CanonicalBuildService,
            GraphRAGServingApiService as CanonicalServingService,
            SystemNotReadyError as CanonicalSystemNotReadyError,
        )

        self.assertIs(compat_service.GraphRAGBuildApiService, CanonicalBuildService)
        self.assertIs(compat_service.GraphRAGServingApiService, CanonicalServingService)
        self.assertIs(compat_service.SystemNotReadyError, CanonicalSystemNotReadyError)
        self.assertIs(compat_service.BuildJobNotFoundError, CanonicalBuildJobNotFoundError)
        self.assertIs(compat_service.BuildJobConflictError, CanonicalBuildJobConflictError)
```

- [ ] **Step 2: Add generation canonical import test**

Add this method inside `GenerationExecutionEngineTests` in `tests/test_generation_executor.py`:

```python
    def test_generation_execution_canonical_and_compat_imports_match(self) -> None:
        from rag_modules.generation.execution import (
            GenerationExecutionEngine as PackageEngine,
        )
        from rag_modules.generation.execution.engine import (
            GenerationExecutionEngine as CanonicalEngine,
        )
        from rag_modules.generation.executor import (
            GenerationExecutionEngine as CompatEngine,
        )

        self.assertIs(PackageEngine, CanonicalEngine)
        self.assertIs(CompatEngine, CanonicalEngine)
```

- [ ] **Step 3: Add Milvus canonical import test**

Add this method inside `MilvusBlueGreenTests` in `tests/test_milvus_blue_green.py`:

```python
    def test_milvus_canonical_and_compat_imports_match(self) -> None:
        from rag_modules.infra.milvus import (
            MilvusIndexConstructionModule as PackageModule,
        )
        from rag_modules.infra.milvus.module import (
            MilvusIndexConstructionModule as CanonicalModule,
        )
        from rag_modules.infra.milvus_index_construction import (
            MilvusIndexConstructionModule as CompatModule,
        )

        self.assertIs(PackageModule, CanonicalModule)
        self.assertIs(CompatModule, CanonicalModule)
```

- [ ] **Step 4: Add thin-wrapper boundary test**

Add this method inside `PublicSurfaceBoundaryTests` in `tests/test_public_surface_boundaries.py`:

```python
    def test_refactored_compat_modules_are_thin_exports(self) -> None:
        expected_imports = {
            RAG_MODULES_DIR / "interfaces" / "api" / "service.py": {
                "rag_modules.interfaces.api.services",
            },
            RAG_MODULES_DIR / "generation" / "executor.py": {
                "rag_modules.generation.execution",
            },
            RAG_MODULES_DIR / "infra" / "milvus_index_construction.py": {
                "rag_modules.infra.milvus",
            },
        }
        violations: list[str] = []

        for path, allowed_imports in expected_imports.items():
            source = path.read_text(encoding="utf-8-sig")
            tree = ast.parse(source, filename=str(path))
            rel = path.relative_to(ROOT)
            imported_modules: set[str] = set()

            for index, node in enumerate(tree.body):
                if (
                    index == 0
                    and isinstance(node, ast.Expr)
                    and isinstance(node.value, ast.Constant)
                    and isinstance(node.value.value, str)
                ):
                    continue
                if isinstance(node, ast.ImportFrom):
                    module_name = self._resolve_import_from(path, node)
                    imported_modules.add(module_name)
                    if module_name == "__future__":
                        continue
                    if module_name not in allowed_imports:
                        violations.append(
                            f"{rel}:{node.lineno}: imports {module_name!r}, expected one of {sorted(allowed_imports)!r}"
                        )
                    if any(alias.name == "*" for alias in node.names):
                        violations.append(f"{rel}:{node.lineno}: star import is not a thin export")
                    continue
                if isinstance(node, ast.Assign) and all(
                    isinstance(target, ast.Name) and target.id == "__all__"
                    for target in node.targets
                ):
                    continue
                violations.append(
                    f"{rel}:{node.lineno}: {source.splitlines()[node.lineno - 1].strip()}"
                )

            self.assertTrue(
                imported_modules & allowed_imports,
                f"{rel} should import one canonical module from {sorted(allowed_imports)!r}",
            )

        self.assertFalse(
            violations,
            "Found refactored compatibility modules with local logic:\n"
            + "\n".join(violations),
        )
```

- [ ] **Step 5: Run tests to verify they fail for missing canonical packages**

Run:

```powershell
pytest tests/test_api_app.py::ApiAppTests::test_api_service_canonical_and_compat_imports_match `
  tests/test_generation_executor.py::GenerationExecutionEngineTests::test_generation_execution_canonical_and_compat_imports_match `
  tests/test_milvus_blue_green.py::MilvusBlueGreenTests::test_milvus_canonical_and_compat_imports_match `
  tests/test_public_surface_boundaries.py::PublicSurfaceBoundaryTests::test_refactored_compat_modules_are_thin_exports -q
```

Expected: FAIL. At least one failure must mention `ModuleNotFoundError` for `rag_modules.interfaces.api.services`, `rag_modules.generation.execution`, or `rag_modules.infra.milvus`. The thin-wrapper test should also fail because the old files still contain local logic.

## Task 2: Split API Service Package

**Files:**
- Create: `rag_modules/interfaces/api/services/__init__.py`
- Create: `rag_modules/interfaces/api/services/base.py`
- Create: `rag_modules/interfaces/api/services/errors.py`
- Create: `rag_modules/interfaces/api/services/serving.py`
- Create: `rag_modules/interfaces/api/services/build.py`
- Modify: `rag_modules/interfaces/api/service.py`
- Modify: `rag_modules/interfaces/api/routes.py`
- Test: `tests/test_api_app.py`

- [ ] **Step 1: Create API errors module**

Create `rag_modules/interfaces/api/services/errors.py` with the current exception definitions moved from `rag_modules/interfaces/api/service.py`:

```python
"""Exceptions raised by API service orchestration."""

from __future__ import annotations


class _StreamCancelledError(RuntimeError):
    """Raised when an SSE consumer disconnects and the background runner should stop."""


class SystemNotReadyError(RuntimeError):
    """Raised when the serving runtime exists but artifacts are not answer-ready."""

    def __init__(self, message: str, *, diagnostics: dict):
        super().__init__(message)
        self.diagnostics = diagnostics


class BuildJobNotFoundError(KeyError):
    """Raised when a build job identifier is unknown to the current API service."""

    def __init__(self, job_id: str):
        super().__init__(job_id)
        self.job_id = str(job_id)


class BuildJobConflictError(RuntimeError):
    """Raised when a new build job is submitted while another build job is active."""

    def __init__(self, message: str, *, job: dict):
        super().__init__(message)
        self.job = dict(job)


__all__ = [
    "BuildJobConflictError",
    "BuildJobNotFoundError",
    "SystemNotReadyError",
]
```

- [ ] **Step 2: Create API base module**

Create `rag_modules/interfaces/api/services/base.py`. Move these existing definitions from `rag_modules/interfaces/api/service.py` without changing method bodies except imports:

- `_API_LOCKS_ATTR`
- `_API_LOCKS_CREATION_LOCK`
- `_GraphRAGApiServiceLocks`
- `_resolve_shared_api_locks`
- `_BaseGraphRAGApiService`

Remove stream-executor fields and `_resolve_stream_executor` from `_BaseGraphRAGApiService`. The base service `__init__` must initialize only `system`, `_locks`, `_stats_cache`, and `_diagnostics_cache`. The base `shutdown()` must close only the application system:

```python
    def shutdown(self) -> None:
        with self._exclusive_runtime_operation():
            self.system.close()
```

- [ ] **Step 3: Create serving API service module**

Create `rag_modules/interfaces/api/services/serving.py`. Move `GraphRAGServingApiService` from the old file and move these serving-only constants into the same module:

- `_STREAM_END`
- `_STREAM_QUEUE_MAX_SIZE`
- `_STREAM_EXECUTOR_MAX_WORKERS`

Add stream executor ownership to `GraphRAGServingApiService.__init__`:

```python
        self._stream_executor: ThreadPoolExecutor | None = None
        self._stream_executor_lock = threading.Lock()
```

Add `_resolve_stream_executor()` to `GraphRAGServingApiService` using the existing method body from the old base class. Add serving shutdown before calling `super().shutdown()`:

```python
    def shutdown(self) -> None:
        executor = self._stream_executor
        self._stream_executor = None
        if executor is not None:
            executor.shutdown(wait=False, cancel_futures=True)
        super().shutdown()
```

Import `_BaseGraphRAGApiService` from `.base`, `SystemNotReadyError` and `_StreamCancelledError` from `.errors`, and `AnswerStreamEventModel` from `..models`.

- [ ] **Step 4: Create build API service module**

Create `rag_modules/interfaces/api/services/build.py`. Move these definitions from `rag_modules/interfaces/api/service.py`:

- `_BUILD_JOB_EXECUTOR_MAX_WORKERS`
- `_utc_now_iso`
- `GraphRAGBuildApiService`

Import `_BaseGraphRAGApiService` from `.base` and build errors from `.errors`. Keep build executor ownership in this module and keep the current `shutdown()` behavior that shuts down `_build_executor` before `super().shutdown()`.

- [ ] **Step 5: Create API services package exports**

Create `rag_modules/interfaces/api/services/__init__.py`:

```python
"""Canonical API service exports."""

from .build import GraphRAGBuildApiService
from .errors import (
    BuildJobConflictError,
    BuildJobNotFoundError,
    SystemNotReadyError,
)
from .serving import GraphRAGServingApiService

__all__ = [
    "BuildJobConflictError",
    "BuildJobNotFoundError",
    "GraphRAGBuildApiService",
    "GraphRAGServingApiService",
    "SystemNotReadyError",
]
```

- [ ] **Step 6: Replace old API service file with compatibility exports**

Replace `rag_modules/interfaces/api/service.py` with:

```python
"""Compatibility exports for API service classes."""

from __future__ import annotations

from .services import (
    BuildJobConflictError,
    BuildJobNotFoundError,
    GraphRAGBuildApiService,
    GraphRAGServingApiService,
    SystemNotReadyError,
)

__all__ = [
    "BuildJobConflictError",
    "BuildJobNotFoundError",
    "GraphRAGBuildApiService",
    "GraphRAGServingApiService",
    "SystemNotReadyError",
]
```

- [ ] **Step 7: Update API routes to canonical service imports**

In `rag_modules/interfaces/api/routes.py`, replace:

```python
from .service import (
```

with:

```python
from .services import (
```

Keep the imported names unchanged.

- [ ] **Step 8: Run API focused tests**

Run:

```powershell
pytest tests/test_api_app.py -q
```

Expected: PASS.

- [ ] **Step 9: Stage API slice files**

Run:

```powershell
git -c safe.directory=E:/ai-project/all-in-rag add -- `
  rag_modules/interfaces/api/services/__init__.py `
  rag_modules/interfaces/api/services/base.py `
  rag_modules/interfaces/api/services/errors.py `
  rag_modules/interfaces/api/services/serving.py `
  rag_modules/interfaces/api/services/build.py `
  rag_modules/interfaces/api/service.py `
  rag_modules/interfaces/api/routes.py `
  tests/test_api_app.py
```

Expected: files are staged. Do not run `git commit`.

## Task 3: Split Generation Execution Package

**Files:**
- Create: `rag_modules/generation/execution/__init__.py`
- Create: `rag_modules/generation/execution/engine.py`
- Create: `rag_modules/generation/execution/direct.py`
- Create: `rag_modules/generation/execution/two_stage.py`
- Create: `rag_modules/generation/execution/streaming.py`
- Create: `rag_modules/generation/execution/tracing.py`
- Create: `rag_modules/generation/execution/timeouts.py`
- Modify: `rag_modules/generation/executor.py`
- Modify: `rag_modules/generation/module_builder.py`
- Modify: `rag_modules/generation/__init__.py`
- Test: `tests/test_generation_executor.py`

- [ ] **Step 1: Create generation timeout mixin**

Create `rag_modules/generation/execution/timeouts.py` with `_GenerationTimeoutMixin`. Move these existing methods from `GenerationExecutionEngine` unchanged:

- `_deadline`
- `_remaining_timeout`
- `_elapsed_ms`

The module imports `time` and `GenerationLatencyBudgetExceeded`.

- [ ] **Step 2: Create generation tracing mixin**

Create `rag_modules/generation/execution/tracing.py` with `_GenerationTraceMixin`. Move these existing methods from `GenerationExecutionEngine` unchanged:

- `_clone_trace`
- `_snapshot_trace`
- `_new_trace`
- `_record_empty_trace`
- `_consume_retry_count`
- `_consume_token_usage`
- `_finalize_trace`

The module imports `Any`, `AnswerEvidencePackage`, `GenerationDecision`, and `GenerationSnapshot`.

- [ ] **Step 3: Create direct completion mixin**

Create `rag_modules/generation/execution/direct.py` with `_DirectCompletionMixin`. Move these existing methods from `GenerationExecutionEngine` unchanged:

- `_run_direct_completion`
- `_response_text`

The module imports `GenerationClientAdapter`, `AnswerContext`, and `time`.

- [ ] **Step 4: Create two-stage completion mixin**

Create `rag_modules/generation/execution/two_stage.py` with `_TwoStageCompletionMixin`. Move these existing methods from `GenerationExecutionEngine` unchanged:

- `_generate_two_stage_with_fallback`
- `_run_two_stage_completion`
- `_build_fallback_answer`
- `_build_answer_plan`

The module imports `inspect`, `logging`, `time`, `AnswerEvidencePackage`, `AnswerContext`, `GenerationSnapshot`, `AnswerPlan`, `build_evidence_only_fallback_answer`, `should_skip_model_fallback`, and `generation_failure_code`. Define `logger = logging.getLogger(__name__)`.

- [ ] **Step 5: Create streaming mixin**

Create `rag_modules/generation/execution/streaming.py` with `_StreamingGenerationMixin`. Move these existing public methods from `GenerationExecutionEngine` unchanged:

- `stream`
- `stream_with_trace`

The module imports `Any`, `logging`, `time`, `AnswerEvidencePackage`, `AnswerContext`, `GenerationSnapshot`, `decide_generation_mode`, `should_skip_model_fallback`, and `generation_failure_code`. Define `logger = logging.getLogger(__name__)`.

- [ ] **Step 6: Create canonical execution engine**

Create `rag_modules/generation/execution/engine.py`. Keep `GenerationExecutionEngine.__init__`, `generate`, `generate_with_trace`, `compose`, `compose_from_context`, and `_resolve_answer_context` in this class. Inherit from the mixins:

```python
"""Canonical generation execution engine."""

from __future__ import annotations

import logging
import time
from typing import Any

from ...answer_evidence_builder import AnswerEvidencePackage
from ...runtime import AnswerContext, GenerationSnapshot, RetrievalOutcome
from ..client import GenerationClientAdapter, generation_failure_code
from ..decision import decide_generation_mode
from ..models import AnswerPlan, GenerationSettings
from ..planner import GenerationPlanner
from ..prompt_builder import GenerationPromptBuilder
from .direct import _DirectCompletionMixin
from .streaming import _StreamingGenerationMixin
from .timeouts import _GenerationTimeoutMixin
from .tracing import _GenerationTraceMixin
from .two_stage import _TwoStageCompletionMixin

logger = logging.getLogger(__name__)


class GenerationExecutionEngine(
    _StreamingGenerationMixin,
    _TwoStageCompletionMixin,
    _DirectCompletionMixin,
    _GenerationTraceMixin,
    _GenerationTimeoutMixin,
):
    """Own generation execution, retries, fallback, and trace state."""
```

Paste the current method bodies for `__init__`, `generate`, `generate_with_trace`, `compose`, `compose_from_context`, and `_resolve_answer_context` under this class. Remove moved methods from this class.

- [ ] **Step 7: Create execution package exports**

Create `rag_modules/generation/execution/__init__.py`:

```python
"""Canonical generation execution exports."""

from .engine import GenerationExecutionEngine

__all__ = ["GenerationExecutionEngine"]
```

- [ ] **Step 8: Replace old generation executor with compatibility export**

Replace `rag_modules/generation/executor.py` with:

```python
"""Compatibility export for the canonical generation execution engine."""

from __future__ import annotations

from .execution import GenerationExecutionEngine

__all__ = ["GenerationExecutionEngine"]
```

- [ ] **Step 9: Update internal generation imports**

In `rag_modules/generation/module_builder.py`, replace:

```python
from .executor import GenerationExecutionEngine
```

with:

```python
from .execution import GenerationExecutionEngine
```

In `rag_modules/generation/__init__.py`, replace:

```python
from .executor import GenerationExecutionEngine
```

with:

```python
from .execution import GenerationExecutionEngine
```

- [ ] **Step 10: Run generation focused tests**

Run:

```powershell
pytest tests/test_generation_executor.py -q
```

Expected: PASS.

- [ ] **Step 11: Stage generation slice files**

Run:

```powershell
git -c safe.directory=E:/ai-project/all-in-rag add -- `
  rag_modules/generation/execution/__init__.py `
  rag_modules/generation/execution/engine.py `
  rag_modules/generation/execution/direct.py `
  rag_modules/generation/execution/two_stage.py `
  rag_modules/generation/execution/streaming.py `
  rag_modules/generation/execution/tracing.py `
  rag_modules/generation/execution/timeouts.py `
  rag_modules/generation/executor.py `
  rag_modules/generation/module_builder.py `
  rag_modules/generation/__init__.py `
  tests/test_generation_executor.py
```

Expected: files are staged. Do not run `git commit`.

## Task 4: Split Milvus Infrastructure Package

**Files:**
- Create: `rag_modules/infra/milvus/__init__.py`
- Create: `rag_modules/infra/milvus/module.py`
- Create: `rag_modules/infra/milvus/client.py`
- Create: `rag_modules/infra/milvus/schema.py`
- Create: `rag_modules/infra/milvus/writer.py`
- Create: `rag_modules/infra/milvus/search.py`
- Create: `rag_modules/infra/milvus/blue_green.py`
- Modify: `rag_modules/infra/milvus_index_construction.py`
- Modify: `rag_modules/infra/__init__.py`
- Modify: `rag_modules/app/provider_components/infrastructure.py`
- Test: `tests/test_milvus_blue_green.py`

- [ ] **Step 1: Create Milvus client operations mixin**

Create `rag_modules/infra/milvus/client.py` with `_MilvusClientOperations`. Move these existing methods from `MilvusIndexConstructionModule` unchanged:

- `_setup_client`
- `_setup_embeddings`
- `get_collection_stats`
- `delete_collection`
- `has_collection`
- `load_collection`
- `close`
- `__del__`

The module imports `logging`, `Dict`, `Any`, `Optional`, `MilvusClient`, and `DashScopeEmbeddingClient`. Define `logger = logging.getLogger(__name__)`.

- [ ] **Step 2: Create Milvus schema operations mixin**

Create `rag_modules/infra/milvus/schema.py` with `_MilvusSchemaOperations`. Move these existing methods from `MilvusIndexConstructionModule` unchanged:

- `_create_collection_schema`
- `create_collection`
- `create_index`

The module imports `logging`, `Optional`, `CollectionSchema`, `DataType`, and `FieldSchema`. Define `logger = logging.getLogger(__name__)`.

- [ ] **Step 3: Create Milvus writer operations mixin**

Create `rag_modules/infra/milvus/writer.py` with `_MilvusWriterOperations`. Move these existing methods from `MilvusIndexConstructionModule` unchanged:

- `_safe_truncate`
- `build_vector_index`
- `add_documents`

The module imports `logging`, `time`, `List`, `Optional`, and `TextDocument`. Define `logger = logging.getLogger(__name__)`.

- [ ] **Step 4: Create Milvus search operations mixin**

Create `rag_modules/infra/milvus/search.py` with `_MilvusSearchOperations`. Move `similarity_search` from `MilvusIndexConstructionModule` unchanged. The module imports `logging`, `List`, `Dict`, `Any`, and `Optional`. Define `logger = logging.getLogger(__name__)`.

- [ ] **Step 5: Create Milvus blue-green operations mixin**

Create `rag_modules/infra/milvus/blue_green.py` with `_MilvusBlueGreenOperations`. Move these existing methods from `MilvusIndexConstructionModule` unchanged:

- `use_manifest`
- `prepare_blue_green_build`
- `publish_collection`
- `rollback_collection_publish`
- `discard_build_collection`
- `alias_target`
- `physical_collection_name`
- `_collection_slot`

The module imports `Dict`.

- [ ] **Step 6: Create canonical Milvus module class**

Create `rag_modules/infra/milvus/module.py`. Keep only constructor state initialization in `MilvusIndexConstructionModule` and inherit the mixins:

```python
"""Canonical Milvus index construction module."""

from __future__ import annotations

from .blue_green import _MilvusBlueGreenOperations
from .client import _MilvusClientOperations
from .schema import _MilvusSchemaOperations
from .search import _MilvusSearchOperations
from .writer import _MilvusWriterOperations


class MilvusIndexConstructionModule(
    _MilvusBlueGreenOperations,
    _MilvusSearchOperations,
    _MilvusWriterOperations,
    _MilvusSchemaOperations,
    _MilvusClientOperations,
):
    """Milvus index construction module for vector writes, reads, and publish flow."""
```

Paste the current `__init__` body from `rag_modules/infra/milvus_index_construction.py` under this class. Keep constructor parameters and state names unchanged.

- [ ] **Step 7: Create Milvus package exports**

Create `rag_modules/infra/milvus/__init__.py`:

```python
"""Canonical Milvus infrastructure exports."""

from .module import MilvusIndexConstructionModule

__all__ = ["MilvusIndexConstructionModule"]
```

- [ ] **Step 8: Replace old Milvus file with compatibility export**

Replace `rag_modules/infra/milvus_index_construction.py` with:

```python
"""Compatibility export for the canonical Milvus infrastructure module."""

from __future__ import annotations

from .milvus import MilvusIndexConstructionModule

__all__ = ["MilvusIndexConstructionModule"]
```

- [ ] **Step 9: Update internal Milvus imports**

In `rag_modules/infra/__init__.py`, replace:

```python
from .milvus_index_construction import MilvusIndexConstructionModule
```

with:

```python
from .milvus import MilvusIndexConstructionModule
```

In `rag_modules/app/provider_components/infrastructure.py`, replace:

```python
from ...infra.milvus_index_construction import MilvusIndexConstructionModule
```

with:

```python
from ...infra.milvus import MilvusIndexConstructionModule
```

- [ ] **Step 10: Run Milvus focused tests**

Run:

```powershell
pytest tests/test_milvus_blue_green.py -q
```

Expected: PASS.

- [ ] **Step 11: Stage Milvus slice files**

Run:

```powershell
git -c safe.directory=E:/ai-project/all-in-rag add -- `
  rag_modules/infra/milvus/__init__.py `
  rag_modules/infra/milvus/module.py `
  rag_modules/infra/milvus/client.py `
  rag_modules/infra/milvus/schema.py `
  rag_modules/infra/milvus/writer.py `
  rag_modules/infra/milvus/search.py `
  rag_modules/infra/milvus/blue_green.py `
  rag_modules/infra/milvus_index_construction.py `
  rag_modules/infra/__init__.py `
  rag_modules/app/provider_components/infrastructure.py `
  tests/test_milvus_blue_green.py
```

Expected: files are staged. Do not run `git commit`.

## Task 5: Final Boundary Verification

**Files:**
- Modify: `tests/test_public_surface_boundaries.py`
- Test: targeted and full verification commands

- [ ] **Step 1: Run thin-wrapper boundary test**

Run:

```powershell
pytest tests/test_public_surface_boundaries.py::PublicSurfaceBoundaryTests::test_refactored_compat_modules_are_thin_exports -q
```

Expected: PASS.

- [ ] **Step 2: Run targeted refactor suite**

Run:

```powershell
pytest tests/test_api_app.py `
  tests/test_generation_executor.py `
  tests/test_milvus_blue_green.py `
  tests/test_public_surface_boundaries.py `
  tests/test_dependency_isolation.py -q
```

Expected: PASS.

- [ ] **Step 3: Run full test suite**

Run:

```powershell
pytest -q
```

Expected: PASS. If a failure requires external Milvus, Neo4j, or DashScope access, record the exact failing test name and rerun the targeted refactor suite to confirm the refactor itself is clean.

- [ ] **Step 4: Inspect compatibility files manually**

Run:

```powershell
Get-Content -LiteralPath 'rag_modules\interfaces\api\service.py'
Get-Content -LiteralPath 'rag_modules\generation\executor.py'
Get-Content -LiteralPath 'rag_modules\infra\milvus_index_construction.py'
```

Expected: each file contains only a module docstring, `from __future__ import annotations`, canonical imports, and `__all__`.

- [ ] **Step 5: Stage final boundary files**

Run:

```powershell
git -c safe.directory=E:/ai-project/all-in-rag add -- `
  tests/test_public_surface_boundaries.py
```

Expected: final boundary test is staged. Do not run `git commit`.
