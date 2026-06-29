# Build Job Repository Reliability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace whole-file build-job persistence with a reliable repository that supports idempotent submissions, paginated job history, retention, legacy migration, and safe corruption warnings.

**Architecture:** Add a directory-backed `BuildJobRepository` under `rag_modules/interfaces/api/build_jobs/` and keep existing build API orchestration in `GraphRAGBuildApiService`. Per-job JSON files become the durable unit, idempotency keys are stored only as SHA-256 hashes, and FastAPI routes translate headers/query parameters into service calls.

**Tech Stack:** Python 3.11, FastAPI, Pydantic v2, pytest/unittest, local JSON files with existing `write_json_atomic`, existing cross-process file locks.

---

## File Structure

- Create: `rag_modules/interfaces/api/build_jobs/repository.py`
  Owns directory-backed persistence, legacy migration, pagination cursors, idempotency indexes, retention, and corruption summaries.
- Modify: `rag_modules/interfaces/api/build_jobs/models.py`
  Adds repository settings/page/warning dataclasses and optional internal `idempotency_key_hash` on `BuildJobRecord`.
- Modify: `rag_modules/interfaces/api/build_jobs/file_store.py`
  Keeps `FileBuildJobStore` facade and lock paths; delegates durable behavior to the repository where useful.
- Modify: `rag_modules/interfaces/api/build_jobs/registry.py`
  Reworks `PersistentBuildJobRegistry` as a thin state-transition facade over `BuildJobRepository`.
- Modify: `rag_modules/interfaces/api/build_jobs/__init__.py`
  Exports new repository types.
- Modify: `rag_modules/interfaces/api/build_job_store.py`
  Re-exports the same public names plus `BuildJobRepository`.
- Modify: `rag_modules/interfaces/api/services/errors.py`
  Adds `InvalidApiRequestError` for invalid idempotency keys and pagination cursors.
- Modify: `rag_modules/interfaces/api/error_handlers.py`
  Maps `InvalidApiRequestError` to `400 INVALID_REQUEST` and includes safe `job_type` details for build-job conflicts when present.
- Modify: `rag_modules/interfaces/api/services/build.py`
  Accepts `idempotency_key`, delegates list pagination, and injects repository corruption summaries into build diagnostics.
- Modify: `rag_modules/interfaces/api/routes.py`
  Reads `Idempotency-Key`, `limit`, and `cursor` on build job routes.
- Modify: `rag_modules/interfaces/api/build_models.py`
  Adds `next_cursor` to `BuildJobListResponseModel`.
- Modify: `rag_modules/interfaces/api/diagnostics_models.py`
  Adds `build_job_store` to startup diagnostics response models.
- Modify: `rag_modules/interfaces/api/response_builder.py`
  Builds paginated build-job list responses.
- Modify: `rag_modules/configuration/model_sections/api.py`
  Adds retention/list-limit settings and validates their relationship.
- Modify: `rag_modules/configuration/env_specs/api.py`
  Adds environment overrides for the new API settings.
- Modify: `.env.example`
  Documents safe defaults for new build-job settings.
- Modify: `README.md`
  Documents idempotency, pagination, retention, and safe corruption warnings.
- Create: `tests/test_build_job_repository.py`
  Focused repository tests that do not need FastAPI.
- Modify: `tests/test_build_job_persistence.py`
  Preserves restart/recovery coverage through the compatibility facade.
- Modify: `tests/test_api_app.py`
  Adds HTTP contract tests for idempotency, pagination, and diagnostics.
- Modify: `tests/test_configuration_section_loaders.py`
  Adds env override coverage.
- Modify: `tests/test_configuration_defaults.py`
  Adds defaults and validation coverage.
- Modify: `tests/test_module_boundary_facades.py`
  Ensures facade re-exports remain aligned.

## Task 1: Repository Foundation

**Files:**
- Create: `tests/test_build_job_repository.py`
- Create: `rag_modules/interfaces/api/build_jobs/repository.py`
- Modify: `rag_modules/interfaces/api/build_jobs/models.py`
- Modify: `rag_modules/interfaces/api/build_jobs/__init__.py`
- Modify: `rag_modules/interfaces/api/build_job_store.py`

- [ ] **Step 1: Write the failing repository storage test**

Add this new test file:

```python
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from rag_modules.interfaces.api.build_jobs import (
    BuildJobRepository,
    BuildJobRepositorySettings,
)


def _now() -> str:
    return "2026-06-29T00:00:00Z"


class BuildJobRepositoryTests(unittest.TestCase):
    def test_repository_writes_one_job_file_and_preserves_legacy_store(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            legacy_path = root / "build_jobs.json"
            legacy_path.write_text(
                json.dumps({"schema_version": "legacy", "jobs": []}),
                encoding="utf-8",
            )
            original_legacy_text = legacy_path.read_text(encoding="utf-8")
            repository = BuildJobRepository(
                str(legacy_path),
                now=_now,
                settings=BuildJobRepositorySettings(
                    retention_limit=100,
                    list_default_limit=50,
                    list_max_limit=100,
                ),
            )

            created, job, build_lock = repository.create_or_active(
                job_id="a" * 32,
                request_id="request-1",
                job_type="build",
                message="Knowledge base build job queued.",
                idempotency_key="",
            )
            try:
                repository.mark_running("a" * 32, message="Knowledge base build started.")
            finally:
                if build_lock is not None:
                    build_lock.release()

            job_path = root / "build_jobs.d" / "jobs" / f"{'a' * 32}.json"
            self.assertTrue(created)
            self.assertEqual(job["job_id"], "a" * 32)
            self.assertTrue(job_path.exists())
            self.assertEqual(legacy_path.read_text(encoding="utf-8"), original_legacy_text)
            stored_job = json.loads(job_path.read_text(encoding="utf-8"))
            self.assertEqual(stored_job["status"], "running")
            self.assertEqual(stored_job["message"], "Knowledge base build started.")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the test to verify it fails**

Run:

```powershell
python -m pytest tests/test_build_job_repository.py::BuildJobRepositoryTests::test_repository_writes_one_job_file_and_preserves_legacy_store -q
```

Expected: FAIL with an import error for `BuildJobRepository` or `BuildJobRepositorySettings`.

- [ ] **Step 3: Add repository settings and page/warning models**

In `rag_modules/interfaces/api/build_jobs/models.py`, add these dataclasses below `BuildJobRecord`:

```python
@dataclass(frozen=True, slots=True)
class BuildJobRepositorySettings:
    retention_limit: int = 100
    list_default_limit: int = 50
    list_max_limit: int = 100


@dataclass(frozen=True, slots=True)
class BuildJobListPage:
    jobs: list[dict]
    next_cursor: str = ""


@dataclass(frozen=True, slots=True)
class BuildJobCorruptionWarning:
    code: str
    component: str
    identifier: str
    detected_at: str

    def to_dict(self) -> dict:
        return {
            "code": self.code,
            "component": self.component,
            "identifier": self.identifier,
            "detected_at": self.detected_at,
        }
```

Update `BuildJobRecord` with the internal field and make sure `to_dict()` writes it only when present:

```python
    idempotency_key_hash: str = ""

    def to_dict(self) -> dict:
        payload = {
            "job_id": self.job_id,
            "request_id": self.request_id,
            "job_type": self.job_type,
            "status": self.status,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "message": self.message,
            "error": copy.deepcopy(self.error),
            "logs": [_safe_build_log(item) for item in self.logs],
            "result": copy.deepcopy(self.result),
        }
        if self.idempotency_key_hash:
            payload["idempotency_key_hash"] = self.idempotency_key_hash
        return payload
```

In `from_dict()`, read the optional hash:

```python
            idempotency_key_hash=str(payload.get("idempotency_key_hash") or ""),
```

Update `__all__` in `models.py`, `build_jobs/__init__.py`, and `build_job_store.py` to include `BuildJobRepositorySettings`, `BuildJobListPage`, and `BuildJobCorruptionWarning`.

- [ ] **Step 4: Implement the minimal repository**

Create `rag_modules/interfaces/api/build_jobs/repository.py` with this starting implementation:

```python
"""Directory-backed repository for asynchronous build-job state."""

from __future__ import annotations

import copy
import json
import os
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Mapping

from ....runtime.artifacts import write_json_atomic
from .locks import _InterprocessFileLock
from .models import (
    BUILD_JOB_STORE_SCHEMA_VERSION,
    BuildJobCorruptionWarning,
    BuildJobListPage,
    BuildJobRecord,
    BuildJobRepositorySettings,
)

BUILD_JOB_REPOSITORY_SCHEMA_VERSION = "graph-rag-build-job-repository-v1"


class BuildJobRepository:
    """Persist build jobs as independent JSON records."""

    def __init__(
        self,
        path: str,
        *,
        now,
        settings: BuildJobRepositorySettings | None = None,
        recover_interrupted: bool = True,
    ) -> None:
        self.path = str(path)
        self._now = now
        self.settings = settings or BuildJobRepositorySettings()
        self._lock = threading.RLock()
        self._store_lock_path = f"{self.path}.lock"
        self._build_lock_path = f"{self.path}.flight.lock"
        self.repository_dir = self._repository_dir_for_path(self.path)
        self.jobs_dir = os.path.join(self.repository_dir, "jobs")
        self.idempotency_dir = os.path.join(self.repository_dir, "idempotency")
        self.metadata_path = os.path.join(self.repository_dir, "metadata.json")
        self._warnings: list[BuildJobCorruptionWarning] = []
        self._ensure_directories()
        with self.locked():
            self._write_metadata_unlocked()
            if recover_interrupted and not self.build_lock_held():
                self._recover_interrupted_unlocked()

    @staticmethod
    def _repository_dir_for_path(path: str) -> str:
        parent = os.path.dirname(path) or "."
        stem, _ = os.path.splitext(os.path.basename(path))
        return os.path.join(parent, f"{stem}.d")

    def _ensure_directories(self) -> None:
        os.makedirs(self.jobs_dir, exist_ok=True)
        os.makedirs(self.idempotency_dir, exist_ok=True)

    @contextmanager
    def locked(self) -> Iterator[None]:
        with self._lock:
            with _InterprocessFileLock(self._store_lock_path):
                yield

    def try_acquire_build_lock(self) -> _InterprocessFileLock | None:
        build_lock = _InterprocessFileLock(self._build_lock_path, blocking=False)
        if build_lock.acquire():
            return build_lock
        return None

    def build_lock_held(self) -> bool:
        build_lock = self.try_acquire_build_lock()
        if build_lock is None:
            return True
        build_lock.release()
        return False

    def create_or_active(
        self,
        *,
        job_id: str,
        request_id: str,
        job_type: str,
        message: str,
        idempotency_key: str = "",
    ) -> tuple[bool, dict | None, _InterprocessFileLock | None]:
        del idempotency_key
        with self._lock:
            with self.locked():
                active_job = self._active_unlocked()
                if active_job is not None:
                    if self.build_lock_held():
                        return False, active_job.to_dict(), None
                    self._mark_interrupted_unlocked(active_job)
                build_lock = self.try_acquire_build_lock()
                if build_lock is None:
                    active_job = self._active_unlocked()
                    return False, active_job.to_dict() if active_job is not None else None, None
                job = BuildJobRecord(
                    job_id=job_id,
                    request_id=request_id,
                    job_type=job_type,
                    status="queued",
                    created_at=self._now(),
                    message=message,
                )
                self._write_job_unlocked(job)
                return True, job.to_dict(), build_lock

    def get(self, job_id: str) -> dict | None:
        with self._lock:
            with self.locked():
                job = self._load_job_unlocked(str(job_id))
                return job.to_dict() if job is not None else None

    def list_page(self, *, limit: int, cursor: str = "") -> BuildJobListPage:
        del cursor
        with self._lock:
            with self.locked():
                jobs = sorted(
                    self._load_jobs_unlocked(),
                    key=lambda item: (item.created_at, item.job_id),
                    reverse=True,
                )
                return BuildJobListPage(
                    jobs=[job.to_dict() for job in jobs[: int(limit)]],
                    next_cursor="",
                )

    def append_log(self, job_id: str, message: str) -> None:
        with self._lock:
            with self.locked():
                job = self._load_job_unlocked(job_id)
                if job is None:
                    return
                job.logs.append(str(message))
                from .models import BUILD_JOB_LOG_LIMIT

                if len(job.logs) > BUILD_JOB_LOG_LIMIT:
                    job.logs = job.logs[-BUILD_JOB_LOG_LIMIT:]
                self._write_job_unlocked(job)

    def mark_running(self, job_id: str, *, message: str) -> None:
        with self._lock:
            with self.locked():
                job = self._require_job_unlocked(job_id)
                job.status = "running"
                job.started_at = self._now()
                job.message = message
                self._write_job_unlocked(job)

    def mark_succeeded(self, job_id: str, *, result: dict) -> None:
        with self._lock:
            with self.locked():
                job = self._require_job_unlocked(job_id)
                job.status = "succeeded"
                job.finished_at = self._now()
                job.message = str(result.get("message", "Knowledge base build completed."))
                job.result = copy.deepcopy(result)
                self._write_job_unlocked(job)

    def mark_failed(self, job_id: str, *, result: dict) -> None:
        from .models import build_failure

        with self._lock:
            with self.locked():
                job = self._require_job_unlocked(job_id)
                job.status = "failed"
                job.finished_at = self._now()
                job.error = build_failure(job.request_id)
                job.message = "Knowledge base build failed."
                job.result = copy.deepcopy(result)
                self._write_job_unlocked(job)

    def corruption_summary(self) -> dict:
        warnings = [warning.to_dict() for warning in self._warnings]
        codes = sorted({warning["code"] for warning in warnings})
        return {"warning_count": len(warnings), "warning_codes": codes, "warnings": warnings}

    def _job_path(self, job_id: str) -> str:
        return os.path.join(self.jobs_dir, f"{job_id}.json")

    def _load_job_unlocked(self, job_id: str) -> BuildJobRecord | None:
        path = self._job_path(job_id)
        if not os.path.exists(path):
            return None
        try:
            with open(path, "r", encoding="utf-8") as file:
                payload = json.load(file)
            if not isinstance(payload, Mapping):
                self._record_warning_unlocked("BUILD_JOB_STORE_CORRUPT_RECORD", "job", job_id)
                return None
            job = BuildJobRecord.from_dict(payload)
            return job if job.job_id else None
        except (OSError, ValueError, TypeError):
            self._record_warning_unlocked("BUILD_JOB_STORE_CORRUPT_RECORD", "job", job_id)
            return None

    def _load_jobs_unlocked(self) -> list[BuildJobRecord]:
        if not os.path.isdir(self.jobs_dir):
            return []
        jobs: list[BuildJobRecord] = []
        for filename in os.listdir(self.jobs_dir):
            if not filename.endswith(".json"):
                continue
            job = self._load_job_unlocked(filename[:-5])
            if job is not None:
                jobs.append(job)
        return jobs

    def _require_job_unlocked(self, job_id: str) -> BuildJobRecord:
        job = self._load_job_unlocked(job_id)
        if job is None:
            raise KeyError(job_id)
        return job

    def _write_job_unlocked(self, job: BuildJobRecord) -> None:
        write_json_atomic(self._job_path(job.job_id), job.to_dict())

    def _active_unlocked(self) -> BuildJobRecord | None:
        for job in self._load_jobs_unlocked():
            if job.status in {"queued", "running"}:
                return job
        return None

    def _recover_interrupted_unlocked(self) -> None:
        for job in self._load_jobs_unlocked():
            if job.status in {"queued", "running"}:
                self._mark_interrupted_unlocked(job)

    def _mark_interrupted_unlocked(self, job: BuildJobRecord) -> None:
        from .models import build_failure

        job.status = "failed"
        job.finished_at = self._now()
        job.error = build_failure(job.request_id)
        job.message = "Knowledge base build interrupted by service restart."
        job.logs.append("Build interrupted by service restart.")
        self._write_job_unlocked(job)

    def _write_metadata_unlocked(self) -> None:
        write_json_atomic(
            self.metadata_path,
            {
                "schema_version": BUILD_JOB_REPOSITORY_SCHEMA_VERSION,
                "legacy_schema_version": BUILD_JOB_STORE_SCHEMA_VERSION,
                "legacy_path": self.path,
            },
        )

    def _record_warning_unlocked(self, code: str, component: str, identifier: str) -> None:
        warning = BuildJobCorruptionWarning(
            code=code,
            component=component,
            identifier=str(identifier)[:24],
            detected_at=self._now(),
        )
        if warning not in self._warnings:
            self._warnings.append(warning)


__all__ = ["BUILD_JOB_REPOSITORY_SCHEMA_VERSION", "BuildJobRepository"]
```

Export `BuildJobRepository` from `build_jobs/__init__.py` and `build_job_store.py`.

- [ ] **Step 5: Run the test to verify it passes**

Run:

```powershell
python -m pytest tests/test_build_job_repository.py::BuildJobRepositoryTests::test_repository_writes_one_job_file_and_preserves_legacy_store -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```powershell
git add tests/test_build_job_repository.py rag_modules/interfaces/api/build_jobs/models.py rag_modules/interfaces/api/build_jobs/repository.py rag_modules/interfaces/api/build_jobs/__init__.py rag_modules/interfaces/api/build_job_store.py
git commit -m "feat: add build job repository storage"
```

## Task 2: Compatibility Facade And Legacy Migration

**Files:**
- Modify: `tests/test_build_job_repository.py`
- Modify: `tests/test_build_job_persistence.py`
- Modify: `rag_modules/interfaces/api/build_jobs/file_store.py`
- Modify: `rag_modules/interfaces/api/build_jobs/registry.py`
- Modify: `rag_modules/interfaces/api/build_jobs/repository.py`

- [ ] **Step 1: Write failing tests for legacy migration and facade recovery**

Add these methods to `BuildJobRepositoryTests`:

```python
    def test_repository_imports_legacy_jobs_once_without_deleting_legacy_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            legacy_path = root / "build_jobs.json"
            legacy_payload = {
                "schema_version": "graph-rag-build-jobs-v2",
                "jobs": [
                    {
                        "job_id": "b" * 32,
                        "request_id": "legacy-request",
                        "job_type": "build",
                        "status": "succeeded",
                        "created_at": "2026-06-28T00:00:00Z",
                        "message": "Knowledge base build completed.",
                    }
                ],
            }
            legacy_path.write_text(json.dumps(legacy_payload), encoding="utf-8")

            first = BuildJobRepository(
                str(legacy_path),
                now=_now,
                settings=BuildJobRepositorySettings(),
            )
            second = BuildJobRepository(
                str(legacy_path),
                now=_now,
                settings=BuildJobRepositorySettings(),
            )

            self.assertEqual(first.get("b" * 32)["status"], "succeeded")
            self.assertEqual(second.get("b" * 32)["status"], "succeeded")
            self.assertTrue(legacy_path.exists())
            metadata = json.loads((root / "build_jobs.d" / "metadata.json").read_text())
            self.assertEqual(metadata["legacy_imports"][0]["path"], str(legacy_path))
            self.assertEqual(metadata["legacy_imports"][0]["status"], "imported")
```

Add this method to `BuildJobPersistenceTests`:

```python
    def test_file_store_facade_uses_repository_after_legacy_seed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = str(Path(temp_dir) / "build_jobs.json")
            store = FileBuildJobStore(path)
            store.save_all(
                [
                    {
                        "job_id": "c" * 32,
                        "request_id": "seed-request",
                        "job_type": "build",
                        "status": "succeeded",
                        "created_at": "2026-06-28T00:00:00Z",
                        "message": "Knowledge base build completed.",
                    }
                ]
            )

            loaded = FileBuildJobStore(path).load_all()

            self.assertEqual(len(loaded), 1)
            self.assertEqual(loaded[0]["job_id"], "c" * 32)
            self.assertTrue((Path(temp_dir) / "build_jobs.d" / "jobs" / f"{'c' * 32}.json").exists())
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```powershell
python -m pytest tests/test_build_job_repository.py::BuildJobRepositoryTests::test_repository_imports_legacy_jobs_once_without_deleting_legacy_file tests/test_build_job_persistence.py::BuildJobPersistenceTests::test_file_store_facade_uses_repository_after_legacy_seed -q
```

Expected: FAIL because legacy import markers and facade delegation are not implemented.

- [ ] **Step 3: Implement legacy migration in the repository**

Add these helper methods to `BuildJobRepository` and call `_import_legacy_store_once_unlocked()` inside `__init__` after `_ensure_directories()` and before recovery:

```python
    def _import_legacy_store_once_unlocked(self) -> None:
        metadata = self._load_metadata_unlocked()
        imports = list(metadata.get("legacy_imports") or [])
        for item in imports:
            if isinstance(item, Mapping) and item.get("path") == self.path:
                return
        if not os.path.exists(self.path):
            self._write_metadata_unlocked(legacy_imports=imports)
            return
        try:
            with open(self.path, "r", encoding="utf-8") as file:
                payload = json.load(file)
            jobs = payload.get("jobs") if isinstance(payload, Mapping) else None
            if not isinstance(jobs, list):
                self._record_warning_unlocked(
                    "BUILD_JOB_STORE_CORRUPT_LEGACY",
                    "legacy",
                    os.path.basename(self.path),
                )
                imports.append({"path": self.path, "status": "corrupt"})
                self._write_metadata_unlocked(legacy_imports=imports)
                return
            for item in jobs:
                if not isinstance(item, Mapping):
                    continue
                job = BuildJobRecord.from_dict(item)
                if job.job_id and not os.path.exists(self._job_path(job.job_id)):
                    self._write_job_unlocked(job)
            imports.append({"path": self.path, "status": "imported"})
            self._write_metadata_unlocked(legacy_imports=imports)
        except (OSError, ValueError, TypeError):
            self._record_warning_unlocked(
                "BUILD_JOB_STORE_CORRUPT_LEGACY",
                "legacy",
                os.path.basename(self.path),
            )
            imports.append({"path": self.path, "status": "corrupt"})
            self._write_metadata_unlocked(legacy_imports=imports)

    def _load_metadata_unlocked(self) -> dict[str, Any]:
        if not os.path.exists(self.metadata_path):
            return {}
        try:
            with open(self.metadata_path, "r", encoding="utf-8") as file:
                payload = json.load(file)
            return dict(payload) if isinstance(payload, Mapping) else {}
        except (OSError, ValueError, TypeError):
            self._record_warning_unlocked(
                "BUILD_JOB_STORE_CORRUPT_METADATA",
                "metadata",
                os.path.basename(self.metadata_path),
            )
            return {}

    def _write_metadata_unlocked(
        self,
        *,
        legacy_imports: list[Mapping[str, Any]] | None = None,
    ) -> None:
        write_json_atomic(
            self.metadata_path,
            {
                "schema_version": BUILD_JOB_REPOSITORY_SCHEMA_VERSION,
                "legacy_schema_version": BUILD_JOB_STORE_SCHEMA_VERSION,
                "legacy_path": self.path,
                "legacy_imports": [dict(item) for item in legacy_imports or []],
            },
        )
```

Adjust `__init__` so metadata is not overwritten before import:

```python
        with self.locked():
            self._import_legacy_store_once_unlocked()
            if recover_interrupted and not self.build_lock_held():
                self._recover_interrupted_unlocked()
```

- [ ] **Step 4: Delegate `FileBuildJobStore` to repository-compatible storage**

In `rag_modules/interfaces/api/build_jobs/file_store.py`, keep lock methods and change load/save behavior:

```python
    def load_all(self) -> list[dict[str, Any]]:
        repository = BuildJobRepository(
            self.path,
            now=lambda: "",
            settings=BuildJobRepositorySettings(),
            recover_interrupted=False,
        )
        page = repository.list_page(limit=repository.settings.list_max_limit, cursor="")
        return list(reversed(page.jobs))

    def save_all(self, jobs: list[Mapping[str, Any]]) -> None:
        with self.locked():
            self._save_all_unlocked(jobs)
            repository = BuildJobRepository(
                self.path,
                now=lambda: "",
                settings=BuildJobRepositorySettings(),
                recover_interrupted=False,
            )
            for payload in jobs:
                if not isinstance(payload, Mapping):
                    continue
                job = BuildJobRecord.from_dict(payload)
                if job.job_id:
                    repository._write_job_unlocked(job)
```

Import the new names:

```python
from .models import BUILD_JOB_STORE_SCHEMA_VERSION, BuildJobRecord, BuildJobRepositorySettings
from .repository import BuildJobRepository
```

- [ ] **Step 5: Rework `PersistentBuildJobRegistry` to delegate to repository**

In `rag_modules/interfaces/api/build_jobs/registry.py`, keep the public class name but replace internal all-job caching with repository calls:

```python
class PersistentBuildJobRegistry:
    """Own build-job state transitions through a durable repository."""

    def __init__(
        self,
        store: FileBuildJobStore,
        *,
        now,
        recover_interrupted: bool = True,
        settings: BuildJobRepositorySettings | None = None,
    ) -> None:
        self.store = store
        self.repository = BuildJobRepository(
            store.path,
            now=now,
            settings=settings or BuildJobRepositorySettings(),
            recover_interrupted=recover_interrupted,
        )

    def active(self) -> dict | None:
        return self.repository.active()

    def create_or_active(
        self,
        *,
        job_id: str,
        request_id: str,
        job_type: str,
        message: str,
        idempotency_key: str = "",
    ) -> tuple[bool, dict | None, _InterprocessFileLock | None]:
        return self.repository.create_or_active(
            job_id=job_id,
            request_id=request_id,
            job_type=job_type,
            message=message,
            idempotency_key=idempotency_key,
        )

    def list_page(self, *, limit: int, cursor: str = "") -> BuildJobListPage:
        return self.repository.list_page(limit=limit, cursor=cursor)

    def list(self) -> list[dict]:
        page = self.repository.list_page(
            limit=self.repository.settings.list_max_limit,
            cursor="",
        )
        return page.jobs

    def get(self, job_id: str) -> dict | None:
        return self.repository.get(str(job_id))

    def append_log(self, job_id: str, message: str) -> None:
        self.repository.append_log(job_id, message)

    def mark_running(self, job_id: str, *, message: str) -> None:
        self.repository.mark_running(job_id, message=message)

    def mark_succeeded(self, job_id: str, *, result: dict) -> None:
        self.repository.mark_succeeded(job_id, result=result)

    def mark_failed(self, job_id: str, *, result: dict) -> None:
        self.repository.mark_failed(job_id, result=result)

    def corruption_summary(self) -> dict:
        return self.repository.corruption_summary()
```

Add any missing imports for `BuildJobListPage` and `BuildJobRepositorySettings`.

- [ ] **Step 6: Run focused persistence tests**

Run:

```powershell
python -m pytest tests/test_build_job_repository.py tests/test_build_job_persistence.py -q
```

Expected: PASS for repository tests and existing persistence/recovery tests.

- [ ] **Step 7: Commit**

```powershell
git add tests/test_build_job_repository.py tests/test_build_job_persistence.py rag_modules/interfaces/api/build_jobs/file_store.py rag_modules/interfaces/api/build_jobs/registry.py rag_modules/interfaces/api/build_jobs/repository.py
git commit -m "feat: migrate build jobs to repository facade"
```

## Task 3: Idempotency Key Contract

**Files:**
- Modify: `tests/test_build_job_repository.py`
- Modify: `tests/test_api_app.py`
- Modify: `rag_modules/interfaces/api/build_jobs/repository.py`
- Modify: `rag_modules/interfaces/api/services/errors.py`
- Modify: `rag_modules/interfaces/api/error_handlers.py`
- Modify: `rag_modules/interfaces/api/services/build.py`
- Modify: `rag_modules/interfaces/api/routes.py`

- [ ] **Step 1: Write failing repository idempotency tests**

Add these tests to `BuildJobRepositoryTests`:

```python
    def test_same_idempotency_key_and_job_type_returns_original_job(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repository = BuildJobRepository(
                str(Path(temp_dir) / "build_jobs.json"),
                now=_now,
                settings=BuildJobRepositorySettings(),
            )
            created, first_job, first_lock = repository.create_or_active(
                job_id="d" * 32,
                request_id="request-1",
                job_type="build",
                message="Knowledge base build job queued.",
                idempotency_key="client-key-1",
            )
            if first_lock is not None:
                first_lock.release()

            repeated, repeated_job, repeated_lock = repository.create_or_active(
                job_id="e" * 32,
                request_id="request-2",
                job_type="build",
                message="Knowledge base build job queued.",
                idempotency_key="client-key-1",
            )

            self.assertTrue(created)
            self.assertFalse(repeated)
            self.assertIsNone(repeated_lock)
            self.assertEqual(repeated_job["job_id"], first_job["job_id"])
            stored_text = "".join(
                path.read_text(encoding="utf-8")
                for path in (Path(temp_dir) / "build_jobs.d").rglob("*.json")
            )
            self.assertNotIn("client-key-1", stored_text)

    def test_same_idempotency_key_and_different_job_type_conflicts(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repository = BuildJobRepository(
                str(Path(temp_dir) / "build_jobs.json"),
                now=_now,
                settings=BuildJobRepositorySettings(),
            )
            created, first_job, first_lock = repository.create_or_active(
                job_id="f" * 32,
                request_id="request-1",
                job_type="build",
                message="Knowledge base build job queued.",
                idempotency_key="client-key-2",
            )
            if first_lock is not None:
                first_lock.release()

            with self.assertRaises(ValueError) as caught:
                repository.create_or_active(
                    job_id="1" * 32,
                    request_id="request-2",
                    job_type="rebuild",
                    message="Knowledge base rebuild job queued.",
                    idempotency_key="client-key-2",
                )

            self.assertTrue(created)
            self.assertEqual(first_job["job_type"], "build")
            self.assertIn("idempotency key already used for build", str(caught.exception))
```

- [ ] **Step 2: Write failing API idempotency tests**

Add these methods near existing build-job API tests in `tests/test_api_app.py`:

```python
    def test_build_jobs_surface_reuses_idempotency_key_for_same_job_type(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config = build_test_config(
                {
                    "api": {"access_token": _API_TOKEN},
                    "storage": {
                        "artifact_manifest_path": str(Path(temp_dir) / "manifest.json"),
                        "build_job_store_path": str(Path(temp_dir) / "jobs.json"),
                    },
                }
            )
            system = _FakeApiSystem()
            system.config = config
            app = create_build_api_app(system=system, config=config)

            with _client(app) as client:
                first_response = client.post(
                    "/jobs/build",
                    headers={"Idempotency-Key": "retry-key-1"},
                )
                first_job = first_response.json()["job"]
                _wait_for_job_status(client, first_job["job_id"], "succeeded")
                second_response = client.post(
                    "/jobs/build",
                    headers={"Idempotency-Key": "retry-key-1"},
                )

        self.assertEqual(first_response.status_code, 202)
        self.assertEqual(second_response.status_code, 202)
        self.assertEqual(second_response.json()["job"]["job_id"], first_job["job_id"])
        self.assertEqual(system.build_calls, 1)

    def test_build_jobs_surface_rejects_idempotency_key_reused_for_different_type(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config = build_test_config(
                {
                    "api": {"access_token": _API_TOKEN},
                    "storage": {
                        "artifact_manifest_path": str(Path(temp_dir) / "manifest.json"),
                        "build_job_store_path": str(Path(temp_dir) / "jobs.json"),
                    },
                }
            )
            system = _FakeApiSystem()
            system.config = config
            app = create_build_api_app(system=system, config=config)

            with _client(app) as client:
                first_response = client.post(
                    "/jobs/build",
                    headers={"Idempotency-Key": "retry-key-2"},
                )
                first_job = first_response.json()["job"]
                _wait_for_job_status(client, first_job["job_id"], "succeeded")
                conflict_response = client.post(
                    "/jobs/rebuild",
                    headers={"Idempotency-Key": "retry-key-2"},
                )

        payload = _assert_error_response(
            conflict_response,
            status_code=409,
            code="BUILD_JOB_CONFLICT",
        )
        self.assertEqual(payload["error"]["details"]["job_id"], first_job["job_id"])
        self.assertEqual(payload["error"]["details"]["job_type"], "build")

    def test_build_jobs_surface_rejects_invalid_idempotency_key(self) -> None:
        app = create_build_api_app(system=_FakeApiSystem())

        with _client(app) as client:
            response = client.post("/jobs/build", headers={"Idempotency-Key": "../bad"})

        payload = _assert_error_response(response, status_code=400, code="INVALID_REQUEST")
        self.assertEqual(payload["error"]["details"]["field"], "Idempotency-Key")
```

- [ ] **Step 3: Run tests to verify they fail**

Run:

```powershell
python -m pytest tests/test_build_job_repository.py::BuildJobRepositoryTests::test_same_idempotency_key_and_job_type_returns_original_job tests/test_build_job_repository.py::BuildJobRepositoryTests::test_same_idempotency_key_and_different_job_type_conflicts tests/test_api_app.py::ApiAppTests::test_build_jobs_surface_reuses_idempotency_key_for_same_job_type tests/test_api_app.py::ApiAppTests::test_build_jobs_surface_rejects_idempotency_key_reused_for_different_type tests/test_api_app.py::ApiAppTests::test_build_jobs_surface_rejects_invalid_idempotency_key -q
```

Expected: FAIL because idempotency hashing, route headers, and invalid request handling are absent.

- [ ] **Step 4: Implement idempotency hashing and index records**

In `repository.py`, add imports:

```python
import hashlib
import re
```

Add module constants:

```python
_IDEMPOTENCY_KEY_PATTERN = re.compile(r"[!-~]{1,128}\Z", flags=re.ASCII)
_IDEMPOTENCY_FORBIDDEN_CHARS = frozenset({"/", "\\"})
```

Add helper methods:

```python
class BuildJobIdempotencyConflictError(ValueError):
    """Raised when an idempotency key points to a different build job type."""

    def __init__(self, job: dict):
        super().__init__(
            f"idempotency key already used for {str(job.get('job_type') or '')}"
        )
        self.job = dict(job)


    @staticmethod
    def validate_idempotency_key(value: str) -> str:
        key = str(value or "")
        if not key:
            return ""
        if not _IDEMPOTENCY_KEY_PATTERN.fullmatch(key):
            raise ValueError("invalid Idempotency-Key")
        if any(character in key for character in _IDEMPOTENCY_FORBIDDEN_CHARS):
            raise ValueError("invalid Idempotency-Key")
        return key

    @staticmethod
    def idempotency_key_hash(value: str) -> str:
        key = BuildJobRepository.validate_idempotency_key(value)
        if not key:
            return ""
        return hashlib.sha256(key.encode("utf-8")).hexdigest()

    def _idempotency_path(self, key_hash: str) -> str:
        return os.path.join(self.idempotency_dir, f"{key_hash}.json")

    def _load_idempotency_unlocked(self, key_hash: str) -> dict[str, Any] | None:
        path = self._idempotency_path(key_hash)
        if not os.path.exists(path):
            return None
        try:
            with open(path, "r", encoding="utf-8") as file:
                payload = json.load(file)
            return dict(payload) if isinstance(payload, Mapping) else None
        except (OSError, ValueError, TypeError):
            self._record_warning_unlocked(
                "BUILD_JOB_STORE_CORRUPT_IDEMPOTENCY",
                "idempotency",
                key_hash[:12],
            )
            return None

    def _write_idempotency_unlocked(
        self,
        *,
        key_hash: str,
        job_id: str,
        job_type: str,
    ) -> None:
        write_json_atomic(
            self._idempotency_path(key_hash),
            {
                "key_hash": key_hash,
                "job_id": job_id,
                "job_type": job_type,
                "created_at": self._now(),
            },
        )
```

At the start of `create_or_active()`, compute the hash and check existing index records before active-job conflict handling:

```python
                key_hash = self.idempotency_key_hash(idempotency_key)
                if key_hash:
                    idempotency = self._load_idempotency_unlocked(key_hash)
                    if idempotency is not None:
                        existing_job = self._load_job_unlocked(str(idempotency.get("job_id") or ""))
                        existing_type = str(idempotency.get("job_type") or "")
                        if existing_job is not None and existing_type == job_type:
                            return False, existing_job.to_dict(), None
                        if existing_job is not None:
                            raise BuildJobIdempotencyConflictError(existing_job.to_dict())
```

When creating a new job, pass the hash into `BuildJobRecord` and write the index:

```python
                    idempotency_key_hash=key_hash,
```

After `_write_job_unlocked(job)`, add:

```python
                if key_hash:
                    self._write_idempotency_unlocked(
                        key_hash=key_hash,
                        job_id=job_id,
                        job_type=job_type,
                    )
```

- [ ] **Step 5: Add invalid request error type and handlers**

In `services/errors.py`, add:

```python
class InvalidApiRequestError(ValueError):
    """Raised when an API request has invalid non-body parameters."""

    def __init__(self, message: str, *, details: dict):
        super().__init__(message)
        self.details = dict(details)
```

Add it to `__all__`.

In `error_handlers.py`, import `InvalidApiRequestError` and add:

```python
    @app.exception_handler(InvalidApiRequestError)
    async def invalid_api_request(_: Request, exc: InvalidApiRequestError):
        return build_error_response(
            ErrorCode.INVALID_REQUEST,
            request_id=current_request_id(),
            details=cast(JsonValue, exc.details),
        )
```

Extend `build_job_conflict()` details:

```python
        details = {
            "job_id": str(exc.job.get("job_id") or ""),
            "status": str(exc.job.get("status") or ""),
        }
        if exc.job.get("job_type"):
            details["job_type"] = str(exc.job.get("job_type") or "")
```

- [ ] **Step 6: Pass idempotency keys through service and routes**

In `services/build.py`, import `InvalidApiRequestError` and update signatures:

```python
    def build_knowledge_base(
        self,
        *,
        rebuild: bool = False,
        request_id: str = "",
        idempotency_key: str = "",
    ) -> dict:
        return self.submit_build_job(
            rebuild=rebuild,
            request_id=request_id,
            idempotency_key=idempotency_key,
        )

    def submit_build_job(
        self,
        *,
        rebuild: bool = False,
        request_id: str = "",
        idempotency_key: str = "",
    ) -> dict:
```

Before calling `create_or_active()`, validate:

```python
            try:
                resolved_idempotency_key = self._job_registry.repository.validate_idempotency_key(
                    idempotency_key
                )
            except ValueError:
                raise InvalidApiRequestError(
                    "Invalid Idempotency-Key header.",
                    details={"field": "Idempotency-Key", "reason": "invalid_format"},
                ) from None
```

Pass it into `create_or_active()`:

```python
                idempotency_key=resolved_idempotency_key,
```

Catch repository job-type conflicts:

```python
            except BuildJobIdempotencyConflictError as exc:
                raise BuildJobConflictError(
                    "Idempotency key conflicts with an existing build job.",
                    job=exc.job,
                ) from None
```

Import `BuildJobIdempotencyConflictError` from `rag_modules.interfaces.api.build_jobs`.
Export `BuildJobIdempotencyConflictError` from `repository.py`, `build_jobs/__init__.py`, and
`build_job_store.py` so service code can import it from the package facade.

In `routes.py`, import `Header`:

```python
from fastapi import FastAPI, Header, Path, Query
```

For each build submission route function, add:

```python
        idempotency_key: str = Header(default="", alias="Idempotency-Key"),
```

Pass `idempotency_key=idempotency_key` into `submit_build_job()` or `build_knowledge_base()`.

- [ ] **Step 7: Run idempotency tests**

Run:

```powershell
python -m pytest tests/test_build_job_repository.py tests/test_api_app.py::ApiAppTests::test_build_jobs_surface_reuses_idempotency_key_for_same_job_type tests/test_api_app.py::ApiAppTests::test_build_jobs_surface_rejects_idempotency_key_reused_for_different_type tests/test_api_app.py::ApiAppTests::test_build_jobs_surface_rejects_invalid_idempotency_key -q
```

Expected: PASS.

- [ ] **Step 8: Commit**

```powershell
git add tests/test_build_job_repository.py tests/test_api_app.py rag_modules/interfaces/api/build_jobs/repository.py rag_modules/interfaces/api/services/errors.py rag_modules/interfaces/api/error_handlers.py rag_modules/interfaces/api/services/build.py rag_modules/interfaces/api/routes.py
git commit -m "feat: add build job idempotency keys"
```

## Task 4: Pagination

**Files:**
- Modify: `tests/test_build_job_repository.py`
- Modify: `tests/test_api_app.py`
- Modify: `rag_modules/interfaces/api/build_jobs/repository.py`
- Modify: `rag_modules/interfaces/api/services/build.py`
- Modify: `rag_modules/interfaces/api/routes.py`
- Modify: `rag_modules/interfaces/api/build_models.py`
- Modify: `rag_modules/interfaces/api/response_builder.py`

- [ ] **Step 1: Write failing repository pagination test**

Add this test:

```python
    def test_repository_lists_jobs_newest_first_with_cursor(self) -> None:
        created_times = iter(
            [
                "2026-06-29T00:00:00Z",
                "2026-06-29T00:00:01Z",
                "2026-06-29T00:00:02Z",
            ]
        )

        def next_time() -> str:
            return next(created_times)

        with tempfile.TemporaryDirectory() as temp_dir:
            repository = BuildJobRepository(
                str(Path(temp_dir) / "build_jobs.json"),
                now=next_time,
                settings=BuildJobRepositorySettings(retention_limit=100, list_default_limit=2, list_max_limit=2),
            )
            for job_id in ("1" * 32, "2" * 32, "3" * 32):
                created, job, build_lock = repository.create_or_active(
                    job_id=job_id,
                    request_id=f"request-{job_id[0]}",
                    job_type="build",
                    message="Knowledge base build job queued.",
                    idempotency_key="",
                )
                if build_lock is not None:
                    build_lock.release()
                repository.mark_succeeded(job["job_id"], result={"message": "Knowledge base build completed."})
                self.assertTrue(created)

            first_page = repository.list_page(limit=2, cursor="")
            second_page = repository.list_page(limit=2, cursor=first_page.next_cursor)

            self.assertEqual([job["job_id"] for job in first_page.jobs], ["3" * 32, "2" * 32])
            self.assertTrue(first_page.next_cursor)
            self.assertEqual([job["job_id"] for job in second_page.jobs], ["1" * 32])
            self.assertEqual(second_page.next_cursor, "")
```

- [ ] **Step 2: Write failing API pagination test**

Add this method near build-job API tests:

```python
    def test_build_jobs_surface_paginates_jobs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config = build_test_config(
                {
                    "api": {
                        "access_token": _API_TOKEN,
                        "build_job_list_default_limit": 2,
                        "build_job_list_max_limit": 2,
                    },
                    "storage": {
                        "artifact_manifest_path": str(Path(temp_dir) / "manifest.json"),
                        "build_job_store_path": str(Path(temp_dir) / "jobs.json"),
                    },
                }
            )
            system = _FakeApiSystem()
            system.config = config
            app = create_build_api_app(system=system, config=config)

            with _client(app) as client:
                job_ids: list[str] = []
                for _ in range(3):
                    submitted = client.post("/jobs/build").json()["job"]
                    finished = _wait_for_job_status(client, submitted["job_id"], "succeeded")
                    job_ids.append(finished["job_id"])
                first_page = client.get("/jobs", params={"limit": 2})
                cursor = first_page.json()["next_cursor"]
                second_page = client.get("/jobs", params={"limit": 2, "cursor": cursor})

        self.assertEqual(first_page.status_code, 200)
        self.assertEqual(second_page.status_code, 200)
        self.assertEqual([job["job_id"] for job in first_page.json()["jobs"]], list(reversed(job_ids))[0:2])
        self.assertTrue(cursor)
        self.assertEqual([job["job_id"] for job in second_page.json()["jobs"]], list(reversed(job_ids))[2:3])
        self.assertEqual(second_page.json()["next_cursor"], "")
```

- [ ] **Step 3: Run tests to verify they fail**

Run:

```powershell
python -m pytest tests/test_build_job_repository.py::BuildJobRepositoryTests::test_repository_lists_jobs_newest_first_with_cursor tests/test_api_app.py::ApiAppTests::test_build_jobs_surface_paginates_jobs -q
```

Expected: FAIL because `next_cursor`, cursor parsing, and route query parameters are not implemented.

- [ ] **Step 4: Implement cursor encoding in repository**

In `repository.py`, add imports:

```python
import base64
```

Add helpers:

```python
    @staticmethod
    def _encode_cursor(created_at: str, job_id: str) -> str:
        payload = json.dumps({"created_at": created_at, "job_id": job_id}, separators=(",", ":"))
        return base64.urlsafe_b64encode(payload.encode("utf-8")).decode("ascii")

    @staticmethod
    def _decode_cursor(cursor: str) -> tuple[str, str] | None:
        if not cursor:
            return None
        try:
            raw = base64.urlsafe_b64decode(cursor.encode("ascii")).decode("utf-8")
            payload = json.loads(raw)
            if not isinstance(payload, Mapping):
                raise ValueError
            created_at = str(payload.get("created_at") or "")
            job_id = str(payload.get("job_id") or "")
            if not created_at or not job_id:
                raise ValueError
            return created_at, job_id
        except (OSError, ValueError, TypeError):
            raise ValueError("invalid build job cursor") from None
```

Replace `list_page()` with:

```python
    def list_page(self, *, limit: int, cursor: str = "") -> BuildJobListPage:
        with self._lock:
            with self.locked():
                decoded_cursor = self._decode_cursor(cursor)
                jobs = sorted(
                    self._load_jobs_unlocked(),
                    key=lambda item: (item.created_at, item.job_id),
                    reverse=True,
                )
                if decoded_cursor is not None:
                    cursor_key = decoded_cursor
                    jobs = [
                        job
                        for job in jobs
                        if (job.created_at, job.job_id) < cursor_key
                    ]
                bounded_limit = max(1, min(int(limit), self.settings.list_max_limit))
                selected = jobs[:bounded_limit]
                remaining = jobs[bounded_limit:]
                next_cursor = ""
                if remaining and selected:
                    last = selected[-1]
                    next_cursor = self._encode_cursor(last.created_at, last.job_id)
                return BuildJobListPage(
                    jobs=[job.to_dict() for job in selected],
                    next_cursor=next_cursor,
                )
```

- [ ] **Step 5: Update API models and response builder**

In `build_models.py`, change `BuildJobListResponseModel`:

```python
class BuildJobListResponseModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    jobs: list[BuildJobPayloadModel] = Field(default_factory=list)
    next_cursor: str = ""
```

In `response_builder.py`, change:

```python
def build_build_job_list_response(
    job_payloads: list[dict],
    *,
    next_cursor: str = "",
) -> BuildJobListResponseModel:
    safe = sanitize_public_error_fields(list(job_payloads or []), code=ErrorCode.BUILD_FAILED)
    return BuildJobListResponseModel.model_validate(
        {"jobs": safe, "next_cursor": str(next_cursor or "")}
    )
```

- [ ] **Step 6: Update service and routes**

In `services/build.py`, add:

```python
    def list_build_jobs(self, *, limit: int | None = None, cursor: str = ""):
        resolved_limit = int(limit or self._job_registry.repository.settings.list_default_limit)
        try:
            return self._job_registry.list_page(limit=resolved_limit, cursor=cursor)
        except ValueError:
            raise InvalidApiRequestError(
                "Invalid build job cursor.",
                details={"field": "cursor", "reason": "invalid_cursor"},
            ) from None
```

In `routes.py`, add `Query` import and change the list route:

```python
    def list_build_jobs(
        limit: int | None = Query(default=None, ge=1),
        cursor: str = Query(default=""),
    ):
        page = api_service.list_build_jobs(limit=limit, cursor=cursor)
        return build_build_job_list_response(page.jobs, next_cursor=page.next_cursor)
```

Apply the same function body to the stacked `/v1/jobs` and `/jobs` route.

- [ ] **Step 7: Run pagination tests**

Run:

```powershell
python -m pytest tests/test_build_job_repository.py::BuildJobRepositoryTests::test_repository_lists_jobs_newest_first_with_cursor tests/test_api_app.py::ApiAppTests::test_build_jobs_surface_paginates_jobs -q
```

Expected: PASS.

- [ ] **Step 8: Commit**

```powershell
git add tests/test_build_job_repository.py tests/test_api_app.py rag_modules/interfaces/api/build_jobs/repository.py rag_modules/interfaces/api/services/build.py rag_modules/interfaces/api/routes.py rag_modules/interfaces/api/build_models.py rag_modules/interfaces/api/response_builder.py
git commit -m "feat: paginate build job history"
```

## Task 5: Retention Policy

**Files:**
- Modify: `tests/test_build_job_repository.py`
- Modify: `rag_modules/interfaces/api/build_jobs/repository.py`
- Modify: `rag_modules/configuration/model_sections/api.py`
- Modify: `rag_modules/configuration/env_specs/api.py`
- Modify: `tests/test_configuration_defaults.py`
- Modify: `tests/test_configuration_section_loaders.py`

- [ ] **Step 1: Write failing retention test**

Add this test to `BuildJobRepositoryTests`:

```python
    def test_retention_prunes_old_terminal_jobs_and_preserves_active_jobs(self) -> None:
        timestamps = iter(
            [
                "2026-06-29T00:00:00Z",
                "2026-06-29T00:00:01Z",
                "2026-06-29T00:00:02Z",
                "2026-06-29T00:00:03Z",
            ]
        )

        def next_time() -> str:
            return next(timestamps)

        with tempfile.TemporaryDirectory() as temp_dir:
            repository = BuildJobRepository(
                str(Path(temp_dir) / "build_jobs.json"),
                now=next_time,
                settings=BuildJobRepositorySettings(retention_limit=1, list_default_limit=10, list_max_limit=10),
            )
            for job_id in ("1" * 32, "2" * 32):
                created, job, build_lock = repository.create_or_active(
                    job_id=job_id,
                    request_id=f"request-{job_id[0]}",
                    job_type="build",
                    message="Knowledge base build job queued.",
                    idempotency_key=f"key-{job_id[0]}",
                )
                if build_lock is not None:
                    build_lock.release()
                repository.mark_succeeded(job["job_id"], result={"message": "Knowledge base build completed."})
                self.assertTrue(created)
            active_created, active_job, active_lock = repository.create_or_active(
                job_id="3" * 32,
                request_id="request-3",
                job_type="build",
                message="Knowledge base build job queued.",
                idempotency_key="key-3",
            )
            if active_lock is not None:
                active_lock.release()

            page = repository.list_page(limit=10, cursor="")

            self.assertTrue(active_created)
            self.assertEqual(repository.get("1" * 32), None)
            self.assertEqual(repository.get("2" * 32)["status"], "succeeded")
            self.assertEqual(repository.get(active_job["job_id"])["status"], "queued")
            self.assertEqual([job["job_id"] for job in page.jobs], ["3" * 32, "2" * 32])
            self.assertEqual(
                len(list((Path(temp_dir) / "build_jobs.d" / "idempotency").glob("*.json"))),
                2,
            )
```

- [ ] **Step 2: Write failing config tests**

In `tests/test_configuration_defaults.py`, add:

```python
    def test_default_build_job_history_limits_are_bounded(self) -> None:
        config = load_config(source=EnvConfigSource(environ={}))

        self.assertEqual(config.api.build_job_retention_limit, 100)
        self.assertEqual(config.api.build_job_list_default_limit, 50)
        self.assertEqual(config.api.build_job_list_max_limit, 100)
```

In `tests/test_configuration_section_loaders.py`, extend `test_api_settings_respect_environment_overrides` env and assertions:

```python
                    "API_BUILD_JOB_RETENTION_LIMIT": "12",
                    "API_BUILD_JOB_LIST_DEFAULT_LIMIT": "4",
                    "API_BUILD_JOB_LIST_MAX_LIMIT": "8",
```

```python
        self.assertEqual(config.api.build_job_retention_limit, 12)
        self.assertEqual(config.api.build_job_list_default_limit, 4)
        self.assertEqual(config.api.build_job_list_max_limit, 8)
```

Add invalid relationship coverage:

```python
    def test_api_settings_reject_build_job_default_limit_above_max_limit(self) -> None:
        with self.assertRaises(ConfigurationError):
            load_config(
                source=EnvConfigSource(
                    environ={
                        "API_BUILD_JOB_LIST_DEFAULT_LIMIT": "9",
                        "API_BUILD_JOB_LIST_MAX_LIMIT": "8",
                    }
                )
            )
```

- [ ] **Step 3: Run tests to verify they fail**

Run:

```powershell
python -m pytest tests/test_build_job_repository.py::BuildJobRepositoryTests::test_retention_prunes_old_terminal_jobs_and_preserves_active_jobs tests/test_configuration_defaults.py::ConfigurationDefaultTests::test_default_build_job_history_limits_are_bounded tests/test_configuration_section_loaders.py::ConfigurationSectionLoaderTests::test_api_settings_respect_environment_overrides tests/test_configuration_section_loaders.py::ConfigurationSectionLoaderTests::test_api_settings_reject_build_job_default_limit_above_max_limit -q
```

Expected: FAIL because retention and config fields are missing.

- [ ] **Step 4: Add config fields and validation**

In `model_sections/api.py`, import `model_validator` and `Self`:

```python
from typing import Self

from pydantic import Field, model_validator
```

Add fields:

```python
    build_job_retention_limit: int = Field(default=100, ge=1)
    build_job_list_default_limit: int = Field(default=50, ge=1)
    build_job_list_max_limit: int = Field(default=100, ge=1)
```

Add validator:

```python
    @model_validator(mode="after")
    def _validate_build_job_limits(self) -> Self:
        if self.build_job_list_default_limit > self.build_job_list_max_limit:
            raise ValueError(
                "api.build_job_list_default_limit must be less than or equal to "
                "api.build_job_list_max_limit."
            )
        return self
```

In `env_specs/api.py`, add:

```python
    _spec("API_BUILD_JOB_RETENTION_LIMIT", ("api", "build_job_retention_limit"), "int"),
    _spec("API_BUILD_JOB_LIST_DEFAULT_LIMIT", ("api", "build_job_list_default_limit"), "int"),
    _spec("API_BUILD_JOB_LIST_MAX_LIMIT", ("api", "build_job_list_max_limit"), "int"),
```

- [ ] **Step 5: Apply settings in `GraphRAGBuildApiService`**

In `services/build.py`, import `BuildJobRepositorySettings` and pass config-derived settings:

```python
        api_settings = getattr(resolved_config, "api", None)
        repository_settings = BuildJobRepositorySettings(
            retention_limit=int(getattr(api_settings, "build_job_retention_limit", 100)),
            list_default_limit=int(getattr(api_settings, "build_job_list_default_limit", 50)),
            list_max_limit=int(getattr(api_settings, "build_job_list_max_limit", 100)),
        )
        self._job_registry = PersistentBuildJobRegistry(
            resolved_job_store,
            now=_utc_now_iso,
            recover_interrupted=not resolved_job_store.build_lock_held(),
            settings=repository_settings,
        )
```

- [ ] **Step 6: Implement retention**

In `repository.py`, call `_apply_retention_unlocked()` after successful create and after `mark_succeeded()` / `mark_failed()`.

Add:

```python
    def _apply_retention_unlocked(self) -> None:
        terminal_jobs = [
            job
            for job in self._load_jobs_unlocked()
            if job.status not in {"queued", "running"}
        ]
        terminal_jobs.sort(key=lambda item: (item.created_at, item.job_id), reverse=True)
        for job in terminal_jobs[self.settings.retention_limit :]:
            try:
                os.remove(self._job_path(job.job_id))
            except FileNotFoundError:
                pass
            self._remove_idempotency_for_job_unlocked(job.job_id)

    def _remove_idempotency_for_job_unlocked(self, job_id: str) -> None:
        if not os.path.isdir(self.idempotency_dir):
            return
        for filename in os.listdir(self.idempotency_dir):
            if not filename.endswith(".json"):
                continue
            path = os.path.join(self.idempotency_dir, filename)
            try:
                with open(path, "r", encoding="utf-8") as file:
                    payload = json.load(file)
                if isinstance(payload, Mapping) and str(payload.get("job_id") or "") == job_id:
                    os.remove(path)
            except (OSError, ValueError, TypeError):
                self._record_warning_unlocked(
                    "BUILD_JOB_STORE_CORRUPT_IDEMPOTENCY",
                    "idempotency",
                    filename[:-5][:12],
                )
```

- [ ] **Step 7: Run retention and config tests**

Run:

```powershell
python -m pytest tests/test_build_job_repository.py::BuildJobRepositoryTests::test_retention_prunes_old_terminal_jobs_and_preserves_active_jobs tests/test_configuration_defaults.py tests/test_configuration_section_loaders.py -q
```

Expected: PASS.

- [ ] **Step 8: Commit**

```powershell
git add tests/test_build_job_repository.py tests/test_configuration_defaults.py tests/test_configuration_section_loaders.py rag_modules/interfaces/api/build_jobs/repository.py rag_modules/interfaces/api/services/build.py rag_modules/configuration/model_sections/api.py rag_modules/configuration/env_specs/api.py
git commit -m "feat: add build job retention policy"
```

## Task 6: Corruption Warnings And Diagnostics

**Files:**
- Modify: `tests/test_build_job_repository.py`
- Modify: `tests/test_api_app.py`
- Modify: `rag_modules/interfaces/api/build_jobs/repository.py`
- Modify: `rag_modules/interfaces/api/services/build.py`
- Modify: `rag_modules/interfaces/api/diagnostics_models.py`
- Modify: `rag_modules/interfaces/api/response_builder.py`

- [ ] **Step 1: Write failing repository corruption test**

Add this test:

```python
    def test_corrupt_job_file_is_skipped_and_reported_safely(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            repository = BuildJobRepository(
                str(root / "build_jobs.json"),
                now=_now,
                settings=BuildJobRepositorySettings(),
            )
            created, job, build_lock = repository.create_or_active(
                job_id="4" * 32,
                request_id="request-4",
                job_type="build",
                message="Knowledge base build job queued.",
                idempotency_key="",
            )
            if build_lock is not None:
                build_lock.release()
            self.assertTrue(created)
            corrupt_path = root / "build_jobs.d" / "jobs" / f"{'5' * 32}.json"
            corrupt_path.write_text("{not json with secret-value", encoding="utf-8")

            page = repository.list_page(limit=10, cursor="")
            missing = repository.get("5" * 32)
            summary = repository.corruption_summary()

            self.assertEqual([item["job_id"] for item in page.jobs], [job["job_id"]])
            self.assertIsNone(missing)
            self.assertEqual(summary["warning_count"], 1)
            self.assertEqual(summary["warning_codes"], ["BUILD_JOB_STORE_CORRUPT_RECORD"])
            self.assertNotIn("secret-value", json.dumps(summary, ensure_ascii=False))
```

- [ ] **Step 2: Write failing API diagnostics test**

Add this method near diagnostics tests:

```python
    def test_build_diagnostics_include_safe_build_job_store_warning_summary(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config = build_test_config(
                {
                    "api": {"access_token": _API_TOKEN},
                    "storage": {
                        "artifact_manifest_path": str(root / "manifest.json"),
                        "build_job_store_path": str(root / "jobs.json"),
                    },
                }
            )
            system = _FakeApiSystem()
            system.config = config
            repository_dir = root / "jobs.d" / "jobs"
            repository_dir.mkdir(parents=True)
            (repository_dir / f"{'6' * 32}.json").write_text(
                "{broken secret-diagnostics-value",
                encoding="utf-8",
            )
            app = create_build_api_app(system=system, config=config)

            with _client(app) as client:
                response = client.get("/diagnostics")

        payload = response.json()["diagnostics"]["build_job_store"]
        dumped = json.dumps(response.json(), ensure_ascii=False)
        self.assertEqual(response.status_code, 200)
        self.assertGreaterEqual(payload["warning_count"], 1)
        self.assertIn("BUILD_JOB_STORE_CORRUPT_RECORD", payload["warning_codes"])
        self.assertNotIn("secret-diagnostics-value", dumped)
```

- [ ] **Step 3: Run tests to verify they fail**

Run:

```powershell
python -m pytest tests/test_build_job_repository.py::BuildJobRepositoryTests::test_corrupt_job_file_is_skipped_and_reported_safely tests/test_api_app.py::ApiAppTests::test_build_diagnostics_include_safe_build_job_store_warning_summary -q
```

Expected: FAIL because warning deduplication and API diagnostics model support are incomplete.

- [ ] **Step 4: Deduplicate warnings by component and identifier**

In `repository.py`, replace the warning append guard with key-based comparison:

```python
        existing_keys = {
            (item.code, item.component, item.identifier)
            for item in self._warnings
        }
        key = (warning.code, warning.component, warning.identifier)
        if key not in existing_keys:
            self._warnings.append(warning)
```

Keep `identifier=str(identifier)[:24]` so public payloads never expose full paths or raw contents.

- [ ] **Step 5: Add diagnostics model field and service injection**

In `diagnostics_models.py`, add this field to `StartupDiagnosticsPayloadModel`:

```python
    build_job_store: JsonObject = Field(default_factory=dict)
```

In `services/build.py`, override `_collect_startup_diagnostics_unlocked()`:

```python
    def _collect_startup_diagnostics_unlocked(self, mode: str) -> dict:
        diagnostics = super()._collect_startup_diagnostics_unlocked(mode)
        diagnostics["build_job_store"] = self._job_registry.corruption_summary()
        return diagnostics
```

If `_snapshot_after_build_failure()` already calls `_collect_startup_diagnostics_unlocked()`, it will inherit the safe summary automatically.

- [ ] **Step 6: Run corruption diagnostics tests**

Run:

```powershell
python -m pytest tests/test_build_job_repository.py::BuildJobRepositoryTests::test_corrupt_job_file_is_skipped_and_reported_safely tests/test_api_app.py::ApiAppTests::test_build_diagnostics_include_safe_build_job_store_warning_summary -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

```powershell
git add tests/test_build_job_repository.py tests/test_api_app.py rag_modules/interfaces/api/build_jobs/repository.py rag_modules/interfaces/api/services/build.py rag_modules/interfaces/api/diagnostics_models.py rag_modules/interfaces/api/response_builder.py
git commit -m "feat: report build job store corruption safely"
```

## Task 7: Route Compatibility, Public Surface, And Documentation

**Files:**
- Modify: `tests/test_api_app.py`
- Modify: `tests/test_module_boundary_facades.py`
- Modify: `.env.example`
- Modify: `README.md`
- Modify: `rag_modules/interfaces/api/routes.py`
- Modify: `rag_modules/interfaces/api/build_jobs/__init__.py`
- Modify: `rag_modules/interfaces/api/build_job_store.py`

- [ ] **Step 1: Write failing v1 and alias idempotency tests**

Add these methods:

```python
    def test_v1_build_jobs_accept_idempotency_and_paginated_list_shape(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config = build_test_config(
                {
                    "api": {"access_token": _API_TOKEN},
                    "storage": {
                        "artifact_manifest_path": str(Path(temp_dir) / "manifest.json"),
                        "build_job_store_path": str(Path(temp_dir) / "jobs.json"),
                    },
                }
            )
            system = _FakeApiSystem()
            system.config = config
            app = create_build_api_app(system=system, config=config)

            with _client(app) as client:
                first = client.post("/v1/jobs/build", headers={"Idempotency-Key": "v1-key"})
                job_id = first.json()["job"]["job_id"]
                _wait_for_job_status(client, job_id, "succeeded")
                repeated = client.post("/v1/jobs/build", headers={"Idempotency-Key": "v1-key"})
                listed = client.get("/v1/jobs", params={"limit": 1})

        self.assertEqual(repeated.json()["job"]["job_id"], job_id)
        self.assertIn("next_cursor", listed.json())

    def test_knowledge_base_build_alias_accepts_idempotency_key(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config = build_test_config(
                {
                    "api": {"access_token": _API_TOKEN},
                    "storage": {
                        "artifact_manifest_path": str(Path(temp_dir) / "manifest.json"),
                        "build_job_store_path": str(Path(temp_dir) / "jobs.json"),
                    },
                }
            )
            system = _FakeApiSystem()
            system.config = config
            app = create_build_api_app(system=system, config=config)

            with _client(app) as client:
                first = client.post(
                    "/knowledge-base/build",
                    headers={"Idempotency-Key": "alias-key"},
                )
                job_id = first.json()["job"]["job_id"]
                _wait_for_job_status(client, job_id, "succeeded")
                repeated = client.post(
                    "/knowledge-base/build",
                    headers={"Idempotency-Key": "alias-key"},
                )

        self.assertEqual(repeated.json()["job"]["job_id"], job_id)
```

In `tests/test_module_boundary_facades.py`, extend the facade test:

```python
        self.assertIn("BuildJobRepository", build_job_store.__all__)
```

- [ ] **Step 2: Run tests to verify they fail if aliases or exports are incomplete**

Run:

```powershell
python -m pytest tests/test_api_app.py::ApiAppTests::test_v1_build_jobs_accept_idempotency_and_paginated_list_shape tests/test_api_app.py::ApiAppTests::test_knowledge_base_build_alias_accepts_idempotency_key tests/test_module_boundary_facades.py::ModuleBoundaryFacadeTests::test_build_job_store_facade_reexports_build_job_components -q
```

Expected: FAIL if any route alias or facade export still misses the new behavior.

- [ ] **Step 3: Ensure route aliases share the same implementation**

In `routes.py`, confirm each stacked route function includes `idempotency_key` and passes it through:

```python
    def build_knowledge_base(
        idempotency_key: str = Header(default="", alias="Idempotency-Key"),
    ):
        return build_build_job_response(
            api_service.build_knowledge_base(
                rebuild=False,
                request_id=current_request_id(),
                idempotency_key=idempotency_key,
            )
        )
```

Apply the same pattern to `queue_build_job`, `queue_rebuild_job`, and `rebuild_knowledge_base`.

- [ ] **Step 4: Update facade exports**

In both `build_jobs/__init__.py` and `build_job_store.py`, include:

```python
from .build_jobs import BuildJobRepository
```

for the facade, and:

```python
from .repository import BuildJobRepository
```

for the package. Add `"BuildJobRepository"` to each `__all__`.

- [ ] **Step 5: Update `.env.example`**

Add these lines near the existing API settings:

```dotenv
API_BUILD_JOB_RETENTION_LIMIT=100
API_BUILD_JOB_LIST_DEFAULT_LIMIT=50
API_BUILD_JOB_LIST_MAX_LIMIT=100
```

- [ ] **Step 6: Update README API operations docs**

Add a concise build job operations section with this content:

```markdown
### Build job retries and history

Build API submit routes accept `Idempotency-Key` on `/v1/jobs/build`,
`/v1/jobs/rebuild`, and their compatibility aliases. Reusing the same key for
the same operation returns the original job. Reusing a key for a different
operation returns `409 BUILD_JOB_CONFLICT`.

`GET /v1/jobs` returns a bounded page:

```powershell
curl -H "Authorization: Bearer $env:API_ACCESS_TOKEN" `
  "http://localhost:8001/v1/jobs?limit=50"
```

Follow `next_cursor` until it is empty. Build job history is retained according
to `API_BUILD_JOB_RETENTION_LIMIT`; active jobs are never pruned. If local job
storage contains a corrupted record, `/v1/diagnostics` reports a safe
`build_job_store.warning_count` and stable warning codes without exposing raw
file contents.
```

- [ ] **Step 7: Run compatibility and doc-adjacent tests**

Run:

```powershell
python -m pytest tests/test_api_app.py::ApiAppTests::test_v1_build_jobs_accept_idempotency_and_paginated_list_shape tests/test_api_app.py::ApiAppTests::test_knowledge_base_build_alias_accepts_idempotency_key tests/test_module_boundary_facades.py -q
```

Expected: PASS.

- [ ] **Step 8: Commit**

```powershell
git add tests/test_api_app.py tests/test_module_boundary_facades.py rag_modules/interfaces/api/routes.py rag_modules/interfaces/api/build_jobs/__init__.py rag_modules/interfaces/api/build_job_store.py .env.example README.md
git commit -m "docs: document build job retry and history controls"
```

## Task 8: Focused Regression Pass

**Files:**
- Modify only files needed to fix failures found by the commands in this task.

- [ ] **Step 1: Run build-job persistence and API tests**

Run:

```powershell
python -m pytest tests/test_build_job_repository.py tests/test_build_job_persistence.py tests/test_api_app.py -q
```

Expected: PASS.

- [ ] **Step 2: Fix any failures with TDD discipline**

For each failure, first add or tighten a focused test that fails for the observed behavior. Then adjust the smallest production code path. Use this command after each fix:

```powershell
python -m pytest tests/test_build_job_repository.py tests/test_build_job_persistence.py tests/test_api_app.py -q
```

Expected after each fix: PASS before moving to the next failure.

- [ ] **Step 3: Run configuration and facade tests**

Run:

```powershell
python -m pytest tests/test_configuration_defaults.py tests/test_configuration_section_loaders.py tests/test_module_boundary_facades.py tests/test_public_api_manifest.py -q
```

Expected: PASS.

- [ ] **Step 4: Commit fixes if any were needed**

If Step 2 or Step 3 changed files, commit:

```powershell
git add tests rag_modules .env.example README.md
git commit -m "fix: stabilize build job repository integration"
```

If no files changed, do not create an empty commit.

## Task 9: Final Verification

**Files:**
- No planned source changes.

- [ ] **Step 1: Run formatting and hooks**

Run:

```powershell
pre-commit run --all-files
```

Expected: PASS. If Ruff modifies files, inspect `git diff`, rerun the focused tests from Task 8, then commit the formatting changes:

```powershell
git add rag_modules tests .env.example README.md
git commit -m "style: apply build job repository formatting"
```

- [ ] **Step 2: Run release gate**

Run:

```powershell
python scripts/release_gate.py
```

Expected: PASS.

- [ ] **Step 3: Capture final status**

Run:

```powershell
git status --short
```

Expected: no output. If output lists intentional files, commit them before delivery. If output lists unrelated user changes, leave them unstaged and report them.

## Self-Review

- Spec coverage: repository storage, idempotency keys, pagination, retention, corruption warnings, migration, diagnostics, docs, and verification all have tasks.
- Type consistency: the plan consistently uses `BuildJobRepository`, `BuildJobRepositorySettings`, `BuildJobListPage`, `BuildJobCorruptionWarning`, and `InvalidApiRequestError`.
- Scope: work stays inside build API, configuration, documentation, and focused tests.
- Test order: every behavior task starts with a failing test and a narrow command before implementation.
