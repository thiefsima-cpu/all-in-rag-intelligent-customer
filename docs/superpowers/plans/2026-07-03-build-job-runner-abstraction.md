# Build Job Runner Abstraction Implementation Plan

Status: completed

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move build-job submission, cancellation, retry, progress events, and executor backend ownership out of `GraphRAGBuildApiService` into a real `BuildJobRunner` boundary.

**Architecture:** `GraphRAGBuildApiService` becomes a thin API service over a runner plus artifact registry. `InProcessBuildJobRunner` owns durable job creation, retry creation, cancellation controls, future tracking, executor lifecycle, and dispatches `BuildJobTask` instances that update repository state and release build-flight locks. The repository adds first-class `cancel_requested`, `cancelled`, and `retry_of_job_id` state so cancel/retry behavior is durable and observable.

**Tech Stack:** Python 3.11, FastAPI, Pydantic v2, `concurrent.futures.ThreadPoolExecutor`, existing `RequestControl`, existing directory-backed build-job repository.

---

### Task 1: Add Durable Cancel And Retry Job State

**Files:**
- Modify: `rag_modules/interfaces/api/build_jobs/models.py`
- Modify: `rag_modules/interfaces/api/build_jobs/record_store.py`
- Modify: `rag_modules/interfaces/api/build_jobs/recovery_retention.py`
- Modify: `rag_modules/interfaces/api/build_jobs/repository.py`
- Modify: `rag_modules/interfaces/api/build_jobs/registry.py`
- Modify: `rag_modules/interfaces/api/build_models.py`
- Test: `tests/test_build_job_repository_records.py`

- [ ] **Step 1: Write failing repository tests**

Add tests that create a job with `retry_of_job_id`, mark a running job `cancel_requested`, mark it `cancelled`, and assert `cancel_requested` remains active while `cancelled` is terminal.

- [ ] **Step 2: Run tests to verify RED**

Run: `python -m pytest tests/test_build_job_repository_records.py::BuildJobRepositoryRecordTests::test_repository_persists_retry_parent_and_cancel_states -q`

Expected: FAIL because repository methods and status values do not exist yet.

- [ ] **Step 3: Implement minimal repository state support**

Add `retry_of_job_id` to `BuildJobRecord`, add safe cancelled logs, add repository/registry methods `mark_cancel_requested()` and `mark_cancelled()`, accept `retry_of_job_id` in `create_or_active()`, include `cancel_requested` in active statuses, and include `cancelled` in public `BuildJobStatus`.

- [ ] **Step 4: Run tests to verify GREEN**

Run: `python -m pytest tests/test_build_job_repository_records.py::BuildJobRepositoryRecordTests::test_repository_persists_retry_parent_and_cancel_states -q`

Expected: PASS.

### Task 2: Extract BuildJobRunner And BuildJobTask

**Files:**
- Create: `rag_modules/interfaces/api/build_jobs/runner.py`
- Modify: `rag_modules/interfaces/api/build_jobs/__init__.py`
- Modify: `rag_modules/interfaces/api/build_job_store.py`
- Test: `tests/test_build_job_runner.py`

- [ ] **Step 1: Write failing runner tests**

Add tests that instantiate `InProcessBuildJobRunner` with fake runtime hooks and assert submitted jobs complete, progress logs are sanitized, queued cancellation releases the build lock, running cancellation becomes `cancelled`, and retry creates a new job with `retry_of_job_id`.

- [ ] **Step 2: Run tests to verify RED**

Run: `python -m pytest tests/test_build_job_runner.py -q`

Expected: FAIL because `rag_modules.interfaces.api.build_jobs.runner` does not exist.

- [ ] **Step 3: Implement minimal runner and task**

Create `BuildJobRunRequest`, `BuildJobRuntimeHooks`, `BuildJobRunner` protocol, `BuildJobTask`, and `InProcessBuildJobRunner`. The runner owns `ThreadPoolExecutor`, active future handles, `RequestControl(deadline=float("inf"))`, `submit()`, `cancel()`, `retry()`, `list_page()`, `get()`, `corruption_summary()`, and `shutdown()`. The task owns running/succeeded/failed/cancelled transitions, progress formatting, failure snapshots, and build-lock release.

- [ ] **Step 4: Run tests to verify GREEN**

Run: `python -m pytest tests/test_build_job_runner.py -q`

Expected: PASS.

### Task 3: Slim GraphRAGBuildApiService Over The Runner

**Files:**
- Modify: `rag_modules/interfaces/api/services/build.py`
- Test: `tests/test_api_app.py`
- Test: `tests/test_build_job_persistence.py`

- [ ] **Step 1: Write failing service boundary tests**

Add tests that assert build submission still succeeds through the API service, `GraphRAGBuildApiService` no longer exposes executor fields, and diagnostics/list/get delegate through the runner.

- [ ] **Step 2: Run tests to verify RED**

Run: `python -m pytest tests/test_api_app.py::ApiAppTests::test_build_flow_uses_build_api_surface tests/test_build_job_persistence.py::BuildJobPersistenceTests::test_completed_job_is_visible_after_service_restart -q`

Expected: existing behavior passes before the boundary assertion is added; after adding the assertion, FAIL until executor fields are removed.

- [ ] **Step 3: Refactor service**

Remove `_BUILD_JOB_EXECUTOR_MAX_WORKERS`, `_build_executor`, `_build_executor_lock`, `_resolve_build_executor()`, `_run_build_job()`, progress callbacks, and mark helpers from `GraphRAGBuildApiService`. Construct `InProcessBuildJobRunner` with repository settings and runtime hooks. Delegate submit/list/get/cancel/retry/corruption/shutdown to the runner.

- [ ] **Step 4: Run tests to verify GREEN**

Run: `python -m pytest tests/test_api_app.py::ApiAppTests::test_build_flow_uses_build_api_surface tests/test_build_job_persistence.py::BuildJobPersistenceTests::test_completed_job_is_visible_after_service_restart -q`

Expected: PASS.

### Task 4: Add Build Runner Configuration

**Files:**
- Modify: `rag_modules/configuration/model_sections/api.py`
- Modify: `rag_modules/configuration/env_specs/api.py`
- Modify: `.env.example`
- Test: `tests/test_configuration_defaults.py`
- Test: `tests/test_configuration_section_loaders.py`

- [ ] **Step 1: Write failing configuration tests**

Assert default `api.build_job_runner_backend == "in_process"` and `api.build_job_runner_max_workers == 1`, and assert environment overrides load from `API_BUILD_JOB_RUNNER_BACKEND` and `API_BUILD_JOB_RUNNER_MAX_WORKERS`.

- [ ] **Step 2: Run tests to verify RED**

Run: `python -m pytest tests/test_configuration_defaults.py::ConfigurationDefaultTests::test_default_build_job_history_limits_are_bounded tests/test_configuration_section_loaders.py::ConfigurationSectionLoaderTests::test_api_settings_respect_environment_overrides -q`

Expected: FAIL because the new fields do not exist.

- [ ] **Step 3: Implement configuration**

Add the two fields to `ApiSettings`, environment specs, and `.env.example`. The runner factory rejects any backend except `"in_process"` with an explicit configuration error path.

- [ ] **Step 4: Run tests to verify GREEN**

Run: `python -m pytest tests/test_configuration_defaults.py::ConfigurationDefaultTests::test_default_build_job_history_limits_are_bounded tests/test_configuration_section_loaders.py::ConfigurationSectionLoaderTests::test_api_settings_respect_environment_overrides -q`

Expected: PASS.

### Task 5: Add Public Cancel And Retry Routes

**Files:**
- Modify: `rag_modules/interfaces/api/routes.py`
- Modify: `rag_modules/interfaces/api/services/errors.py`
- Modify: `rag_modules/interfaces/api/error_handlers.py`
- Test: `tests/test_api_app.py`

- [ ] **Step 1: Write failing API tests**

Add tests for `POST /v1/jobs/{job_id}/cancel` on a running build, `POST /v1/jobs/{job_id}/retry` after a failed job, rejection of retry for a running job, and OpenAPI paths for both routes.

- [ ] **Step 2: Run tests to verify RED**

Run: `python -m pytest tests/test_api_app.py::ApiAppTests::test_build_job_cancel_route_cancels_running_job tests/test_api_app.py::ApiAppTests::test_build_job_retry_route_queues_new_job_from_failed_job -q`

Expected: FAIL with 404 because routes do not exist.

- [ ] **Step 3: Implement routes and service methods**

Add `cancel_build_job(job_id)` and `retry_build_job(job_id, request_id)` on the service, delegate to runner, and register POST routes. Retry is valid only from `failed` or `cancelled`; cancel is valid for `queued`, `running`, and `cancel_requested`.

- [ ] **Step 4: Run tests to verify GREEN**

Run: `python -m pytest tests/test_api_app.py::ApiAppTests::test_build_job_cancel_route_cancels_running_job tests/test_api_app.py::ApiAppTests::test_build_job_retry_route_queues_new_job_from_failed_job -q`

Expected: PASS.

### Task 6: Update Architecture Docs And Run Focused Verification

**Files:**
- Modify: `docs/architecture.md`
- Modify: `README.md`
- Test: `tests/test_module_boundary_facades.py`
- Test: `tests/test_api_app.py`
- Test: `tests/test_build_job_persistence.py`
- Test: `tests/test_build_job_repository_records.py`
- Test: `tests/test_configuration_defaults.py`
- Test: `tests/test_configuration_section_loaders.py`

- [ ] **Step 1: Update docs**

Document `BuildJobRunner`, `InProcessBuildJobRunner`, cancel/retry routes, config fields, and the revised state machine.

- [ ] **Step 2: Run focused verification**

Run: `python -m pytest tests/test_build_job_runner.py tests/test_build_job_persistence.py tests/test_build_job_repository_records.py tests/test_api_app.py::ApiAppTests::test_build_flow_uses_build_api_surface tests/test_api_app.py::ApiAppTests::test_build_job_cancel_route_cancels_running_job tests/test_api_app.py::ApiAppTests::test_build_job_retry_route_queues_new_job_from_failed_job tests/test_configuration_defaults.py tests/test_configuration_section_loaders.py tests/test_module_boundary_facades.py -q`

Expected: PASS.

- [ ] **Step 3: Run formatting/lint gate**

Run: `pre-commit run --all-files`

Expected: PASS, or only automatic formatting changes that are reviewed and included.

