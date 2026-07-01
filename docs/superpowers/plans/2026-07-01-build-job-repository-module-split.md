# Build Job Repository Module Split Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split the directory-backed build-job repository into focused record store, idempotency index, and recovery/retention modules without changing public behavior.

**Architecture:** Keep `rag_modules/interfaces/api/build_jobs/repository.py` as the public facade that owns locking and API-level state transitions. Move JSON record IO/validation into `record_store.py`, idempotency key validation/index repair into `idempotency_index.py`, and legacy import, interrupted-job recovery, retention, and metadata handling into `recovery_retention.py`.

**Tech Stack:** Python 3.11, existing dataclass models, existing `write_json_atomic`, pytest/unittest, local JSON files.

---

## File Structure

- Modify: `rag_modules/interfaces/api/build_jobs/repository.py`
  Keep `BuildJobRepository`, cursor pagination, locking, and public methods; delegate storage concerns to focused collaborators.
- Create: `rag_modules/interfaces/api/build_jobs/record_store.py`
  Own job file paths, job load/write/replace, job validation, and record corruption warnings.
- Create: `rag_modules/interfaces/api/build_jobs/idempotency_index.py`
  Own idempotency key validation, hashing, index file load/write/remove/scan, and repair from job records.
- Create: `rag_modules/interfaces/api/build_jobs/recovery_retention.py`
  Own repository metadata, legacy JSON import, active/interrupted job recovery, and terminal-job retention pruning.
- Delete: `tests/test_build_job_repository.py`
  Replace the large mixed-topic test module with topic-focused files.
- Create: `tests/test_build_job_repository_records.py`
  Cover job record validation, corruption summaries, pagination, and write behavior.
- Create: `tests/test_build_job_repository_idempotency.py`
  Cover idempotency replay, conflicts, index repair, and retention cleanup of idempotency files.
- Create: `tests/test_build_job_repository_recovery_retention.py`
  Cover legacy import, invalid legacy/metadata warnings, retention, and interrupted recovery behavior.

## Task 1: Extract Record Store

**Files:**
- Create: `rag_modules/interfaces/api/build_jobs/record_store.py`
- Modify: `rag_modules/interfaces/api/build_jobs/repository.py`

- [ ] **Step 1: Run the current focused repository tests**

Run:

```powershell
python -m pytest tests/test_build_job_repository.py -q
```

Expected: PASS before refactoring.

- [ ] **Step 2: Move record IO and validation**

Create `BuildJobRecordStore` with `job_path()`, `load()`, `load_all()`, `require()`, `write()`, `replace()`, and `is_valid_job_record()` methods. Inject a `warn(code, component, identifier)` callback so warning behavior stays owned by the facade.

- [ ] **Step 3: Delegate repository record methods**

Update `BuildJobRepository` to instantiate `BuildJobRecordStore` and replace direct calls to `_load_job_unlocked`, `_load_jobs_unlocked`, `_write_job_unlocked`, `_replace_jobs_unlocked`, `_require_job_unlocked`, and `_is_valid_job_record` with collaborator methods.

- [ ] **Step 4: Re-run repository tests**

Run:

```powershell
python -m pytest tests/test_build_job_repository.py -q
```

Expected: PASS.

## Task 2: Extract Idempotency Index

**Files:**
- Create: `rag_modules/interfaces/api/build_jobs/idempotency_index.py`
- Modify: `rag_modules/interfaces/api/build_jobs/repository.py`

- [ ] **Step 1: Move key validation and index IO**

Create `BuildJobIdempotencyIndex` with `validate_key()`, `key_hash()`, `load()`, `write()`, `remove_for_job()`, `scan()`, and `repair_from_jobs()` methods. Preserve the `BuildJobIdempotencyConflictError` public exception in `repository.py`.

- [ ] **Step 2: Delegate repository idempotency behavior**

Update `BuildJobRepository.validate_idempotency_key()` and `BuildJobRepository.idempotency_key_hash()` to call `BuildJobIdempotencyIndex` static methods. Update `create_or_active()` and corruption scanning to use the index collaborator.

- [ ] **Step 3: Re-run repository tests**

Run:

```powershell
python -m pytest tests/test_build_job_repository.py -q
```

Expected: PASS.

## Task 3: Extract Recovery And Retention

**Files:**
- Create: `rag_modules/interfaces/api/build_jobs/recovery_retention.py`
- Modify: `rag_modules/interfaces/api/build_jobs/repository.py`

- [ ] **Step 1: Move metadata, legacy import, retention, and recovery**

Create `BuildJobRepositoryRecoveryRetention` with `apply_retention()`, `active()`, `recover_interrupted()`, `mark_interrupted()`, `import_legacy_store_once()`, `load_metadata()`, `write_metadata()`, and `scan_for_corruption()` methods.

- [ ] **Step 2: Delegate repository lifecycle behavior**

Update `BuildJobRepository.__init__()`, `create_or_active()`, `mark_succeeded()`, `mark_failed()`, and `corruption_summary()` to call the lifecycle collaborator.

- [ ] **Step 3: Re-run repository and persistence tests**

Run:

```powershell
python -m pytest tests/test_build_job_repository.py tests/test_build_job_persistence.py -q
```

Expected: PASS.

## Task 4: Split Topic Tests

**Files:**
- Delete: `tests/test_build_job_repository.py`
- Create: `tests/test_build_job_repository_records.py`
- Create: `tests/test_build_job_repository_idempotency.py`
- Create: `tests/test_build_job_repository_recovery_retention.py`

- [ ] **Step 1: Move record-focused tests**

Move corruption, pagination, mismatched record ID, duplicate warning, and write behavior tests into `tests/test_build_job_repository_records.py`.

- [ ] **Step 2: Move idempotency-focused tests**

Move same-key replay, cross-type conflict, missing/corrupt index repair, and idempotency cleanup assertions into `tests/test_build_job_repository_idempotency.py`.

- [ ] **Step 3: Move recovery/retention-focused tests**

Move retention, legacy import, invalid metadata/legacy, and interrupted recovery coverage into `tests/test_build_job_repository_recovery_retention.py`.

- [ ] **Step 4: Run all build-job tests**

Run:

```powershell
python -m pytest tests/test_build_job_repository_records.py tests/test_build_job_repository_idempotency.py tests/test_build_job_repository_recovery_retention.py tests/test_build_job_persistence.py -q
```

Expected: PASS.

## Task 5: Final Verification

**Files:**
- Verify changed files only.

- [ ] **Step 1: Run API boundary checks touched by build-job facades**

Run:

```powershell
python -m pytest tests/test_module_boundary_facades.py tests/test_public_api_manifest.py -q
```

Expected: PASS.

- [ ] **Step 2: Run Ruff on changed Python files**

Run:

```powershell
python -m ruff check rag_modules/interfaces/api/build_jobs tests/test_build_job_repository_records.py tests/test_build_job_repository_idempotency.py tests/test_build_job_repository_recovery_retention.py
```

Expected: PASS.
