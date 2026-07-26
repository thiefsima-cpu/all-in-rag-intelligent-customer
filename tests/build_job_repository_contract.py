"""Backend-neutral build-job repository behavior contract."""

from __future__ import annotations

import tempfile
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from rag_modules.app.build_jobs import (
    BuildJobEvent,
    BuildJobEventListQuery,
    BuildJobEventType,
    BuildJobId,
    BuildJobLeaseLostError,
    BuildJobListQuery,
    BuildJobNotFoundError,
    BuildJobRepositorySettings,
    BuildJobSnapshot,
    BuildJobSubmissionDisposition,
    BuildJobType,
    JobStarted,
    JobSucceeded,
    SubmitBuildJob,
    WorkerIdentity,
)

NOW = datetime(2026, 7, 6, tzinfo=timezone.utc)


class MutableClock:
    def __init__(self, current: datetime = NOW) -> None:
        self.current = current

    def now(self) -> datetime:
        return self.current

    def advance(self, *, seconds: float) -> None:
        self.current += timedelta(seconds=seconds)


def submit_build_job(repository, job_id: str, *, key: str = "") -> BuildJobSnapshot:
    return repository.submit(
        SubmitBuildJob(
            job_id=BuildJobId(job_id),
            request_id=f"request-{job_id[0]}",
            job_type=BuildJobType.BUILD,
            idempotency_key=key,
        )
    ).snapshot


def _event(
    snapshot: BuildJobSnapshot,
    event_type: BuildJobEventType,
    payload: object,
    *,
    clock: MutableClock,
) -> BuildJobEvent:
    return BuildJobEvent(
        event_id=f"{snapshot.job_id}:{snapshot.revision + 1}",
        job_id=snapshot.job_id,
        revision=snapshot.revision + 1,
        event_type=event_type,
        schema_version=1,
        occurred_at=clock.now(),
        request_id=snapshot.request_id,
        payload=payload,
    )


def submit_and_succeed(repository, job_id: str, *, clock: MutableClock, key: str = "") -> BuildJobSnapshot:
    snapshot = submit_build_job(repository, job_id, key=key)
    worker = WorkerIdentity("worker-1", "in_process")
    lease = repository.claim_next(worker)
    claimed = repository.get(snapshot.job_id)
    assert lease is not None
    assert claimed is not None
    started = repository.apply(
        _event(claimed, BuildJobEventType.STARTED, JobStarted(worker), clock=clock),
        expected_revision=claimed.revision,
        lease=lease,
    )
    return repository.apply(
        _event(
            started,
            BuildJobEventType.SUCCEEDED,
            JobSucceeded(result={"message": "Knowledge base build completed."}),
            clock=clock,
        ),
        expected_revision=started.revision,
        lease=replace(lease, revision=started.revision),
    )


class BuildJobRepositoryContractTests:
    """Mixin for repository adapters; subclasses provide ``make_repository``."""

    def setUp(self) -> None:
        super().setUp()
        self._temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self._temporary_directory.name)

    def tearDown(self) -> None:
        self._temporary_directory.cleanup()
        super().tearDown()

    def make_repository(self, clock: MutableClock, settings: BuildJobRepositorySettings):
        raise NotImplementedError

    def test_submit_replays_idempotency_key(self) -> None:
        repository = self.make_repository(MutableClock(), BuildJobRepositorySettings())

        created = submit_build_job(repository, "a" * 32, key="stable-key")
        replayed = repository.submit(
            SubmitBuildJob(
                job_id=BuildJobId("b" * 32),
                request_id="request-b",
                job_type=BuildJobType.BUILD,
                idempotency_key="stable-key",
            )
        )

        self.assertEqual(replayed.disposition, BuildJobSubmissionDisposition.REPLAYED)
        self.assertEqual(replayed.snapshot.job_id, created.job_id)

    def test_renew_lease_rejects_an_expired_lease(self) -> None:
        clock = MutableClock()
        repository = self.make_repository(clock, BuildJobRepositorySettings(lease_seconds=30))
        snapshot = submit_build_job(repository, "c" * 32)
        lease = repository.claim_next(WorkerIdentity("worker-1", "in_process"))
        assert lease is not None

        clock.advance(seconds=30)

        with self.assertRaises(BuildJobLeaseLostError):
            repository.renew_lease(lease)
        self.assertEqual(repository.get(snapshot.job_id).revision, lease.revision)

    def test_list_page_uses_newest_first_keyset_cursor(self) -> None:
        clock = MutableClock()
        repository = self.make_repository(
            clock,
            BuildJobRepositorySettings(list_default_limit=2, list_max_limit=2),
        )
        for job_id in ("1" * 32, "2" * 32, "3" * 32):
            submit_and_succeed(repository, job_id, clock=clock)
            clock.advance(seconds=1)

        first_page = repository.list_page(BuildJobListQuery(limit=50))
        second_page = repository.list_page(BuildJobListQuery(limit=50, cursor=first_page.next_cursor))

        self.assertEqual([snapshot.job_id for snapshot in first_page.jobs], ["3" * 32, "2" * 32])
        self.assertTrue(first_page.next_cursor)
        self.assertEqual([snapshot.job_id for snapshot in second_page.jobs], ["1" * 32])
        self.assertEqual(second_page.next_cursor, "")

    def test_archived_job_events_page_by_revision_and_idempotency_replays_until_purge(self) -> None:
        clock = MutableClock()
        repository = self.make_repository(
            clock,
            BuildJobRepositorySettings(retention_limit=1, list_max_limit=2),
        )
        oldest = submit_and_succeed(repository, "4" * 32, clock=clock, key="key-4")
        clock.advance(seconds=1)
        submit_and_succeed(repository, "5" * 32, clock=clock, key="key-5")

        self.assertIsNone(repository.get(oldest.job_id))
        events = repository.list_events(oldest.job_id, BuildJobEventListQuery(limit=2))
        self.assertEqual([event.revision for event in events.events], [1, 2])
        self.assertTrue(events.next_cursor)
        next_page = repository.list_events(
            oldest.job_id,
            BuildJobEventListQuery(limit=2, cursor=events.next_cursor),
        )
        self.assertEqual([event.revision for event in next_page.events], [3, 4])
        with pytest.raises(ValueError, match="invalid build job event cursor"):
            repository.list_events(oldest.job_id, BuildJobEventListQuery(cursor="not-valid"))

        replayed = repository.submit(
            SubmitBuildJob(
                job_id=BuildJobId("6" * 32),
                request_id="request-6",
                job_type=BuildJobType.BUILD,
                idempotency_key="key-4",
            )
        )
        self.assertEqual(replayed.disposition, BuildJobSubmissionDisposition.REPLAYED)
        self.assertEqual(replayed.snapshot.job_id, oldest.job_id)

        clock.advance(seconds=90 * 86400)
        repository.apply_retention()
        with pytest.raises(BuildJobNotFoundError):
            repository.list_events(oldest.job_id, BuildJobEventListQuery())
        recreated = repository.submit(
            SubmitBuildJob(
                job_id=BuildJobId("7" * 32),
                request_id="request-7",
                job_type=BuildJobType.BUILD,
                idempotency_key="key-4",
            )
        )
        self.assertEqual(recreated.disposition, BuildJobSubmissionDisposition.CREATED)
        self.assertEqual(recreated.snapshot.job_id, BuildJobId("7" * 32))

    def test_find_dispatchable_returns_queued_ids_only(self) -> None:
        repository = self.make_repository(MutableClock(), BuildJobRepositorySettings())
        snapshot = submit_build_job(repository, "7" * 32)

        self.assertEqual(repository.find_dispatchable(limit=10), (snapshot.job_id,))
        self.assertIsNotNone(repository.claim_next(WorkerIdentity("worker-1", "in_process")))
        self.assertEqual(repository.find_dispatchable(limit=10), ())
