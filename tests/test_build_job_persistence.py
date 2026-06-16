from __future__ import annotations

import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace

from rag_modules.configuration.testing import build_test_config
from rag_modules.interfaces.api.build_job_store import FileBuildJobStore
from rag_modules.interfaces.api.service import (
    BuildJobConflictError,
    GraphRAGBuildApiService,
)


class _BuildSystem:
    def __init__(self, config) -> None:
        self.config = config
        self.system_ready = False
        self.build_initialized = False

    def is_build_initialized(self) -> bool:
        return self.build_initialized

    def is_serving_initialized(self) -> bool:
        return False

    def initialize_build_runtime(self, progress=None, *, neo4j_manager=None):
        del progress, neo4j_manager
        self.build_initialized = True

    def build_knowledge_base(self, progress=None) -> None:
        if progress:
            progress("building")
        self.system_ready = True

    def rebuild_knowledge_base(self, progress=None) -> None:
        self.build_knowledge_base(progress=progress)

    def collect_system_stats(self) -> dict:
        return {"ready": self.system_ready}

    def collect_startup_diagnostics(self, mode: str):
        return SimpleNamespace(
            to_dict=lambda: {
                "mode": mode,
                "build_initialized": self.build_initialized,
                "serving_initialized": False,
                "artifacts_ready": self.system_ready,
                "system_ready": self.system_ready,
                "retrieval_engines_initialized": False,
                "manifest": {"health": "ready" if self.system_ready else "missing"},
            }
        )

    def close(self) -> None:
        return None


class _BlockingBuildSystem(_BuildSystem):
    def __init__(self, config) -> None:
        super().__init__(config)
        self.build_initialized = True
        self.build_started = threading.Event()
        self.release_build = threading.Event()

    def build_knowledge_base(self, progress=None) -> None:
        if progress:
            progress("building")
        self.build_started.set()
        self.release_build.wait(timeout=2.0)
        self.system_ready = True


def _wait_for_service_job_status(
    service: GraphRAGBuildApiService,
    job_id: str,
    expected_status: str,
    *,
    timeout: float = 2.0,
) -> dict:
    deadline = time.time() + timeout
    last_payload: dict = {}
    while time.time() < deadline:
        last_payload = service.get_build_job(job_id)
        if last_payload["status"] == expected_status:
            return last_payload
        time.sleep(0.01)
    raise AssertionError(
        f"Timed out waiting for build job {job_id} to reach {expected_status!r}. "
        f"Last payload: {last_payload}"
    )


class BuildJobPersistenceTests(unittest.TestCase):
    def test_completed_job_is_visible_after_service_restart(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config = build_test_config(
                {
                    "storage": {
                        "artifact_manifest_path": str(root / "manifest.json"),
                        "build_job_store_path": str(root / "build_jobs.json"),
                    }
                }
            )
            store = FileBuildJobStore(config.storage.build_job_store_path)
            service = GraphRAGBuildApiService(
                system=_BuildSystem(config),
                job_store=store,
            )

            submitted = service.submit_build_job()
            deadline = time.time() + 2.0
            while time.time() < deadline:
                completed = service.get_build_job(submitted["job_id"])
                if completed["status"] == "succeeded":
                    break
                time.sleep(0.01)
            else:
                self.fail("Build job did not complete.")

            restarted = GraphRAGBuildApiService(
                system=_BuildSystem(config),
                job_store=FileBuildJobStore(config.storage.build_job_store_path),
            )

            restored = restarted.get_build_job(submitted["job_id"])
            self.assertEqual(restored["status"], "succeeded")
            self.assertEqual(restored["logs"], ["building"])

    def test_incomplete_job_is_marked_failed_during_recovery(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = str(Path(temp_dir) / "build_jobs.json")
            store = FileBuildJobStore(path)
            store.save_all(
                [
                    {
                        "job_id": "a" * 32,
                        "job_type": "build",
                        "status": "running",
                        "created_at": "2026-06-12T00:00:00Z",
                    }
                ]
            )
            config = build_test_config(
                {"storage": {"build_job_store_path": path}}
            )

            service = GraphRAGBuildApiService(
                system=_BuildSystem(config),
                job_store=store,
            )

            recovered = service.get_build_job("a" * 32)
            self.assertEqual(recovered["status"], "failed")
            self.assertIn("restarted", recovered["error"])

    def test_parallel_service_instances_conflict_on_active_build_job(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config = build_test_config(
                {
                    "storage": {
                        "artifact_manifest_path": str(root / "manifest.json"),
                        "build_job_store_path": str(root / "build_jobs.json"),
                    }
                }
            )
            first_system = _BlockingBuildSystem(config)
            first_service = GraphRAGBuildApiService(
                system=first_system,
                job_store=FileBuildJobStore(config.storage.build_job_store_path),
            )
            second_service = GraphRAGBuildApiService(
                system=_BuildSystem(config),
                job_store=FileBuildJobStore(config.storage.build_job_store_path),
            )

            submitted = first_service.submit_build_job()
            self.assertTrue(first_system.build_started.wait(timeout=1.0))

            try:
                with self.assertRaises(BuildJobConflictError) as caught:
                    second_service.submit_build_job(rebuild=True)
                self.assertEqual(caught.exception.job["job_id"], submitted["job_id"])
                self.assertEqual(
                    second_service.get_build_job(submitted["job_id"])["status"],
                    "running",
                )
            finally:
                first_system.release_build.set()
                _wait_for_service_job_status(
                    first_service,
                    submitted["job_id"],
                    "succeeded",
                )

    def test_service_startup_preserves_active_job_owned_by_another_service(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config = build_test_config(
                {
                    "storage": {
                        "artifact_manifest_path": str(root / "manifest.json"),
                        "build_job_store_path": str(root / "build_jobs.json"),
                    }
                }
            )
            first_system = _BlockingBuildSystem(config)
            first_service = GraphRAGBuildApiService(
                system=first_system,
                job_store=FileBuildJobStore(config.storage.build_job_store_path),
            )

            submitted = first_service.submit_build_job()
            self.assertTrue(first_system.build_started.wait(timeout=1.0))

            try:
                restarted = GraphRAGBuildApiService(
                    system=_BuildSystem(config),
                    job_store=FileBuildJobStore(config.storage.build_job_store_path),
                )

                restored = restarted.get_build_job(submitted["job_id"])
                self.assertEqual(restored["status"], "running")
            finally:
                first_system.release_build.set()
                _wait_for_service_job_status(
                    first_service,
                    submitted["job_id"],
                    "succeeded",
                )


if __name__ == "__main__":
    unittest.main()
