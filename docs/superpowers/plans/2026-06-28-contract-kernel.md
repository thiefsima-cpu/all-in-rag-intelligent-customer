# Contract Kernel Dependency Break Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development
> (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move shared DTOs/settings into `rag_modules.contracts` and remove the dependency cycle
between runtime, retrieval, and query-understanding.

**Architecture:** `rag_modules.contracts` becomes the only canonical contract package. Runtime,
retrieval, query-understanding, graph, routing, generation, and tests import shared DTOs from it.
Old retrieval/query-understanding contract ownership is removed rather than re-exported.

**Tech Stack:** Python 3.11, dataclasses, unittest/pytest, Ruff import sorting.

---

### Task 1: Boundary Tests

**Files:**
- Modify: `tests/test_public_surface_boundaries.py`

- [ ] **Step 1: Write failing dependency tests**

Add tests that parse imports and reject:

```python
runtime -> rag_modules.retrieval
runtime -> rag_modules.query_understanding
query_understanding -> rag_modules.retrieval
contracts -> runtime/retrieval/query_understanding/routing/graph/generation/app
any repository code -> rag_modules.retrieval.contracts
any repository code importing QueryPlan or QuerySemanticProfile from rag_modules.query_understanding
```

- [ ] **Step 2: Verify red**

Run:

```powershell
python -m pytest tests/test_public_surface_boundaries.py -q
```

Expected: failure showing the existing imports from runtime and query-understanding.

### Task 2: Create Contract Kernel

**Files:**
- Create: `rag_modules/contracts/__init__.py`
- Create: `rag_modules/contracts/query.py`
- Create: `rag_modules/contracts/query_settings.py`
- Create: `rag_modules/contracts/retrieval.py`
- Create: `rag_modules/contracts/langchain_compat.py`
- Create: `rag_modules/contracts/_common.py`
- Modify: `rag_modules/query_understanding/planner_models.py`
- Modify: `rag_modules/query_understanding/registry.py`
- Modify: `rag_modules/retrieval/contracts/*.py`

- [ ] **Step 1: Move query DTOs**

Move `QuerySemanticScoreBreakdown`, `QuerySemanticProfile`, and `QueryPlan` into
`rag_modules.contracts.query`.

- [ ] **Step 2: Move query settings**

Move `QueryPlannerRuntimeSettings` and `QuerySemanticRuntimeSettings` into
`rag_modules.contracts.query_settings`.

- [ ] **Step 3: Move retrieval DTOs**

Move `EvidenceDocument`, `RetrievalRequest`, and document conversion helpers into
`rag_modules.contracts.retrieval` and `rag_modules.contracts.langchain_compat`.

- [ ] **Step 4: Remove old ownership**

Remove old retrieval contract modules and make query-understanding model/registry modules import
the kernel definitions for internal use only.

### Task 3: Update Consumers

**Files:**
- Modify runtime, retrieval, query_understanding, routing, graph, generation, observability,
  evidence_processing, and tests that import moved contracts.

- [ ] **Step 1: Update runtime imports**

Use `rag_modules.contracts` in runtime model files.

- [ ] **Step 2: Update feature imports**

Use `rag_modules.contracts` anywhere a moved DTO or query settings type is consumed.

- [ ] **Step 3: Update query-understanding service API**

Accept planner and semantic settings directly instead of importing `RetrievalRuntimeProfile`.

### Task 4: Verification

**Files:**
- No production edits unless failures reveal migration gaps.

- [ ] **Step 1: Run focused tests**

```powershell
python -m pytest tests/test_public_surface_boundaries.py tests/test_runtime_workflow_models.py tests/test_runtime_retrieval_models.py tests/test_route_trace_recorder.py tests/test_query_semantics.py -q
```

- [ ] **Step 2: Run broader affected tests**

```powershell
python -m pytest tests/test_retrieval_candidate_generator.py tests/test_route_execution_strategies.py tests/test_route_search_orchestrator.py tests/test_hybrid_retrieval_executor.py tests/test_graph_retrieval_executor.py tests/test_answer_response_mapping.py -q
```

- [ ] **Step 3: Run formatting/lint gate**

```powershell
pre-commit run --all-files
```
