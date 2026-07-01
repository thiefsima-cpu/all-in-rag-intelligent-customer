# Idempotent Docker Bootstrap Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development
> (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the Docker API profile import missing graph data and prepare reusable knowledge-base
artifacts before starting the serving API.

**Architecture:** A one-shot Python bootstrap client coordinates existing boundaries: the Neo4j
CSV importer and the build API. Docker Compose supplies readiness ordering and keeps the serving
API blocked until bootstrap succeeds.

**Tech Stack:** Python 3.11, requests, Neo4j driver, FastAPI build jobs, Docker Compose, unittest.

---

### Task 1: Make graph import conditional

**Files:**
- Modify: `scripts/import_neo4j.py`
- Create: `tests/test_import_neo4j.py`

- [x] **Step 1: Write failing tests** for skipping when a `Recipe` node exists and importing when
  the graph is empty using a fake Neo4j driver/session.
- [x] **Step 2: Run `python -m pytest tests/test_import_neo4j.py -q`** and verify failures are caused
  by the missing conditional import API.
- [x] **Step 3: Add `import_graph(config, only_if_empty=False, driver_factory=...) -> bool`** and an
  `--if-empty` CLI flag while preserving the current import behavior by default.
- [x] **Step 4: Re-run the focused test** and verify it passes.

### Task 2: Add the runtime bootstrap client

**Files:**
- Create: `scripts/bootstrap_runtime.py`
- Create: `tests/test_bootstrap_runtime.py`

- [x] **Step 1: Write failing tests** for disabled bootstrap, normal build, forced rebuild, active
  job conflict reuse, failed job propagation, and polling timeout.
- [x] **Step 2: Run `python -m pytest tests/test_bootstrap_runtime.py -q`** and verify the module is
  missing.
- [x] **Step 3: Implement typed environment settings, conditional graph import, build submission,
  conflict recovery, polling, and a nonzero CLI exit on failure.**
- [x] **Step 4: Re-run the focused test** and verify it passes.

### Task 3: Wire Docker startup ordering

**Files:**
- Modify: `Dockerfile.api`
- Modify: `docker-compose.yml`
- Modify: `.env.example`
- Modify: `tests/test_docker_api_build_context.py`

- [x] **Step 1: Extend Compose tests** to require Neo4j/Milvus/build API health checks, the one-shot
  bootstrap service, shared data/config, bootstrap environment switches, and serving dependency on
  successful bootstrap.
- [x] **Step 2: Run the Compose test** and verify it fails against the current configuration.
- [x] **Step 3: Copy `cypher/` into the API image and add health checks plus bootstrap ordering to
  Compose. Set `API_AUTO_INITIALIZE_SERVING=true` for the serving container.**
- [x] **Step 4: Add documented defaults for `AUTO_BOOTSTRAP`, `FORCE_REBUILD`, and bootstrap timing
  settings to `.env.example`.**
- [x] **Step 5: Re-run the Compose test** and verify it passes.

### Task 4: Document and verify the workflow

**Files:**
- Modify: `README.md`

- [x] **Step 1: Replace the manual first-run sequence** with the one-command local path and retain
  manual build/rebuild commands for operations.
- [x] **Step 2: Run focused tests:**
  `python -m pytest tests/test_import_neo4j.py tests/test_bootstrap_runtime.py tests/test_docker_api_build_context.py -q`.
- [x] **Step 3: Run Ruff:**
  `python -m ruff check scripts/import_neo4j.py scripts/bootstrap_runtime.py tests/test_import_neo4j.py tests/test_bootstrap_runtime.py tests/test_docker_api_build_context.py`.
- [x] **Step 4: Run `docker compose --profile api config --quiet`** to validate the final Compose
  model, or report Docker access limitations explicitly.
