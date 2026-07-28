"""External build-job worker runner adapters."""

from __future__ import annotations

import threading
from collections.abc import Callable

from rag_modules.contracts.build_jobs import BuildJobId, BuildJobRepositoryPort

from .in_process_runner import (
    BuildJobExecution,
    BuildJobResult,
    BuildLeaseRecorder,
    InProcessBuildJobRunner,
)


class ExternalBuildJobQueueRunner:
    """API-side runner for deployments where separate workers execute queued jobs."""

    backend = "external_worker"

    def start(self) -> None:
        return None

    def schedule(self, job_id: BuildJobId) -> None:
        del job_id
        return None

    def notify_cancellation(self, job_id: BuildJobId) -> None:
        del job_id
        return None

    def shutdown(self) -> None:
        return None


class ExternalBuildJobWorkerRunner(InProcessBuildJobRunner):
    """Polling worker runner for the external-worker backend."""

    backend = "external_worker"

    def __init__(
        self,
        *,
        repository: BuildJobRepositoryPort,
        execute_build: BuildJobExecution,
        cancelled_result: BuildJobResult,
        failed_result: BuildJobResult,
        max_workers: int,
        worker_id: str,
        heartbeat_seconds: float = 10.0,
        poll_interval_seconds: float = 1.0,
        heartbeat_trigger: threading.Event | None = None,
        poll_trigger: threading.Event | None = None,
        lease_recorder: BuildLeaseRecorder | None = None,
        repository_close: Callable[[], None] | None = None,
    ) -> None:
        super().__init__(
            repository=repository,
            execute_build=execute_build,
            cancelled_result=cancelled_result,
            failed_result=failed_result,
            max_workers=max_workers,
            worker_id=worker_id,
            heartbeat_seconds=heartbeat_seconds,
            heartbeat_trigger=heartbeat_trigger,
            lease_recorder=lease_recorder,
        )
        self._poll_interval_seconds = max(0.1, float(poll_interval_seconds or 1.0))
        self._poll_trigger = poll_trigger
        self._poll_thread: threading.Thread | None = None
        self._repository_close = repository_close or (lambda: None)
        self._repository_closed = False

    @property
    def poll_interval_seconds(self) -> float:
        return self._poll_interval_seconds

    def start(self) -> None:
        super().start()
        with self._lock:
            if self._poll_thread is not None:
                return
            self._poll_thread = threading.Thread(
                target=self._poll_loop,
                name="graph-rag-build-worker-poll",
                daemon=True,
            )
            self._poll_thread.start()

    def poll_once(self) -> None:
        if self._shutdown.is_set():
            return
        for job_id in self._repository.find_dispatchable(limit=self._max_workers):
            self.schedule(job_id)

    def shutdown(self) -> None:
        if self._poll_trigger is not None:
            self._poll_trigger.set()
        try:
            try:
                super().shutdown()
            finally:
                poll_thread = self._poll_thread
                if poll_thread is not None:
                    poll_thread.join(timeout=1.0)
        finally:
            self._close_repository_once()

    def _close_repository_once(self) -> None:
        with self._lock:
            if self._repository_closed:
                return
            self._repository_closed = True
        self._repository_close()

    def _poll_loop(self) -> None:
        while not self._shutdown.is_set():
            if self._poll_trigger is None:
                if self._shutdown.wait(self._poll_interval_seconds):
                    return
            else:
                self._poll_trigger.wait(self._poll_interval_seconds)
                self._poll_trigger.clear()
                if self._shutdown.is_set():
                    return
            self.poll_once()


__all__ = ["ExternalBuildJobQueueRunner", "ExternalBuildJobWorkerRunner"]
