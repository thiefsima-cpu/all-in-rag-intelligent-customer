from __future__ import annotations

import unittest
from datetime import datetime, timezone

from rag_modules.app.build_jobs import (
    BuildJobApplicationService,
    BuildJobConcurrentUpdateError,
    BuildJobConflictError,
    BuildJobDispatchError,
    BuildJobEvent,
    BuildJobEventListQuery,
    BuildJobEventPage,
    BuildJobEventType,
    BuildJobId,
    BuildJobLease,
    BuildJobListQuery,
    BuildJobNotFoundError,
    BuildJobPage,
    BuildJobRepositoryDiagnostics,
    BuildJobSnapshot,
    BuildJobStatus,
    BuildJobSubmission,
    BuildJobSubmissionDisposition,
    BuildJobType,
    JobQueued,
    SubmitBuildJob,
    WorkerIdentity,
    reduce_build_job,
)

NOW = datetime(2026, 7, 6, tzinfo=timezone.utc)


def _snapshot(
    job_id: str,
    *,
    status: BuildJobStatus = BuildJobStatus.QUEUED,
    revision: int = 1,
    retry_of_job_id: BuildJobId | None = None,
) -> BuildJobSnapshot:
    return BuildJobSnapshot(
        job_id=BuildJobId(job_id),
        request_id=f"request-{job_id[0]}",
        job_type=BuildJobType.BUILD,
        status=status,
        revision=revision,
        created_at=NOW,
        retry_of_job_id=retry_of_job_id,
    )


class RecordingRepository:
    list_default_limit = 50

    def __init__(self, calls: list[tuple]) -> None:
        self.calls = calls
        self.snapshots: dict[BuildJobId, BuildJobSnapshot] = {}
        self.next_submission_disposition = BuildJobSubmissionDisposition.CREATED
        self.submit_exception: Exception | None = None
        self.concurrent_failures = 0
        self.recovered: tuple[BuildJobSnapshot, ...] = ()
        self.events: tuple[BuildJobEvent, ...] = ()

    def submit(self, command: SubmitBuildJob) -> BuildJobSubmission:
        self.calls.append(("repository.submit", command.job_id))
        if self.submit_exception is not None:
            raise self.submit_exception
        if self.next_submission_disposition is BuildJobSubmissionDisposition.REPLAYED:
            existing = next(iter(self.snapshots.values()))
            return BuildJobSubmission(BuildJobSubmissionDisposition.REPLAYED, existing)
        snapshot = _snapshot(
            str(command.job_id),
            retry_of_job_id=command.retry_of_job_id,
        )
        self.snapshots[snapshot.job_id] = snapshot
        return BuildJobSubmission(BuildJobSubmissionDisposition.CREATED, snapshot)

    def get(self, job_id: BuildJobId) -> BuildJobSnapshot | None:
        self.calls.append(("repository.get", job_id))
        return self.snapshots.get(job_id)

    def list_page(self, query: BuildJobListQuery) -> BuildJobPage:
        self.calls.append(("repository.list_page", query.limit, query.cursor, query.status))
        return BuildJobPage(jobs=tuple(self.snapshots.values()))

    def list_events(
        self,
        job_id: BuildJobId,
        query: BuildJobEventListQuery,
    ) -> BuildJobEventPage:
        self.calls.append(("repository.list_events", job_id, query.limit, query.cursor))
        return BuildJobEventPage(events=self.events)

    def claim_next(self, worker: WorkerIdentity) -> BuildJobLease | None:
        raise NotImplementedError

    def renew_lease(self, lease: BuildJobLease) -> BuildJobLease:
        raise NotImplementedError

    def apply(
        self,
        event: BuildJobEvent,
        *,
        expected_revision: int,
        lease: BuildJobLease | None = None,
    ) -> BuildJobSnapshot:
        self.calls.append(("repository.apply", event.event_type, expected_revision))
        if self.concurrent_failures:
            self.concurrent_failures -= 1
            raise BuildJobConcurrentUpdateError("stale revision")
        current = self.snapshots[event.job_id]
        updated = reduce_build_job(current, event)
        self.snapshots[event.job_id] = updated
        return updated

    def find_dispatchable(self, *, limit: int) -> tuple[BuildJobId, ...]:
        return ()

    def recover_expired_leases(self) -> tuple[BuildJobSnapshot, ...]:
        self.calls.append(("repository.recover_expired_leases",))
        return self.recovered

    def apply_retention(self) -> None:
        return None

    def diagnostics(self) -> BuildJobRepositoryDiagnostics:
        return BuildJobRepositoryDiagnostics()

    def close(self) -> None:
        self.calls.append(("repository.close",))


class RecordingRunner:
    def __init__(self, calls: list[tuple]) -> None:
        self.calls = calls
        self.fail_schedule = False

    def start(self) -> None:
        self.calls.append(("runner.start",))

    def schedule(self, job_id: BuildJobId) -> None:
        self.calls.append(("runner.schedule", job_id))
        if self.fail_schedule:
            raise BuildJobDispatchError("dispatch failed")

    def notify_cancellation(self, job_id: BuildJobId) -> None:
        self.calls.append(("runner.notify_cancellation", job_id))

    def shutdown(self) -> None:
        self.calls.append(("runner.shutdown",))


def _service(
    repository: RecordingRepository,
    runner: RecordingRunner,
    warnings: list[BuildJobId] | None = None,
) -> BuildJobApplicationService:
    ids = iter(["a" * 32, "b" * 32, "c" * 32])
    record_dispatch_warning = warnings.append if warnings is not None else (lambda _job_id: None)
    return BuildJobApplicationService(
        repository=repository,
        runner=runner,
        new_id=lambda: next(ids),
        now=lambda: NOW,
        record_dispatch_warning=record_dispatch_warning,
    )


class BuildJobApplicationServiceTests(unittest.TestCase):
    def test_list_events_delegates_audit_query_and_shutdown_closes_repository(self) -> None:
        calls: list[tuple] = []
        repository = RecordingRepository(calls)
        repository.events = (
            BuildJobEvent(
                event_id=f"{'1' * 32}:1",
                job_id=BuildJobId("1" * 32),
                revision=1,
                event_type=BuildJobEventType.QUEUED,
                schema_version=1,
                occurred_at=NOW,
                request_id="request-1",
                payload=JobQueued(job_type=BuildJobType.BUILD),
            ),
        )
        service = _service(repository, RecordingRunner(calls))

        page = service.list_events(BuildJobId("1" * 32), limit=10, cursor="opaque-cursor")
        service.shutdown()

        self.assertEqual(page.events, repository.events)
        self.assertEqual(
            calls,
            [
                ("repository.list_events", BuildJobId("1" * 32), 10, "opaque-cursor"),
                ("runner.shutdown",),
                ("repository.close",),
            ],
        )

    def test_submit_persists_before_scheduling(self) -> None:
        calls: list[tuple] = []
        repository = RecordingRepository(calls)
        runner = RecordingRunner(calls)
        service = _service(repository, runner)

        snapshot = service.submit(
            rebuild=False,
            request_id="request-1",
            idempotency_key="key-1",
        )

        self.assertEqual(
            calls,
            [
                ("repository.submit", snapshot.job_id),
                ("runner.schedule", snapshot.job_id),
            ],
        )

    def test_replayed_submission_does_not_schedule(self) -> None:
        calls: list[tuple] = []
        repository = RecordingRepository(calls)
        existing = _snapshot("9" * 32)
        repository.snapshots[existing.job_id] = existing
        repository.next_submission_disposition = BuildJobSubmissionDisposition.REPLAYED
        service = _service(repository, RecordingRunner(calls))

        snapshot = service.submit(rebuild=False, request_id="request-1", idempotency_key="key-1")

        self.assertEqual(snapshot.job_id, existing.job_id)
        self.assertEqual(calls, [("repository.submit", BuildJobId("a" * 32))])

    def test_repository_failure_never_schedules(self) -> None:
        calls: list[tuple] = []
        repository = RecordingRepository(calls)
        active = _snapshot("8" * 32)
        repository.submit_exception = BuildJobConflictError("active", active)
        runner = RecordingRunner(calls)
        service = _service(repository, runner)

        with self.assertRaises(BuildJobConflictError):
            service.submit(rebuild=False, request_id="request-1", idempotency_key="key-1")

        self.assertEqual(calls, [("repository.submit", BuildJobId("a" * 32))])

    def test_dispatch_failure_leaves_created_snapshot_retrievable(self) -> None:
        calls: list[tuple] = []
        warnings: list[BuildJobId] = []
        repository = RecordingRepository(calls)
        runner = RecordingRunner(calls)
        runner.fail_schedule = True
        service = _service(repository, runner, warnings)

        snapshot = service.submit(rebuild=False, request_id="request-1", idempotency_key="key-1")

        self.assertEqual(repository.get(snapshot.job_id), snapshot)
        self.assertEqual(warnings, [snapshot.job_id])

    def test_cancel_applies_event_before_notifying_runner(self) -> None:
        calls: list[tuple] = []
        repository = RecordingRepository(calls)
        snapshot = _snapshot("7" * 32)
        repository.snapshots[snapshot.job_id] = snapshot
        runner = RecordingRunner(calls)
        service = _service(repository, runner)

        cancelled = service.cancel(snapshot.job_id)

        self.assertEqual(cancelled.status, BuildJobStatus.CANCEL_REQUESTED)
        self.assertEqual(
            calls,
            [
                ("repository.get", snapshot.job_id),
                ("repository.apply", BuildJobEventType.CANCELLATION_REQUESTED, 1),
                ("runner.notify_cancellation", snapshot.job_id),
            ],
        )

    def test_cancel_retries_revision_conflict_and_notifies_after_apply(self) -> None:
        calls: list[tuple] = []
        repository = RecordingRepository(calls)
        snapshot = _snapshot("6" * 32)
        repository.snapshots[snapshot.job_id] = snapshot
        repository.concurrent_failures = 1
        runner = RecordingRunner(calls)
        service = _service(repository, runner)

        cancelled = service.cancel(snapshot.job_id)

        self.assertEqual(cancelled.status, BuildJobStatus.CANCEL_REQUESTED)
        self.assertEqual(calls[-1], ("runner.notify_cancellation", snapshot.job_id))

    def test_cancelled_snapshot_is_idempotent_but_other_terminal_states_reject(self) -> None:
        calls: list[tuple] = []
        repository = RecordingRepository(calls)
        cancelled = _snapshot("5" * 32, status=BuildJobStatus.CANCELLED)
        failed = _snapshot("4" * 32, status=BuildJobStatus.FAILED)
        repository.snapshots[cancelled.job_id] = cancelled
        repository.snapshots[failed.job_id] = failed
        service = _service(repository, RecordingRunner(calls))

        self.assertEqual(service.cancel(cancelled.job_id), cancelled)
        with self.assertRaises(BuildJobConflictError):
            service.cancel(failed.job_id)

    def test_retry_accepts_failed_cancelled_and_interrupted_only(self) -> None:
        calls: list[tuple] = []
        repository = RecordingRepository(calls)
        failed = _snapshot("3" * 32, status=BuildJobStatus.FAILED)
        cancelled = _snapshot("8" * 32, status=BuildJobStatus.CANCELLED)
        interrupted = _snapshot("9" * 32, status=BuildJobStatus.INTERRUPTED)
        running = _snapshot("2" * 32, status=BuildJobStatus.RUNNING)
        repository.snapshots[failed.job_id] = failed
        repository.snapshots[cancelled.job_id] = cancelled
        repository.snapshots[interrupted.job_id] = interrupted
        repository.snapshots[running.job_id] = running
        service = _service(repository, RecordingRunner(calls))

        failed_retry = service.retry(
            failed.job_id,
            request_id="request-retry",
            idempotency_key="retry-key",
        )
        cancelled_retry = service.retry(
            cancelled.job_id,
            request_id="request-retry",
            idempotency_key="retry-key-2",
        )
        interrupted_retry = service.retry(
            interrupted.job_id,
            request_id="request-retry",
            idempotency_key="retry-key-3",
        )

        self.assertEqual(failed_retry.retry_of_job_id, failed.job_id)
        self.assertEqual(cancelled_retry.retry_of_job_id, cancelled.job_id)
        self.assertEqual(interrupted_retry.retry_of_job_id, interrupted.job_id)
        with self.assertRaises(BuildJobConflictError):
            service.retry(running.job_id, request_id="request-retry", idempotency_key="retry-key")

    def test_get_list_startup_and_shutdown_delegate_to_ports(self) -> None:
        calls: list[tuple] = []
        repository = RecordingRepository(calls)
        recovered = _snapshot("1" * 32, status=BuildJobStatus.INTERRUPTED)
        repository.recovered = (recovered,)
        runner = RecordingRunner(calls)
        service = _service(repository, runner)

        self.assertEqual(service.startup(), (recovered,))
        page = service.list_page()
        service.shutdown()

        self.assertEqual(page.jobs, ())
        self.assertEqual(
            calls[:2],
            [("repository.recover_expired_leases",), ("runner.start",)],
        )
        self.assertEqual(
            calls[-3:],
            [("repository.list_page", 50, "", None), ("runner.shutdown",), ("repository.close",)],
        )
        with self.assertRaises(BuildJobNotFoundError):
            service.get(BuildJobId("0" * 32))


if __name__ == "__main__":
    unittest.main()
