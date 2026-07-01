# LangChain Document Boundary Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove LangChain `Document` from all non-adapter/compat `rag_modules` internals.

**Architecture:** `TextDocument` is the internal text/chunk/parent-document DTO, and
`EvidenceDocument` is the internal retrieval result DTO. LangChain conversion stays only in
`rag_modules/contracts/langchain_compat.py` and `rag_modules/langchain_document_adapter.py`.

**Tech Stack:** Python 3.11, dataclasses, pytest/unittest, existing `TextDocument`,
`EvidenceDocument`, and retrieval runtime modules.

---

## File Structure

- Modify `tests/test_langchain_document_boundary.py`: add the production import boundary test.
- Modify `tests/test_runtime_retrieval_models.py`: assert runtime DTOs are evidence-native only.
- Modify `tests/test_recipe_constraint_matcher.py`: use `TextDocument` instead of LangChain.
- Modify `tests/test_hybrid_retrieval_runtime.py`: use `TextDocument` in hybrid runtime state tests.
- Modify `tests/test_retrieval_cache.py`: use `TextDocument` in cache signature tests.
- Modify `tests/test_safe_logging.py`: use `TextDocument` for BM25 build input.
- Modify `rag_modules/contracts/__init__.py`: remove LangChain compat re-exports.
- Modify `rag_modules/contracts/retrieval.py`: remove DTO methods that know about LangChain.
- Modify `rag_modules/runtime/retrieval_models.py`: remove legacy LangChain input/output.
- Modify `rag_modules/runtime/workflow_models.py`: remove LangChain `documents` property.
- Modify `rag_modules/app/services/answer_models.py`: remove LangChain `documents` property.
- Modify `rag_modules/parent_doc_enricher.py`: use `TextDocument`.
- Modify `rag_modules/retrieval_cache.py`: use `TextDocument`.
- Modify `rag_modules/retrieval/evidence/constraint_matcher.py`: use `TextDocument`.
- Modify `rag_modules/retrieval/adapters/constraint_retriever.py`: map `TextDocument` to evidence.
- Modify `rag_modules/retrieval/adapters/bm25_retriever.py`: store `TextDocument`.
- Modify hybrid runtime/index/parent/executor/service modules: accept and expose `TextDocument`.
- Modify routing modules and tests that read `RetrievalOutcome.documents` only when they were
  referring to removed runtime DTO compatibility.

### Task 1: Add Failing Boundary Tests

- [ ] **Step 1: Write the failing import boundary test**

Add `tests/test_langchain_document_boundary.py`:

```python
from __future__ import annotations

import ast
from pathlib import Path


ALLOWED_IMPORTERS = {
    Path("rag_modules/contracts/langchain_compat.py"),
    Path("rag_modules/langchain_document_adapter.py"),
}


def test_langchain_document_imports_stay_in_adapter_or_compat_layer() -> None:
    root = Path("rag_modules")
    offenders: list[str] = []
    for path in root.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module == "langchain_core.documents":
                relative = path.as_posix()
                if path not in ALLOWED_IMPORTERS:
                    offenders.append(relative)
    assert offenders == []
```

- [ ] **Step 2: Run the boundary test and verify it fails**

Run: `python -m pytest tests/test_langchain_document_boundary.py -q`

Expected: FAIL with a list of current non-adapter `Document` importers.

### Task 2: Remove Runtime/App LangChain DTO Compatibility

- [ ] **Step 1: Update runtime tests**

In `tests/test_runtime_retrieval_models.py`, remove direct LangChain imports and legacy document
input assertions. Assert `RetrievalOutcome` and `AnswerContext` expose `evidence_documents` only.

- [ ] **Step 2: Run the runtime tests and verify they fail**

Run: `python -m pytest tests/test_runtime_retrieval_models.py -q`

Expected: FAIL while production still exposes LangChain-based properties/imports.

- [ ] **Step 3: Remove runtime/app compatibility code**

Edit:

- `rag_modules/runtime/retrieval_models.py`
- `rag_modules/runtime/workflow_models.py`
- `rag_modules/app/services/answer_models.py`
- `rag_modules/contracts/retrieval.py`
- `rag_modules/contracts/__init__.py`

Remove LangChain imports, legacy `documents_input`, `documents` properties, and DTO methods or
top-level re-exports that expose LangChain conversion.

- [ ] **Step 4: Run runtime tests**

Run: `python -m pytest tests/test_runtime_retrieval_models.py tests/test_runtime_workflow_models.py tests/test_answer_workflow.py -q`

Expected: PASS.

### Task 3: Convert Retrieval Text Internals To TextDocument

- [ ] **Step 1: Update retrieval tests**

Change matcher, cache, safe logging, and hybrid runtime tests to construct `TextDocument` instead
of LangChain `Document` for internal retrieval setup.

- [ ] **Step 2: Run focused retrieval tests and verify failures**

Run:

```powershell
python -m pytest tests/test_recipe_constraint_matcher.py tests/test_retrieval_cache.py tests/test_hybrid_retrieval_runtime.py tests/test_safe_logging.py -q
```

Expected: FAIL until production signatures accept `TextDocument`.

- [ ] **Step 3: Implement TextDocument internals**

Edit:

- `rag_modules/parent_doc_enricher.py`
- `rag_modules/retrieval_cache.py`
- `rag_modules/retrieval/evidence/constraint_matcher.py`
- `rag_modules/retrieval/adapters/constraint_retriever.py`
- `rag_modules/retrieval/adapters/bm25_retriever.py`
- `rag_modules/retrieval/hybrid_runtime_state.py`
- `rag_modules/retrieval/hybrid_index_service.py`
- `rag_modules/retrieval/hybrid_parent_document_service.py`
- `rag_modules/retrieval/hybrid_runtime.py`
- `rag_modules/retrieval/hybrid_executor.py`
- `rag_modules/retrieval/hybrid_service.py`
- `rag_modules/app/composition/serving_runtime_preparer.py`

Use `TextDocument.content`/`metadata` internally. Where a LangChain caller is still needed, require
the caller to use `langchain_document_adapter` explicitly.

- [ ] **Step 4: Run focused retrieval tests**

Run:

```powershell
python -m pytest tests/test_recipe_constraint_matcher.py tests/test_retrieval_cache.py tests/test_hybrid_retrieval_runtime.py tests/test_hybrid_retrieval_executor.py tests/test_hybrid_search_service.py tests/test_safe_logging.py -q
```

Expected: PASS.

### Task 4: Update Internal Call Sites And Verify Boundary

- [ ] **Step 1: Replace internal calls to removed runtime `documents` properties**

Edit routing/app/tests call sites to read `evidence_documents` or `HybridRetrievalOutcome.documents`
where the latter is already evidence-native.

- [ ] **Step 2: Run route and boundary tests**

Run:

```powershell
python -m pytest tests/test_langchain_document_boundary.py tests/test_route_execution_strategies.py tests/test_route_search_orchestrator.py -q
```

Expected: PASS.

- [ ] **Step 3: Run public surface checks**

Run:

```powershell
python -m pytest tests/test_public_surface_boundaries.py tests/test_public_api_manifest.py -q
```

Expected: PASS.

### Task 5: Final Verification

- [ ] **Step 1: Run the focused changed-test suite**

Run:

```powershell
python -m pytest tests/test_langchain_document_boundary.py tests/test_runtime_retrieval_models.py tests/test_runtime_workflow_models.py tests/test_answer_workflow.py tests/test_recipe_constraint_matcher.py tests/test_retrieval_cache.py tests/test_hybrid_retrieval_runtime.py tests/test_hybrid_retrieval_executor.py tests/test_hybrid_search_service.py tests/test_route_execution_strategies.py tests/test_route_search_orchestrator.py tests/test_safe_logging.py -q
```

Expected: PASS.

- [ ] **Step 2: Run Ruff or pre-commit equivalent**

Run: `pre-commit run --all-files`

Expected: PASS, or report any unavailable hook/dependency issue with output.

## Self-Review

- Spec coverage: boundary, runtime/app cleanup, retrieval DTO conversion, and verification are
  covered.
- Placeholder scan: no `TBD`, `TODO`, or unspecified implementation steps remain.
- Type consistency: `TextDocument` is used for text chunks/parents; `EvidenceDocument` is used for
  retrieval results; LangChain conversion is named only in adapter/compat modules.
