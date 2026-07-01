# Runtime Error Semantics Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Replace runtime fallback and exception strings with stable typed error details across provider, retrieval, routing, and generation traces.

**Architecture:** Add a runtime error-detail contract that serializes as `{code, detail}` and is built from explicit subsystem classifiers. Update trace snapshots and degraded-candidate metadata to carry that contract directly, then adapt answer API DTOs and tests to expose the typed shape instead of sanitizing raw strings after the fact.

**Tech Stack:** Python 3.11 dataclasses, Pydantic v2 response DTOs, unittest/pytest, existing safe logging.

---

## File Structure

- Create `rag_modules/runtime/error_models.py` for `RuntimeErrorDetail`, safe serialization, and subsystem classifiers.
- Modify `rag_modules/runtime/route_models.py`, `rag_modules/runtime/graph_models.py`, and `rag_modules/runtime/trace_models.py` so trace `error` fields are typed details.
- Modify `rag_modules/retrieval/candidate_generator.py` so degraded candidates emit `{source, error: {code, detail}}` instead of raw exception-derived fields.
- Modify `rag_modules/generation/clients/errors.py` and generation execution helpers so provider failures populate typed generation details while preserving fallback decisions through explicit classifier output.
- Modify `rag_modules/routing/workflow_service.py` and `rag_modules/app/services/answer_workflow.py` so fallback metadata and query traces receive typed safe errors only.
- Modify `rag_modules/interfaces/api/answer_mappers.py`, `answer_debug_models.py`, and `answer_public_models.py` so response schemas expose typed error objects.
- Update focused tests in `tests/test_answer_workflow.py`, `tests/test_retrieval_candidate_generator.py`, `tests/test_query_tracer.py`, and `tests/test_answer_response_mapping.py`.

### Task 1: Runtime Error Contract

**Files:**
- Create: `rag_modules/runtime/error_models.py`
- Modify: `rag_modules/runtime/__init__.py`
- Test: `tests/test_runtime_error_models.py`

- [x] Write tests proving raw exception text is excluded and known subsystem errors map to stable `{code, detail}` values.
- [x] Run `python -m pytest tests/test_runtime_error_models.py -q` and verify it fails because the module does not exist.
- [x] Implement `RuntimeErrorDetail`, `runtime_error_detail`, `generation_error_detail`, `retrieval_error_detail`, `routing_error_detail`, and `answer_error_detail`.
- [x] Re-run `python -m pytest tests/test_runtime_error_models.py -q` and verify it passes.

### Task 2: Retrieval Degradation Contract

**Files:**
- Modify: `rag_modules/retrieval/candidate_generator.py`
- Modify: `rag_modules/runtime/route_models.py`
- Modify: `rag_modules/interfaces/api/answer_mappers.py`
- Test: `tests/test_retrieval_candidate_generator.py`
- Test: `tests/test_route_trace_recorder.py`
- Test: `tests/test_answer_response_mapping.py`

- [x] Change tests so degraded candidates expect `{"source": "...", "error": {"code": "...", "detail": "..."}}`.
- [x] Run the focused tests and verify failure against the existing `error_code`/`error_type` shape.
- [x] Update candidate generation, route degradation summaries, and API mappers to carry typed details.
- [x] Re-run focused retrieval and mapper tests.

### Task 3: Routing and Answer Workflow Errors

**Files:**
- Modify: `rag_modules/runtime/route_models.py`
- Modify: `rag_modules/runtime/trace_models.py`
- Modify: `rag_modules/routing/workflow_service.py`
- Modify: `rag_modules/app/services/answer_workflow.py`
- Modify: `rag_modules/app/services/answer_models.py`
- Test: `tests/test_answer_workflow.py`
- Test: `tests/test_query_tracer.py`

- [x] Change workflow tests so route/query errors are typed details and no raw secret appears in metadata or trace objects.
- [x] Run focused workflow/tracer tests and verify failure.
- [x] Update runtime snapshots and workflow producers to assign typed details directly.
- [x] Re-run focused workflow/tracer tests.

### Task 4: Generation Provider Classification

**Files:**
- Modify: `rag_modules/generation/clients/errors.py`
- Modify: `rag_modules/generation/execution/two_stage.py`
- Modify: `rag_modules/generation/execution/streaming.py`
- Modify: `rag_modules/generation/execution/engine.py`
- Modify: `rag_modules/runtime/generation_models.py`
- Test: `tests/test_generation_executor.py`
- Test: `tests/test_query_tracer.py`

- [x] Add tests for provider timeout, invalid response, latency budget, and generic provider error classifications.
- [x] Verify the tests fail where classification still depends on `str(exc)` or lacks typed details.
- [x] Implement classifier-based trace error details and update fallback reason assignment to use safe detail values.
- [x] Re-run generation and tracer tests.

### Task 5: API DTO Contract and Verification

**Files:**
- Modify: `rag_modules/interfaces/api/answer_debug_models.py`
- Modify: `rag_modules/interfaces/api/answer_public_models.py`
- Modify: `rag_modules/interfaces/api/answer_mappers.py`
- Test: `tests/test_answer_response_mapping.py`
- Test: `tests/test_api_app.py`

- [x] Update API tests so summary, route trace, graph trace, trace event, and degraded candidates expose typed error objects.
- [x] Run focused API/mapping tests and verify failure.
- [x] Update Pydantic DTOs to validate typed error objects with `code` and `detail`.
- [x] Run `python -m pytest tests/test_answer_workflow.py tests/test_answer_response_mapping.py tests/test_retrieval_candidate_generator.py tests/test_query_tracer.py tests/test_api_app.py -q`.
- [x] Run `python -m ruff check rag_modules tests/test_answer_workflow.py tests/test_answer_response_mapping.py tests/test_retrieval_candidate_generator.py tests/test_query_tracer.py tests/test_api_app.py tests/test_runtime_error_models.py`.
