"""In-process build-job runner adapter backed by repository leases."""

from __future__ import annotations

import threading
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone

from rag_modules.contracts import RequestCancelled, RequestControl
from rag_modules.contracts.build_jobs import (
    BuildJobConcurrentUpdateError,
    BuildJobEvent,
    BuildJobEventType,
    BuildJobExecutor,
    BuildJobId,
    BuildJobLease,
    BuildJobLeaseLostError,
    BuildJobRepositoryPort,
    BuildJobSnapshot,
    BuildJobStatus,
    JobCancelled,
    JobFailed,
    JobProgressRecorded,
    JobStarted,
    WorkerIdentity,
)


@dataclass(slots=True)
class _RunningJob:
    lease: BuildJobLease
    control: RequestControl
    snapshot: BuildJobSnapshot
    future: Future[None] | None = None


class InProcessBuildJobRunner:
    backend = "in_process"

    def __init__(
        self,
        *,
        repository: BuildJobRepositoryPort,
        executor: BuildJobExecutor,
        max_workers: int,
        worker_id: str,
        heartbeat_seconds: float = 10.0,
        heartbeat_trigger: threading.Event | None = None,
    ) -> None:
        self._repository = repository
        self._executor = executor
        self._max_workers = max(1, int(max_workers or 1))
        self._worker = WorkerIdentity(str(worker_id or "in-process-worker"), self.backend)
        self._heartbeat_seconds = max(0.1, float(heartbeat_seconds or 10.0))
        self._heartbeat_trigger = heartbeat_trigger
        self._pool = ThreadPoolExecutor(
            max_workers=self._max_workers,
            thread_name_prefix="graph-rag-build",
        )
        self._lock = threading.RLock()
        self._pending: set[BuildJobId] = set()
        self._running: dict[BuildJobId, _RunningJob] = {}
        self._started = False
        self._shutdown = threading.Event()
        self._heartbeat_thread: threading.Thread | None = None

    def start(self) -> None:
        with self._lock:
            if self._started:
                return
            self._started = True
            self._start_heartbeat_locked()
        for job_id in self._repository.find_dispatchable(limit=self._max_workers):
            self.schedule(job_id)

    def schedule(self, job_id: BuildJobId) -> None:
        with self._lock:
            if self._shutdown.is_set():
                return
            if job_id in self._running or job_id in self._pending:
                return
            self._pending.add(job_id)
        self._dispatch_pending()

    def notify_cancellation(self, job_id: BuildJobId) -> None:
        with self._lock:
            running = self._running.get(job_id)
        if running is not None:
            running.control.cancel("build_job_cancelled")

    def shutdown(self) -> None:
        self._shutdown.set()
        with self._lock:
            running = list(self._running.values())
        for handle in running:
            handle.control.cancel("build_job_shutdown")
        if self._heartbeat_trigger is not None:
            self._heartbeat_trigger.set()
        heartbeat_thread = self._heartbeat_thread
        if heartbeat_thread is not None:
            heartbeat_thread.join(timeout=1.0)
        self._pool.shutdown(wait=False, cancel_futures=True)

    def _dispatch_pending(self) -> None:
        while True:
            with self._lock:
                if not self._pending or self._shutdown.is_set():
                    return
            lease = self._repository.claim_next(self._worker)
            if lease is None:
                return
            snapshot = self._repository.get(lease.job_id)
            if snapshot is None:
                return
            control = RequestControl(deadline=float("inf"), scope=f"build_job.{lease.job_id}")
            handle = _RunningJob(lease=lease, control=control, snapshot=snapshot)
            with self._lock:
                self._pending.discard(lease.job_id)
                self._running[lease.job_id] = handle
            try:
                handle.future = self._pool.submit(self._run_claimed_job, handle)
            except Exception:
                with self._lock:
                    self._running.pop(lease.job_id, None)
                raise

    def _run_claimed_job(self, handle: _RunningJob) -> None:
        try:
            current = self._append_started(handle)

            def cancellation_check() -> None:
                handle.control.raise_if_cancelled()
                latest = self._repository.get(current.job_id)
                if latest is not None and latest.status in {
                    BuildJobStatus.CANCEL_REQUESTED,
                    BuildJobStatus.CANCELLED,
                }:
                    raise RequestCancelled("build_job_cancelled")

            def progress(payload: JobProgressRecorded) -> None:
                nonlocal current
                cancellation_check()
                event = self._event(current, BuildJobEventType.PROGRESS_RECORDED, payload)
                current = self._repository.apply(
                    event,
                    expected_revision=current.revision,
                    lease=self._lease_for_revision(handle.lease, current.revision),
                )
                handle.snapshot = current
                handle.lease = self._lease_for_revision(handle.lease, current.revision)

            succeeded = self._executor.execute(
                current,
                progress=progress,
                cancellation_check=cancellation_check,
            )
            current = self._repository.apply(
                self._event(current, BuildJobEventType.SUCCEEDED, succeeded),
                expected_revision=current.revision,
                lease=self._lease_for_revision(handle.lease, current.revision),
            )
            handle.snapshot = current
        except RequestCancelled:
            self._append_cancelled(handle)
        except BuildJobConcurrentUpdateError:
            self._append_cancelled_if_requested(handle)
        except BuildJobLeaseLostError:
            return
        except Exception:
            self._append_failed(handle)
        finally:
            with self._lock:
                self._running.pop(handle.lease.job_id, None)

    def _append_started(self, handle: _RunningJob) -> BuildJobSnapshot:
        current = handle.snapshot
        started = self._repository.apply(
            self._event(current, BuildJobEventType.STARTED, JobStarted(self._worker)),
            expected_revision=current.revision,
            lease=handle.lease,
        )
        handle.snapshot = started
        handle.lease = self._lease_for_revision(handle.lease, started.revision)
        return started

    def _append_cancelled(self, handle: _RunningJob) -> None:
        current = self._repository.get(handle.lease.job_id) or handle.snapshot
        try:
            cancelled = self._repository.apply(
                self._event(
                    current,
                    BuildJobEventType.CANCELLED,
                    JobCancelled(result=self._executor.cancelled_result()),
                ),
                expected_revision=current.revision,
                lease=self._lease_for_revision(handle.lease, current.revision),
            )
            handle.snapshot = cancelled
        except (BuildJobLeaseLostError, BuildJobConcurrentUpdateError):
            return

    def _append_cancelled_if_requested(self, handle: _RunningJob) -> None:
        latest = self._repository.get(handle.lease.job_id)
        if latest is None:
            return
        handle.snapshot = latest
        handle.lease = self._lease_for_revision(handle.lease, latest.revision)
        if latest.status is BuildJobStatus.CANCELLED:
            return
        if latest.status is BuildJobStatus.CANCEL_REQUESTED:
            self._append_cancelled(handle)

    def _append_failed(self, handle: _RunningJob) -> None:
        current = self._repository.get(handle.lease.job_id) or handle.snapshot
        try:
            failed = self._repository.apply(
                self._event(
                    current,
                    BuildJobEventType.FAILED,
                    JobFailed(
                        message="Knowledge base build failed.",
                        result=self._executor.failed_result(),
                    ),
                ),
                expected_revision=current.revision,
                lease=self._lease_for_revision(handle.lease, current.revision),
            )
            handle.snapshot = failed
        except (BuildJobLeaseLostError, BuildJobConcurrentUpdateError):
            return

    def _start_heartbeat_locked(self) -> None:
        if self._heartbeat_thread is not None:
            return
        self._heartbeat_thread = threading.Thread(
            target=self._heartbeat_loop,
            name="graph-rag-build-heartbeat",
            daemon=True,
        )
        self._heartbeat_thread.start()

    def _heartbeat_loop(self) -> None:
        while not self._shutdown.is_set():
            if self._heartbeat_trigger is None:
                if self._shutdown.wait(self._heartbeat_seconds):
                    return
            else:
                self._heartbeat_trigger.wait(self._heartbeat_seconds)
                self._heartbeat_trigger.clear()
                if self._shutdown.is_set():
                    return
            with self._lock:
                handles = list(self._running.values())
            for handle in handles:
                try:
                    renewed = self._repository.renew_lease(handle.lease)
                    with self._lock:
                        if handle.lease.job_id in self._running:
                            handle.lease = renewed
                except BuildJobLeaseLostError:
                    handle.control.cancel("build_job_lease_lost")

    @staticmethod
    def _lease_for_revision(lease: BuildJobLease, revision: int) -> BuildJobLease:
        return BuildJobLease(
            job_id=lease.job_id,
            revision=revision,
            worker=lease.worker,
            lease_token=lease.lease_token,
            lease_expires_at=lease.lease_expires_at,
        )

    @staticmethod
    def _event(
        snapshot: BuildJobSnapshot,
        event_type: BuildJobEventType,
        payload,
    ) -> BuildJobEvent:
        return BuildJobEvent(
            event_id=f"{snapshot.job_id}:{snapshot.revision + 1}",
            job_id=snapshot.job_id,
            revision=snapshot.revision + 1,
            event_type=event_type,
            schema_version=1,
            occurred_at=datetime.now(timezone.utc),
            request_id=snapshot.request_id,
            payload=payload,
        )


__all__ = ["InProcessBuildJobRunner"]
