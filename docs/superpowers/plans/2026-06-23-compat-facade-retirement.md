# Compatibility Facade Retirement Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove the remaining compatibility facade identities so internal runtime assembly uses canonical workflow/service boundaries only.

**Architecture:** Answering routes through `AnswerWorkflow`; generation routes through `GenerationWorkflowService`; hybrid retrieval is exposed as a canonical `HybridRetrievalService` rather than the legacy `HybridRetrievalModule` name. Old facade names and old import surfaces are retired with boundary tests that fail if they return.

**Tech Stack:** Python 3.11, pytest, dataclasses/protocols, existing application composition and retrieval component factories.

---

### Task 1: Lock Retired Facade Imports

**Files:**
- Modify: `tests/test_public_surface_boundaries.py`
- Modify: `tests/test_public_api_manifest.py`
- Modify: `docs/public_surface_retirement_plan.md`

- [x] Add tests proving `QuestionAnswerService`, `GenerationIntegrationModule`, `HybridRetrievalModule`, `HybridLegacyResultTranslator`, and `RetrievalResult` are not exported from top-level or canonical packages.
- [x] Add tests proving retired facade source files are absent.
- [x] Run `python -m pytest tests/test_public_api_manifest.py tests/test_public_surface_boundaries.py -q` and verify the new tests fail before implementation.

### Task 2: Remove QuestionAnswerService

**Files:**
- Delete: `rag_modules/app/services/question_answer_service.py`
- Delete: `rag_modules/app/runtime_service_resolver.py`
- Modify: `rag_modules/app/services/__init__.py`
- Modify: `rag_modules/app/provider_components/services.py`
- Modify: `rag_modules/app/provider_components/contracts.py`
- Modify: `rag_modules/app/composition/serving_runtime_factory.py`
- Modify: `rag_modules/app/composition/system_answering_service.py`
- Modify: `rag_modules/app/runtime_state.py`
- Modify: `rag_modules/app/runtime_views.py`
- Modify: `rag_modules/app/runtime_view_builder.py`
- Modify: answering/runtime tests

- [x] Convert runtime answering tests to use `AnswerWorkflow` directly.
- [x] Remove `question_answer_service` from serving runtime state and grouped service views.
- [x] Make `SystemAnsweringService` require `answer_workflow`.
- [x] Run focused application tests and fix only canonical workflow behavior.

### Task 3: Remove GenerationIntegrationModule

**Files:**
- Delete: `rag_modules/generation/integration.py`
- Modify: `rag_modules/generation/__init__.py`
- Modify: `rag_modules/__init__.py`
- Replace: `tests/test_generation_workflow_service.py` with generation workflow/context tests.

- [x] Add a failing test showing the old generation integration import is retired.
- [x] Move facade behavior coverage to `GenerationWorkflowService` using existing context factory APIs.
- [x] Run `python -m pytest tests/test_generation_workflow_service.py tests/test_generation_executor.py -q`.

### Task 4: Rename Hybrid Retrieval Facade To Service

**Files:**
- Move/replace: `rag_modules/retrieval/hybrid_facade.py` with canonical service implementation.
- Modify: `rag_modules/retrieval/__init__.py`
- Modify: `rag_modules/app/provider_components/retrieval.py`
- Modify: `rag_modules/app/provider_components/contracts.py`
- Modify: `rag_modules/app/runtime_state.py`
- Modify: `rag_modules/app/runtime_views.py`
- Modify: retrieval/routing tests

- [x] Add `HybridRetrievalService` as the canonical component-factory-backed retrieval service.
- [x] Remove legacy result translator helpers and old `Module` export.
- [x] Update provider, runtime, and routing type hints to use `HybridRetrievalService` or protocol ports.
- [x] Run retrieval and routing focused tests.

### Task 5: Final Verification

**Files:**
- All modified files above.

- [x] Run focused tests for public surface, app runtime, serving runtime factory, generation, retrieval, and routing.
- [x] Run `pre-commit run --all-files` or equivalent Ruff checks if the environment permits.
- [x] Report any skipped checks with the reason.
