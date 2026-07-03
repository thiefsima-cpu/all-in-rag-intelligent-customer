from __future__ import annotations

import tempfile
import threading
import time
import unittest
from contextlib import contextmanager
from pathlib import Path

from rag_modules.interfaces.api.build_jobs import (
    BuildJobRuntimeHooks,
    FileBuildJobStore,
    InProcessBuildJobRunner,
    PersistentBuildJobRegistry,
)


def _now() -> str:
    return "2026-07-03T00:00:00Z"


@contextmanager
def _lifecycle_operation():
    yield


class _RunnerSystem:
    def __init__(self) -> None:
        self.build_initialized = False
        self.system_ready = False
        self.initialize_calls = 0
        self.build_calls = 0
        self.rebuild_calls = 0

    def is_build_initialized(self) -> bool:
        return self.build_initialized

    def initialize_build_runtime(self, progress=None):
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
        del request_id, build_job_id
        self.build_calls += 1
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
        del request_id, build_job_id
        self.rebuild_calls += 1
        if progress:
            progress("Building the inactive Milvus collection...")
        self.system_ready = True


class _CancellableRunnerSystem(_RunnerSystem):
    def __init__(self) -> None:
        super().__init__()
        self.build_initialized = True
        self.started = threading.Event()

    def build_knowledge_base(
        self,
        progress=None,
        *,
        request_id: str = "",
        build_job_id: str = "",
    ) -> None:
        del request_id, build_job_id
        self.build_calls += 1
        self.started.set()
        while True:
            if progress:
                progress("Building Milvus vector index...")
            time.sleep(0.01)


class _FailOnceRunnerSystem(_RunnerSystem):
    def __init__(self) -> None:
        super().__init__()
        self.build_initialized = True
        self.failures_remaining = 1

    def build_knowledge_base(
        self,
        progress=None,
        *,
        request_id: str = "",
        build_job_id: str = "",
    ) -> None:
        del progress, request_id, build_job_id
        self.build_calls += 1
        if self.failures_remaining:
            self.failures_remaining -= 1
            raise RuntimeError("private build failure")
        self.system_ready = True


def _runner(root: Path, system: _RunnerSystem) -> InProcessBuildJobRunner:
    registry = PersistentBuildJobRegistry(
        FileBuildJobStore(str(root / "build_jobs.json")),
        now=_now,
    )
    hooks = BuildJobRuntimeHooks(
        system=system,
        lifecycle_operation=_lifecycle_operation,
        operation_response=lambda message: {
            "message": message,
            "diagnostics": {"mode": "build"},
            "stats": {"ready": system.system_ready},
        },
        failure_snapshot=lambda: (
            {"mode": "build", "system_ready": False},
            {"ready": False},
        ),
    )
    return InProcessBuildJobRunner(
        registry=registry,
        hooks=hooks,
        max_workers=1,
    )


def _wait_for_status(
    runner: InProcessBuildJobRunner,
    job_id: str,
    expected_status: str,
    *,
    timeout: float = 2.0,
) -> dict:
    deadline = time.time() + timeout
    last_job: dict = {}
    while time.time() < deadline:
        last_job = runner.get(job_id)
        if last_job["status"] == expected_status:
            return last_job
        time.sleep(0.01)
    raise AssertionError(
        f"Timed out waiting for {job_id} to become {expected_status!r}. Last job: {last_job}"
    )


class BuildJobRunnerTests(unittest.TestCase):
    def test_submit_executes_build_and_persists_progress(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            system = _RunnerSystem()
            runner = _runner(Path(temp_dir), system)
            try:
                submitted = runner.submit(
                    rebuild=False,
                    request_id="runner-request",
                    idempotency_key="",
                )
                completed = _wait_for_status(runner, submitted["job_id"], "succeeded")
            finally:
                runner.shutdown()

        self.assertEqual(system.initialize_calls, 1)
        self.assertEqual(system.build_calls, 1)
        self.assertEqual(completed["result"]["message"], "Knowledge base build completed.")
        self.assertTrue(
            any("stage=build_vector_index " in log for log in completed["logs"]),
            completed["logs"],
        )

    def test_cancel_running_job_is_observed_by_progress_checkpoint(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            system = _CancellableRunnerSystem()
            runner = _runner(Path(temp_dir), system)
            try:
                submitted = runner.submit(
                    rebuild=False,
                    request_id="cancel-request",
                    idempotency_key="",
                )
                self.assertTrue(system.started.wait(timeout=1.0))

                cancel_result = runner.cancel(submitted["job_id"])
                cancelled = _wait_for_status(runner, submitted["job_id"], "cancelled")
            finally:
                runner.shutdown()

        self.assertIn(cancel_result["status"], {"cancel_requested", "cancelled"})
        self.assertEqual(cancelled["message"], "Knowledge base build cancelled.")
        self.assertIn("Build cancellation requested.", cancelled["logs"])
        self.assertIn("Build cancelled.", cancelled["logs"])

    def test_retry_creates_new_job_linked_to_failed_job(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            system = _FailOnceRunnerSystem()
            runner = _runner(Path(temp_dir), system)
            try:
                submitted = runner.submit(
                    rebuild=False,
                    request_id="first-request",
                    idempotency_key="",
                )
                failed = _wait_for_status(runner, submitted["job_id"], "failed")

                retried = runner.retry(failed["job_id"], request_id="retry-request")
                completed = _wait_for_status(runner, retried["job_id"], "succeeded")
            finally:
                runner.shutdown()

        self.assertNotEqual(retried["job_id"], failed["job_id"])
        self.assertEqual(completed["retry_of_job_id"], failed["job_id"])
        self.assertEqual(system.build_calls, 2)


if __name__ == "__main__":
    unittest.main()
