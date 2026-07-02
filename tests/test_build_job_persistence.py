from __future__ import annotations

import json
import re
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace

from rag_modules.configuration.testing import build_test_config
from rag_modules.interfaces.api.build_job_store import FileBuildJobStore
from rag_modules.interfaces.api.services import (
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

    def build_knowledge_base(
        self,
        progress=None,
        *,
        request_id: str = "",
        build_job_id: str = "",
    ) -> None:
        del request_id, build_job_id
        if progress:
            progress("Building Milvus vector index...")
        self.system_ready = True

    def rebuild_knowledge_base(
        self,
        progress=None,
        *,
        request_id: str = "",
        build_job_id: str = "",
    ) -> None:
        self.build_knowledge_base(
            progress=progress,
            request_id=request_id,
            build_job_id=build_job_id,
        )

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

    def build_knowledge_base(
        self,
        progress=None,
        *,
        request_id: str = "",
        build_job_id: str = "",
    ) -> None:
        del request_id, build_job_id
        if progress:
            progress("building")
        self.build_started.set()
        self.release_build.wait(timeout=2.0)
        self.system_ready = True


class _FailingBuildSystem(_BuildSystem):
    def __init__(self, config, secret: str) -> None:
        super().__init__(config)
        self.secret = secret

    def build_knowledge_base(
        self,
        progress=None,
        *,
        request_id: str = "",
        build_job_id: str = "",
    ) -> None:
        del request_id, build_job_id
        if progress:
            progress(f"private progress {self.secret}")
        raise RuntimeError(self.secret)


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


def _repository_job_path(store_path: str, job_id: str) -> Path:
    path = Path(store_path)
    return path.with_name(f"{path.stem}.d") / "jobs" / f"{job_id}.json"


class BuildJobPersistenceTests(unittest.TestCase):
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
            self.assertTrue(_repository_job_path(path, "c" * 32).exists())

    def test_file_store_save_all_refreshes_repository_after_existing_import(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = str(Path(temp_dir) / "build_jobs.json")
            store = FileBuildJobStore(path)
            store.save_all(
                [
                    {
                        "job_id": "c" * 32,
                        "request_id": "first-seed",
                        "job_type": "build",
                        "status": "succeeded",
                        "created_at": "2026-06-28T00:00:00Z",
                    }
                ]
            )
            self.assertEqual(FileBuildJobStore(path).load_all()[0]["job_id"], "c" * 32)

            store.save_all(
                [
                    {
                        "job_id": "d" * 32,
                        "request_id": "second-seed",
                        "job_type": "rebuild",
                        "status": "failed",
                        "created_at": "2026-06-29T00:00:00Z",
                        "error": {"code": "BUILD_FAILED", "request_id": "second-seed"},
                    }
                ]
            )

            loaded = FileBuildJobStore(path).load_all()

            self.assertEqual([job["job_id"] for job in loaded], ["d" * 32])
            self.assertFalse(_repository_job_path(path, "c" * 32).exists())
            self.assertTrue(_repository_job_path(path, "d" * 32).exists())

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
            self.assertEqual(len(restored["logs"]), 1)
            self.assertRegex(
                restored["logs"][0],
                re.compile(
                    r"^stage=build_vector_index elapsed=\d+\.\d{3}s "
                    r'message="Building Milvus vector index\."$'
                ),
            )

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
            config = build_test_config({"storage": {"build_job_store_path": path}})

            service = GraphRAGBuildApiService(
                system=_BuildSystem(config),
                job_store=store,
            )

            recovered = service.get_build_job("a" * 32)
            self.assertEqual(recovered["status"], "failed")
            self.assertEqual(recovered["error"]["code"], "BUILD_FAILED")
            self.assertEqual(recovered["logs"], ["Build interrupted by service restart."])

    def test_failed_job_persists_typed_error_without_raw_exception_or_progress(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = str(Path(temp_dir) / "build_jobs.json")
            config = build_test_config({"storage": {"build_job_store_path": path}})
            secret = "build-database-password"
            service = GraphRAGBuildApiService(
                system=_FailingBuildSystem(config, secret),
                job_store=FileBuildJobStore(path),
            )

            submitted = service.submit_build_job(request_id="build-submit-42")
            failed = _wait_for_service_job_status(service, submitted["job_id"], "failed")
            stored_text = _repository_job_path(path, submitted["job_id"]).read_text(
                encoding="utf-8"
            )

            self.assertEqual(
                failed["error"],
                {
                    "code": "BUILD_FAILED",
                    "message": "The knowledge-base build failed.",
                    "request_id": "build-submit-42",
                },
            )
            self.assertEqual(len(failed["logs"]), 2)
            self.assertRegex(
                failed["logs"][0],
                re.compile(
                    r"^stage=build_progress elapsed=\d+\.\d{3}s "
                    r'message="Build progress updated\."$'
                ),
            )
            self.assertEqual(failed["logs"][1], "Build failed.")
            self.assertNotIn(secret, stored_text)

    def test_legacy_raw_job_errors_are_sanitized_on_load(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = str(Path(temp_dir) / "build_jobs.json")
            store = FileBuildJobStore(path)
            store.save_all(
                [
                    {
                        "job_id": "a" * 32,
                        "job_type": "build",
                        "status": "failed",
                        "created_at": "2026-06-28T00:00:00Z",
                        "error": "legacy-secret",
                        "logs": ["[ERROR] legacy-secret"],
                    }
                ]
            )
            config = build_test_config({"storage": {"build_job_store_path": path}})
            service = GraphRAGBuildApiService(
                system=_BuildSystem(config),
                job_store=store,
            )

            restored = service.get_build_job("a" * 32)
            returned_text = json.dumps(restored, ensure_ascii=False)
            stored_text = _repository_job_path(path, "a" * 32).read_text(encoding="utf-8")

            self.assertEqual(restored["error"]["code"], "BUILD_FAILED")
            self.assertEqual(restored["logs"], ["Build failed."])
            self.assertTrue(Path(path).exists())
            self.assertNotIn("legacy-secret", returned_text)
            self.assertNotIn("legacy-secret", stored_text)

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
