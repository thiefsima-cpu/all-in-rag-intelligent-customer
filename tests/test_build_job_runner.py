from __future__ import annotations

import json
import tempfile
import threading
import time
import unittest
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from rag_modules.app.build_jobs import (
    BuildJobApplicationService,
    BuildJobExecutor,
    BuildJobId,
    BuildJobRuntimeHooks,
    BuildJobStatus,
)
from rag_modules.runtime.build_jobs import FileBuildJobRepository, InProcessBuildJobRunner

NOW = datetime(2026, 7, 6, tzinfo=timezone.utc)


class MutableClock:
    def __init__(self) -> None:
        self.current = NOW

    def now(self) -> datetime:
        return self.current

    def advance(self, *, seconds: float) -> None:
        self.current += timedelta(seconds=seconds)


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


class _BlockedProgressSystem(_RunnerSystem):
    def __init__(self) -> None:
        super().__init__()
        self.build_initialized = True
        self.started = threading.Event()
        self.allow_progress = threading.Event()
        self.finished = threading.Event()

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
        self.allow_progress.wait(timeout=2.0)
        try:
            if progress:
                progress("Building Milvus vector index...")
        finally:
            self.finished.set()


def _stack(
    root: Path,
    system: _RunnerSystem,
    *,
    clock: MutableClock | None = None,
    heartbeat_trigger: threading.Event | None = None,
) -> tuple[FileBuildJobRepository, InProcessBuildJobRunner, BuildJobApplicationService]:
    resolved_clock = clock or MutableClock()
    repository = FileBuildJobRepository(str(root / "build_jobs.json"), now=resolved_clock.now)
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
    executor = BuildJobExecutor(hooks=hooks)
    runner = InProcessBuildJobRunner(
        repository=repository,
        executor=executor,
        max_workers=1,
        worker_id="test-worker",
        heartbeat_seconds=10.0,
        heartbeat_trigger=heartbeat_trigger,
    )
    ids = iter(["a" * 32, "b" * 32, "c" * 32])
    service = BuildJobApplicationService(
        repository=repository,
        runner=runner,
        new_id=lambda: next(ids),
        now=resolved_clock.now,
    )
    return repository, runner, service


def _wait_for_status(
    service: BuildJobApplicationService,
    job_id: BuildJobId,
    expected_status: BuildJobStatus,
    *,
    timeout: float = 2.0,
):
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        last = service.get(job_id)
        if last.status is expected_status:
            return last
        time.sleep(0.01)
    raise AssertionError(
        f"Timed out waiting for {job_id} to become {expected_status!r}. Last job: {last}"
    )


def _lease_path(root: Path, job_id: BuildJobId) -> Path:
    return root / "build_jobs.d" / "leases" / f"{job_id}.json"


def _read_lease(root: Path, job_id: BuildJobId) -> dict[str, Any]:
    return json.loads(_lease_path(root, job_id).read_text(encoding="utf-8"))


class BuildJobRunnerTests(unittest.TestCase):
    def test_submit_executes_build_and_persists_progress(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            system = _RunnerSystem()
            repository, runner, service = _stack(Path(temp_dir), system)
            try:
                service.startup()
                submitted = service.submit(
                    rebuild=False,
                    request_id="runner-request",
                    idempotency_key="",
                )
                completed = _wait_for_status(service, submitted.job_id, BuildJobStatus.SUCCEEDED)
            finally:
                runner.shutdown()

        self.assertEqual(system.initialize_calls, 1)
        self.assertEqual(system.build_calls, 1)
        self.assertEqual(completed.result["message"], "Knowledge base build completed.")
        self.assertTrue(
            any("stage=build_vector_index " in log for log in completed.to_public_dict()["logs"]),
            completed.logs,
        )

    def test_cancel_running_job_is_observed_by_progress_checkpoint(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            system = _CancellableRunnerSystem()
            repository, runner, service = _stack(Path(temp_dir), system)
            try:
                service.startup()
                submitted = service.submit(
                    rebuild=False,
                    request_id="cancel-request",
                    idempotency_key="",
                )
                self.assertTrue(system.started.wait(timeout=1.0))

                cancel_result = service.cancel(submitted.job_id)
                cancelled = _wait_for_status(
                    service,
                    submitted.job_id,
                    BuildJobStatus.CANCELLED,
                    timeout=5.0,
                )
            finally:
                runner.shutdown()

        self.assertIn(
            cancel_result.status, {BuildJobStatus.CANCEL_REQUESTED, BuildJobStatus.CANCELLED}
        )
        self.assertEqual(cancelled.message, "Build cancelled.")
        self.assertIn("Build cancellation requested.", cancelled.logs)
        self.assertIn("Build cancelled.", cancelled.logs)

    def test_retry_creates_new_job_linked_to_failed_job(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            system = _FailOnceRunnerSystem()
            repository, runner, service = _stack(Path(temp_dir), system)
            try:
                service.startup()
                submitted = service.submit(
                    rebuild=False,
                    request_id="first-request",
                    idempotency_key="",
                )
                failed = _wait_for_status(service, submitted.job_id, BuildJobStatus.FAILED)

                retried = service.retry(
                    failed.job_id,
                    request_id="retry-request",
                    idempotency_key="",
                )
                completed = _wait_for_status(service, retried.job_id, BuildJobStatus.SUCCEEDED)
            finally:
                runner.shutdown()

        self.assertNotEqual(retried.job_id, failed.job_id)
        self.assertEqual(completed.retry_of_job_id, failed.job_id)
        self.assertEqual(system.build_calls, 2)

    def test_stale_worker_stops_after_lease_is_replaced(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            system = _BlockedProgressSystem()
            repository, runner, service = _stack(root, system)
            try:
                service.startup()
                submitted = service.submit(
                    rebuild=False,
                    request_id="stale-request",
                    idempotency_key="",
                )
                self.assertTrue(system.started.wait(timeout=1.0))
                lease = _read_lease(root, submitted.job_id)
                lease["lease_token"] = "different-owner"
                _lease_path(root, submitted.job_id).write_text(json.dumps(lease), encoding="utf-8")

                system.allow_progress.set()
                self.assertTrue(system.finished.wait(timeout=1.0))
                stale = service.get(submitted.job_id)
            finally:
                runner.shutdown()

        self.assertEqual(stale.status, BuildJobStatus.RUNNING)
        self.assertEqual(stale.logs, ())

    def test_heartbeat_renews_lease_without_progress(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            clock = MutableClock()
            heartbeat_trigger = threading.Event()
            system = _BlockedProgressSystem()
            repository, runner, service = _stack(
                root,
                system,
                clock=clock,
                heartbeat_trigger=heartbeat_trigger,
            )
            try:
                service.startup()
                submitted = service.submit(
                    rebuild=False,
                    request_id="heartbeat-request",
                    idempotency_key="",
                )
                self.assertTrue(system.started.wait(timeout=1.0))
                original_lease = _read_lease(root, submitted.job_id)

                clock.advance(seconds=5)
                heartbeat_trigger.set()
                deadline = time.time() + 1.0
                renewed_lease = original_lease
                while time.time() < deadline:
                    renewed_lease = _read_lease(root, submitted.job_id)
                    if renewed_lease["lease_expires_at"] != original_lease["lease_expires_at"]:
                        break
                    time.sleep(0.01)
            finally:
                system.allow_progress.set()
                runner.shutdown()

        self.assertGreater(
            datetime.fromisoformat(renewed_lease["lease_expires_at"]),
            datetime.fromisoformat(original_lease["lease_expires_at"]),
        )


if __name__ == "__main__":
    unittest.main()
