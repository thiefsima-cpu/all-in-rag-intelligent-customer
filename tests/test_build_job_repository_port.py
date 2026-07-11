from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

from rag_modules.app.build_jobs import (
    BuildJobConcurrentUpdateError,
    BuildJobEvent,
    BuildJobEventType,
    BuildJobId,
    BuildJobLeaseLostError,
    BuildJobListQuery,
    BuildJobRepositorySettings,
    BuildJobSubmissionDisposition,
    BuildJobType,
    JobCancellationRequested,
    JobStarted,
    JobSucceeded,
    SubmitBuildJob,
    WorkerIdentity,
)
from rag_modules.runtime.build_jobs import FileBuildJobRepository

NOW = datetime(2026, 7, 6, tzinfo=timezone.utc)


class MutableClock:
    def __init__(self, current: datetime = NOW) -> None:
        self.current = current

    def now(self) -> datetime:
        return self.current

    def advance(self, *, seconds: float) -> None:
        self.current += timedelta(seconds=seconds)


def _repository(root: Path, clock: MutableClock | None = None) -> FileBuildJobRepository:
    resolved_clock = clock or MutableClock()
    return FileBuildJobRepository(
        str(root / "build_jobs.json"),
        now=resolved_clock.now,
        settings=BuildJobRepositorySettings(
            retention_limit=100,
            list_default_limit=50,
            list_max_limit=100,
            lease_seconds=30,
        ),
    )


def _event(
    snapshot,
    event_type: BuildJobEventType,
    payload,
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


def _submit(repository: FileBuildJobRepository, job_id: str, *, key: str = ""):
    return repository.submit(
        SubmitBuildJob(
            job_id=BuildJobId(job_id),
            request_id=f"request-{job_id[0]}",
            job_type=BuildJobType.BUILD,
            idempotency_key=key,
        )
    ).snapshot


def _succeed(
    repository: FileBuildJobRepository,
    snapshot,
    *,
    clock: MutableClock,
) -> None:
    worker = WorkerIdentity("worker-1", "in_process")
    lease = repository.claim_next(worker)
    self_snapshot = repository.get(snapshot.job_id)
    assert lease is not None
    assert self_snapshot is not None
    started = repository.apply(
        _event(self_snapshot, BuildJobEventType.STARTED, JobStarted(worker), clock=clock),
        expected_revision=self_snapshot.revision,
        lease=lease,
    )
    repository.apply(
        _event(
            started,
            BuildJobEventType.SUCCEEDED,
            JobSucceeded(result={"message": "Knowledge base build completed."}),
            clock=clock,
        ),
        expected_revision=started.revision,
        lease=replace(lease, revision=started.revision),
    )


class BuildJobRepositorySubmissionTests(unittest.TestCase):
    def test_submit_replays_idempotency_key_and_reloads_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            repository = _repository(root)

            submission = repository.submit(
                SubmitBuildJob(
                    job_id=BuildJobId("a" * 32),
                    request_id="request-1",
                    job_type=BuildJobType.BUILD,
                    idempotency_key="stable-key",
                )
            )
            replayed = repository.submit(
                SubmitBuildJob(
                    job_id=BuildJobId("b" * 32),
                    request_id="request-2",
                    job_type=BuildJobType.BUILD,
                    idempotency_key="stable-key",
                )
            )

            self.assertEqual(submission.disposition, BuildJobSubmissionDisposition.CREATED)
            self.assertEqual(replayed.disposition, BuildJobSubmissionDisposition.REPLAYED)
            self.assertEqual(replayed.snapshot.job_id, submission.snapshot.job_id)
            self.assertEqual(repository.get(submission.snapshot.job_id), submission.snapshot)
            stored_text = "".join(
                path.read_text(encoding="utf-8") for path in (root / "build_jobs.d").rglob("*.json")
            )
            self.assertNotIn("stable-key", stored_text)

    def test_apply_requires_expected_revision_and_writes_v3_envelope(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            repository = _repository(root)
            submission = repository.submit(
                SubmitBuildJob(
                    job_id=BuildJobId("c" * 32),
                    request_id="request-1",
                    job_type=BuildJobType.BUILD,
                )
            )
            event = BuildJobEvent(
                event_id="event-2",
                job_id=submission.snapshot.job_id,
                revision=2,
                event_type=BuildJobEventType.CANCELLATION_REQUESTED,
                schema_version=1,
                occurred_at=NOW,
                request_id="request-1",
                payload=JobCancellationRequested(),
            )

            with self.assertRaises(BuildJobConcurrentUpdateError):
                repository.apply(event, expected_revision=0)

            job_path = root / "build_jobs.d" / "jobs" / f"{submission.snapshot.job_id}.json"
            envelope = json.loads(job_path.read_text(encoding="utf-8"))
            self.assertEqual(
                set(envelope),
                {"schema_version", "revision", "baseline", "snapshot", "events"},
            )


class BuildJobRepositoryLeaseTests(unittest.TestCase):
    def test_claim_next_renews_matching_token_and_rejects_stale_token(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            clock = MutableClock()
            repository = _repository(Path(temp_dir), clock)
            snapshot = _submit(repository, "d" * 32)
            worker = WorkerIdentity("worker-1", "in_process")

            lease = repository.claim_next(worker)
            claimed = repository.get(snapshot.job_id)
            assert claimed is not None

            self.assertIsNotNone(lease)
            assert lease is not None
            self.assertTrue(lease.lease_token)
            self.assertEqual(claimed.status.value, "claimed")
            self.assertEqual(claimed.revision, 2)

            clock.advance(seconds=5)
            renewed = repository.renew_lease(lease)

            self.assertEqual(renewed.lease_token, lease.lease_token)
            self.assertEqual(renewed.revision, claimed.revision)
            self.assertGreater(renewed.lease_expires_at, lease.lease_expires_at)
            with self.assertRaises(BuildJobLeaseLostError):
                repository.apply(
                    _event(claimed, BuildJobEventType.STARTED, JobStarted(worker), clock=clock),
                    expected_revision=claimed.revision,
                    lease=replace(renewed, lease_token="different-token"),
                )

    def test_recover_expired_leases_interrupts_only_expired_owned_jobs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            clock = MutableClock()
            repository = _repository(Path(temp_dir), clock)
            snapshot = _submit(repository, "e" * 32)
            lease = repository.claim_next(WorkerIdentity("worker-1", "in_process"))
            assert lease is not None

            clock.advance(seconds=29)
            self.assertEqual(repository.recover_expired_leases(), ())
            still_claimed = repository.get(snapshot.job_id)
            assert still_claimed is not None
            self.assertEqual(still_claimed.status.value, "claimed")

            clock.advance(seconds=1)
            recovered = repository.recover_expired_leases()

            self.assertEqual(len(recovered), 1)
            self.assertEqual(recovered[0].status.value, "interrupted")
            self.assertEqual(recovered[0].to_public_dict()["status"], "failed")


class BuildJobRepositoryListingTests(unittest.TestCase):
    def test_find_dispatchable_returns_queued_ids_only(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repository = _repository(Path(temp_dir))
            snapshot = _submit(repository, "f" * 32)

            self.assertEqual(repository.find_dispatchable(limit=10), (snapshot.job_id,))

            lease = repository.claim_next(WorkerIdentity("worker-1", "in_process"))
            self.assertIsNotNone(lease)
            self.assertEqual(repository.find_dispatchable(limit=10), ())

    def test_list_page_uses_newest_first_cursor_and_list_max_limit(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            clock = MutableClock()
            repository = FileBuildJobRepository(
                str(root / "build_jobs.json"),
                now=clock.now,
                settings=BuildJobRepositorySettings(
                    retention_limit=100,
                    list_default_limit=2,
                    list_max_limit=2,
                    lease_seconds=30,
                ),
            )
            for job_id in ("1" * 32, "2" * 32, "3" * 32):
                snapshot = _submit(repository, job_id)
                _succeed(repository, snapshot, clock=clock)
                clock.advance(seconds=1)

            first_page = repository.list_page(BuildJobListQuery(limit=50))
            second_page = repository.list_page(
                BuildJobListQuery(limit=50, cursor=first_page.next_cursor)
            )

            self.assertEqual(
                [snapshot.job_id for snapshot in first_page.jobs], ["3" * 32, "2" * 32]
            )
            self.assertTrue(first_page.next_cursor)
            self.assertEqual([snapshot.job_id for snapshot in second_page.jobs], ["1" * 32])
            self.assertEqual(second_page.next_cursor, "")
            with self.assertRaisesRegex(ValueError, "invalid build job cursor"):
                repository.list_page(BuildJobListQuery(cursor="not-valid"))


class BuildJobRepositoryRetentionDiagnosticsTests(unittest.TestCase):
    def test_retention_removes_oldest_terminal_jobs_but_never_nonterminal_jobs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            clock = MutableClock()
            repository = FileBuildJobRepository(
                str(root / "build_jobs.json"),
                now=clock.now,
                settings=BuildJobRepositorySettings(
                    retention_limit=1,
                    list_default_limit=50,
                    list_max_limit=100,
                    lease_seconds=30,
                ),
            )
            oldest = _submit(repository, "4" * 32, key="key-4")
            _succeed(repository, oldest, clock=clock)
            clock.advance(seconds=1)
            newest_terminal = _submit(repository, "5" * 32, key="key-5")
            _succeed(repository, newest_terminal, clock=clock)
            clock.advance(seconds=1)
            queued = _submit(repository, "6" * 32, key="key-6")

            repository.apply_retention()

            self.assertIsNone(repository.get(oldest.job_id))
            self.assertIsNotNone(repository.get(newest_terminal.job_id))
            self.assertIsNotNone(repository.get(queued.job_id))
            idempotency_payloads = [
                json.loads(path.read_text(encoding="utf-8"))
                for path in (root / "build_jobs.d" / "idempotency").glob("*.json")
            ]
            self.assertNotIn(
                str(oldest.job_id), {payload["job_id"] for payload in idempotency_payloads}
            )

    def test_malformed_envelope_is_reported_without_leaking_file_contents(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            repository = _repository(root)
            corrupt_job_id = BuildJobId("7" * 32)
            corrupt_path = root / "build_jobs.d" / "jobs" / f"{corrupt_job_id}.json"
            corrupt_path.write_text("{not json with secret-token", encoding="utf-8")

            self.assertIsNone(repository.get(corrupt_job_id))
            diagnostics = repository.diagnostics()
            self.assertEqual(len(diagnostics.warnings), 1)
            self.assertEqual(diagnostics.warnings[0].code, "BUILD_JOB_STORE_CORRUPT_RECORD")
            self.assertNotIn("secret-token", json.dumps(diagnostics.to_public_dict()))


if __name__ == "__main__":
    unittest.main()
