from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from rag_modules.app.assembly import assemble_build_job_application, compose_build_job_worker
from rag_modules.app.build_jobs import BuildJobStatus
from rag_modules.app.runtime_operations import resolve_runtime_operation_coordinator
from rag_modules.runtime.build_jobs import ExternalBuildJobQueueRunner, ExternalBuildJobWorkerRunner
from rag_modules.runtime.build_jobs import external_worker_runner as worker_runner_module
from tests.configuration_test_helpers import build_test_config


class _WorkerSystem:
    def __init__(self, config) -> None:
        self.config = config
        self.system_ready = False
        self.build_initialized = False
        self.initialize_calls = 0
        self.build_calls = 0
        self.received_request_id = ""
        self.received_build_job_id = ""

    def is_build_initialized(self) -> bool:
        return self.build_initialized

    def is_serving_initialized(self) -> bool:
        return False

    def initialize_build_runtime(self, progress=None, *, neo4j_manager=None):
        del neo4j_manager
        self.initialize_calls += 1
        self.build_initialized = True
        if progress:
            progress("[OK] Build runtime assembled.")

    def build_knowledge_base(
        self,
        progress=None,
        *,
        request_id: str = "",
        build_job_id: str = "",
    ) -> None:
        self.build_calls += 1
        self.received_request_id = request_id
        self.received_build_job_id = build_job_id
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
                "system_ready": self.system_ready,
                "artifacts_ready": self.system_ready,
                "retrieval_engines_initialized": False,
                "manifest": {"health": "ready" if self.system_ready else "missing"},
            }
        )

    def close(self) -> None:
        return None


def _application(system: _WorkerSystem, config):
    return assemble_build_job_application(
        system=system,
        config=config,
        coordinator=resolve_runtime_operation_coordinator(system),
    )


def _wait_for_status(application, job_id, expected_status: BuildJobStatus):
    deadline = time.time() + 2.0
    last = None
    while time.time() < deadline:
        last = application.get(job_id)
        if last.status is expected_status:
            return last
        time.sleep(0.01)
    raise AssertionError(f"Timed out waiting for {expected_status}. Last job: {last}")


class BuildJobExternalWorkerTests(unittest.TestCase):
    def test_worker_shutdown_closes_its_repository_exactly_once(self) -> None:
        repository = Mock()
        runner = ExternalBuildJobWorkerRunner(
            repository=repository,
            execute_build=lambda _snapshot, _progress, _cancellation_check: None,
            cancelled_result=lambda: {},
            failed_result=lambda: {},
            max_workers=1,
            worker_id="worker-a",
            repository_close=repository.close,
        )

        runner.shutdown()
        runner.shutdown()

        repository.close.assert_called_once_with()

    def test_worker_shutdown_closes_repository_after_start_failure(self) -> None:
        repository = Mock()
        runner = ExternalBuildJobWorkerRunner(
            repository=repository,
            execute_build=lambda _snapshot, _progress, _cancellation_check: None,
            cancelled_result=lambda: {},
            failed_result=lambda: {},
            max_workers=1,
            worker_id="worker-a",
            repository_close=repository.close,
        )

        with patch.object(
            worker_runner_module.threading.Thread, "start", side_effect=RuntimeError("start failed")
        ):
            with self.assertRaisesRegex(RuntimeError, "start failed"):
                runner.start()

        with self.assertRaisesRegex(RuntimeError, "cannot join thread before it is started"):
            runner.shutdown()
        with self.assertRaisesRegex(RuntimeError, "cannot join thread before it is started"):
            runner.shutdown()

        repository.close.assert_called_once_with()

    def test_worker_shutdown_closes_repository_when_poll_join_fails(self) -> None:
        repository = Mock()
        poll_thread = Mock()
        poll_thread.join.side_effect = RuntimeError("join failed")
        runner = ExternalBuildJobWorkerRunner(
            repository=repository,
            execute_build=lambda _snapshot, _progress, _cancellation_check: None,
            cancelled_result=lambda: {},
            failed_result=lambda: {},
            max_workers=1,
            worker_id="worker-a",
            repository_close=repository.close,
        )
        runner._poll_thread = poll_thread

        with self.assertRaisesRegex(RuntimeError, "join failed"):
            runner.shutdown()
        with self.assertRaisesRegex(RuntimeError, "join failed"):
            runner.shutdown()

        repository.close.assert_called_once_with()

    def test_worker_shutdown_closes_repository_when_runner_shutdown_fails(self) -> None:
        repository = Mock()
        runner = ExternalBuildJobWorkerRunner(
            repository=repository,
            execute_build=lambda _snapshot, _progress, _cancellation_check: None,
            cancelled_result=lambda: {},
            failed_result=lambda: {},
            max_workers=1,
            worker_id="worker-a",
            repository_close=repository.close,
        )

        with patch.object(
            worker_runner_module.InProcessBuildJobRunner,
            "shutdown",
            side_effect=RuntimeError("runner shutdown failed"),
        ):
            with self.assertRaisesRegex(RuntimeError, "runner shutdown failed"):
                runner.shutdown()
            with self.assertRaisesRegex(RuntimeError, "runner shutdown failed"):
                runner.shutdown()

        repository.close.assert_called_once_with()

    def test_external_worker_backend_enqueues_without_running_in_api_process(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config = build_test_config(
                {
                    "api": {"build_job_runner_backend": "external_worker"},
                    "storage": {"build_job_store_path": str(Path(temp_dir) / "build_jobs.json")},
                }
            )
            api_system = _WorkerSystem(config)
            application = _application(api_system, config)
            try:
                application.startup()
                submitted = application.submit(
                    rebuild=False,
                    request_id="api-submit-request",
                    idempotency_key="",
                )
            finally:
                application.shutdown()

        self.assertIsInstance(application._runner, ExternalBuildJobQueueRunner)
        self.assertEqual(submitted.status, BuildJobStatus.QUEUED)
        self.assertEqual(api_system.build_calls, 0)
        self.assertEqual(api_system.initialize_calls, 0)

    def test_external_worker_runner_claims_and_executes_persisted_job(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config = build_test_config(
                {
                    "api": {
                        "build_job_runner_backend": "external_worker",
                        "build_job_worker_poll_interval_seconds": 60.0,
                    },
                    "storage": {"build_job_store_path": str(Path(temp_dir) / "build_jobs.json")},
                }
            )
            api_system = _WorkerSystem(config)
            worker_system = _WorkerSystem(config)
            application = _application(api_system, config)
            worker = compose_build_job_worker(
                system=worker_system,
                config=config,
                coordinator=resolve_runtime_operation_coordinator(worker_system),
                worker_id="worker-a",
            )
            try:
                application.startup()
                worker.start()
                submitted = application.submit(
                    rebuild=False,
                    request_id="worker-submit-request",
                    idempotency_key="",
                )

                worker.poll_once()
                completed = _wait_for_status(
                    application,
                    submitted.job_id,
                    BuildJobStatus.SUCCEEDED,
                )
            finally:
                worker.shutdown()
                application.shutdown()

        self.assertIsInstance(worker, ExternalBuildJobWorkerRunner)
        self.assertEqual(api_system.build_calls, 0)
        self.assertEqual(worker_system.build_calls, 1)
        self.assertEqual(worker_system.received_request_id, "worker-submit-request")
        self.assertEqual(worker_system.received_build_job_id, str(submitted.job_id))
        self.assertIsNotNone(completed.worker)
        assert completed.worker is not None
        self.assertEqual(completed.worker.worker_id, "worker-a")
        self.assertEqual(completed.worker.runner_backend, "external_worker")


if __name__ == "__main__":
    unittest.main()
