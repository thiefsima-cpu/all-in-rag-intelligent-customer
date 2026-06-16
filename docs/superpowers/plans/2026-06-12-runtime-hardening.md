# Runtime Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make process behavior, probes, dependencies, and traces safe for production operation.

**Architecture:** Keep operational behavior at the entrypoint and API boundaries. Add one reusable console helper, one trace sanitizer applied before sinks, and repository scripts that enforce a local virtual environment.

**Tech Stack:** Python 3.11, FastAPI, Pydantic, unittest/pytest, pip-tools, PowerShell.

---

### Task 1: Entrypoint Encoding And Exit Codes

**Files:**
- Create: `rag_modules/interfaces/console_runtime.py`
- Modify: `main.py`
- Modify: `main_build_service.py`
- Modify: `main_build_kb.py`
- Modify: `main_qa.py`
- Test: `tests/test_entrypoints.py`

- [ ] Write tests asserting UTF-8 reconfiguration and exit code `1` on startup exceptions.
- [ ] Run `python -m pytest tests/test_entrypoints.py -q` and confirm failure.
- [ ] Add `configure_utf8_stdio()` and integer-returning entrypoints.
- [ ] Raise `SystemExit(main())` from each script.
- [ ] Re-run the focused tests and confirm success.

### Task 2: Liveness And Readiness Probes

**Files:**
- Modify: `rag_modules/interfaces/api/routes.py`
- Modify: `rag_modules/interfaces/api/security.py`
- Modify: `rag_modules/interfaces/api/service.py`
- Modify: `tests/test_api_app.py`

- [ ] Add failing tests for public `/health/live` and `/health/ready`.
- [ ] Verify unready serving and build runtimes return `503` from readiness.
- [ ] Add service readiness payloads and explicit JSON status responses.
- [ ] Keep `/health` as the compatibility liveness endpoint.
- [ ] Re-run `python -m pytest tests/test_api_app.py -q`.

### Task 3: Trace Privacy Boundary

**Files:**
- Create: `rag_modules/trace_privacy.py`
- Modify: `rag_modules/configuration/models.py`
- Modify: `rag_modules/configuration/section_loaders.py`
- Modify: `rag_modules/tracing.py`
- Modify: `.env.example`
- Modify: `docs/observability.md`
- Modify: `tests/test_query_tracer.py`
- Modify: `tests/test_configuration_section_loaders.py`

- [ ] Add failing tests proving raw content and credentials never reach a sink.
- [ ] Add configuration for a trace fingerprint salt.
- [ ] Implement recursive key-aware sanitization with salted SHA-256 fingerprints.
- [ ] Sanitize the complete `QueryTraceEvent` before sink writes and returns.
- [ ] Document the non-reversible trace contract and re-run focused tests.

### Task 4: Dependency Isolation

**Files:**
- Create: `scripts/bootstrap_env.ps1`
- Create: `scripts/verify_environment.py`
- Create: `tests/test_dependency_isolation.py`
- Modify: `requirements.in`
- Modify: `requirements-dev.in`
- Modify: `requirements.txt`
- Modify: `requirements-dev.txt`
- Modify: `docs/dependency_management.md`
- Modify: `.gitignore`

- [ ] Add failing tests for global-interpreter rejection and lock separation.
- [ ] Pin a compatible packaging toolchain and keep test/build tools out of the runtime input.
- [ ] Add idempotent `.venv` bootstrap and verification scripts.
- [ ] Regenerate both locks with Python 3.11.
- [ ] Create `.venv`, install the development lock, and run `.venv\Scripts\python -m pip check`.

### Task 5: Verification

**Files:**
- Modify only files required by failures found during verification.

- [ ] Run all focused tests.
- [ ] Run `python scripts/check_encoding.py`.
- [ ] Run `.venv\Scripts\python scripts/verify_environment.py`.
- [ ] Run `.venv\Scripts\python -m pytest -q`.
- [ ] Reproduce startup failure and confirm a non-zero process exit.
