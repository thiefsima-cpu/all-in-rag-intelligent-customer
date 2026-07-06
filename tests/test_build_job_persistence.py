from __future__ import annotations

import json
import re
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace

from rag_modules.app.assembly import assemble_build_job_application
from rag_modules.app.runtime_operations import resolve_runtime_operation_coordinator
from rag_modules.configuration.testing import build_test_config
from rag_modules.interfaces.api.services import (
    BuildJobConflictError,
    GraphRAGBuildApiService,
)
from rag_modules.kernel.artifacts import ArtifactManifest
from rag_modules.runtime.artifacts import ArtifactManifestStore


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
        self.build_started.set()
        self.release_build.wait(timeout=2.0)
        if progress:
            progress("Building Milvus vector index...")
        self.system_ready = True


class _FailingBuildSystem(_BuildSystem):
    def __init__(self, config, secret: str) -> None:
        super().__init__(config)
        self.build_initialized = True
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


def _service(system: _BuildSystem, config) -> GraphRAGBuildApiService:
    coordinator = resolve_runtime_operation_coordinator(system)
    build_jobs = assemble_build_job_application(
        system=system,
        config=config,
        coordinator=coordinator,
    )
    service = GraphRAGBuildApiService(system=system, config=config, build_jobs=build_jobs)
    service.startup()
    return service


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


def _write_v2_running_job(path: str, *, job_id: str) -> None:
    root = Path(path).parent
    jobs_dir = root / "build_jobs.d" / "jobs"
    jobs_dir.mkdir(parents=True)
    (jobs_dir / f"{job_id}.json").write_text(
        json.dumps(
            {
                "job_id": job_id,
                "request_id": "request-killed-build",
                "job_type": "rebuild",
                "status": "running",
                "created_at": "2026-06-12T00:00:00+00:00",
                "started_at": "2026-06-12T00:00:00+00:00",
            }
        ),
        encoding="utf-8",
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
            service = _service(_BuildSystem(config), config)

            submitted = service.submit_build_job()
            completed = _wait_for_service_job_status(service, submitted["job_id"], "succeeded")
            service.shutdown()

            restarted = _service(_BuildSystem(config), config)
            restored = restarted.get_build_job(submitted["job_id"])
            restarted.shutdown()

            self.assertEqual(completed["status"], "succeeded")
            self.assertEqual(restored["status"], "succeeded")
            self.assertRegex(
                restored["logs"][0],
                re.compile(
                    r"^stage=build_vector_index elapsed=\d+\.\d{3}s "
                    r'message="Building Milvus vector index\."$'
                ),
            )

    def test_failed_job_persists_typed_error_without_raw_exception_or_progress(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = str(Path(temp_dir) / "build_jobs.json")
            config = build_test_config({"storage": {"build_job_store_path": path}})
            secret = "build-database-password"
            service = _service(_FailingBuildSystem(config, secret), config)

            submitted = service.submit_build_job(request_id="build-submit-42")
            failed = _wait_for_service_job_status(service, submitted["job_id"], "failed")
            stored_text = _repository_job_path(path, submitted["job_id"]).read_text(
                encoding="utf-8"
            )
            service.shutdown()

            self.assertEqual(failed["error"]["code"], "BUILD_FAILED")
            self.assertNotIn(secret, json.dumps(failed, ensure_ascii=False))
            self.assertNotIn(secret, stored_text)

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
            first_service = _service(first_system, config)
            second_service = _service(_BuildSystem(config), config)

            submitted = first_service.submit_build_job()
            self.assertTrue(first_system.build_started.wait(timeout=1.0))
            try:
                with self.assertRaises(BuildJobConflictError) as caught:
                    second_service.submit_build_job(rebuild=True)
                self.assertEqual(caught.exception.job["job_id"], submitted["job_id"])
                self.assertEqual(
                    second_service.get_build_job(submitted["job_id"])["status"], "running"
                )
            finally:
                first_system.release_build.set()
                _wait_for_service_job_status(first_service, submitted["job_id"], "succeeded")
                first_service.shutdown()
                second_service.shutdown()

    def test_service_startup_marks_interrupted_candidate_manifest_failed(self) -> None:
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
            manifest_store = ArtifactManifestStore(config)
            active = manifest_store.save(
                ArtifactManifest(
                    stage="ready",
                    manifest_version=4,
                    index_signature="sig-old",
                    index_version="v000004-sig-old",
                    collection_name="recipes__blue",
                    collection_base_name="recipes",
                    collection_slot="blue",
                )
            )
            manifest_store.save_candidate(
                active.evolve(
                    stage="building",
                    index_signature="sig-new",
                    collection_name="recipes__green",
                    collection_slot="green",
                    previous_collection_name="recipes__blue",
                )
            )
            _write_v2_running_job(config.storage.build_job_store_path, job_id="a" * 32)

            service = _service(_BuildSystem(config), config)
            recovered_job = service.get_build_job("a" * 32)
            candidate_after_restart = manifest_store.load_candidate()
            service.shutdown()

            self.assertEqual(recovered_job["status"], "failed")
            self.assertIsNotNone(candidate_after_restart)
            assert candidate_after_restart is not None
            self.assertEqual(candidate_after_restart.stage, "failed")
            self.assertEqual(candidate_after_restart.last_error, "BUILD_FAILED")


if __name__ == "__main__":
    unittest.main()
