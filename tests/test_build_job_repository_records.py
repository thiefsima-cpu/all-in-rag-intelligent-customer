from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

from rag_modules.app.build_jobs import (
    BuildJobConflictError,
    BuildJobEvent,
    BuildJobEventType,
    BuildJobId,
    BuildJobListQuery,
    BuildJobRepositorySettings,
    BuildJobSnapshot,
    BuildJobStatus,
    BuildJobType,
    JobCancellationRequested,
    JobCancelled,
    JobStarted,
    JobSucceeded,
    SubmitBuildJob,
    WorkerIdentity,
)
from rag_modules.runtime.build_jobs import FileBuildJobRepository

NOW = datetime(2026, 6, 29, tzinfo=timezone.utc)


class MutableClock:
    def __init__(self) -> None:
        self.current = NOW

    def now(self) -> datetime:
        return self.current

    def advance(self, *, seconds: float) -> None:
        self.current = self.current.replace(second=self.current.second + int(seconds))


def _now() -> datetime:
    return NOW


def _repository(
    root: Path,
    *,
    settings: BuildJobRepositorySettings | None = None,
) -> FileBuildJobRepository:
    return FileBuildJobRepository(
        str(root / "build_jobs.json"),
        now=_now,
        settings=settings,
    )


def _submit(
    repository: FileBuildJobRepository,
    job_id: str,
    *,
    job_type: BuildJobType = BuildJobType.BUILD,
    idempotency_key: str = "",
    retry_of_job_id: str = "",
) -> BuildJobSnapshot:
    return repository.submit(
        SubmitBuildJob(
            job_id=BuildJobId(job_id),
            request_id=f"request-{job_id[0]}",
            job_type=job_type,
            idempotency_key=idempotency_key,
            retry_of_job_id=BuildJobId(retry_of_job_id) if retry_of_job_id else None,
        )
    ).snapshot


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
        occurred_at=NOW,
        request_id=snapshot.request_id,
        payload=payload,
    )


def _succeed(repository: FileBuildJobRepository, snapshot: BuildJobSnapshot) -> None:
    worker = WorkerIdentity("worker-1", "in_process")
    lease = repository.claim_next(worker)
    claimed = repository.get(snapshot.job_id)
    assert lease is not None
    assert claimed is not None
    started = repository.apply(
        _event(claimed, BuildJobEventType.STARTED, JobStarted(worker)),
        expected_revision=claimed.revision,
        lease=lease,
    )
    repository.apply(
        _event(
            started,
            BuildJobEventType.SUCCEEDED,
            JobSucceeded(result={"message": "Knowledge base build completed."}),
        ),
        expected_revision=started.revision,
        lease=replace(lease, revision=started.revision),
    )


class BuildJobRepositoryRecordTests(unittest.TestCase):
    def test_repository_persists_retry_parent_and_cancel_states(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repository = _repository(Path(temp_dir))
            snapshot = _submit(
                repository,
                "a" * 32,
                idempotency_key="retry-key",
                retry_of_job_id="9" * 32,
            )

            worker = WorkerIdentity("worker-1", "in_process")
            lease = repository.claim_next(worker)
            claimed = repository.get(snapshot.job_id)
            assert lease is not None
            assert claimed is not None
            cancel_requested = repository.apply(
                _event(
                    claimed,
                    BuildJobEventType.CANCELLATION_REQUESTED,
                    JobCancellationRequested(),
                ),
                expected_revision=claimed.revision,
                lease=lease,
            )

            with self.assertRaises(BuildJobConflictError):
                _submit(repository, "b" * 32)

            cancelled = repository.apply(
                _event(
                    cancel_requested,
                    BuildJobEventType.CANCELLED,
                    JobCancelled(result={"message": "Knowledge base build cancelled."}),
                ),
                expected_revision=cancel_requested.revision,
                lease=replace(lease, revision=cancel_requested.revision),
            )

            restored = repository.get(snapshot.job_id)
            self.assertEqual(cancel_requested.status, BuildJobStatus.CANCEL_REQUESTED)
            self.assertEqual(cancelled.status, BuildJobStatus.CANCELLED)
            self.assertIsNotNone(restored)
            assert restored is not None
            self.assertEqual(restored.retry_of_job_id, BuildJobId("9" * 32))
            self.assertEqual(restored.result["message"], "Knowledge base build cancelled.")
            self.assertEqual(_submit(repository, "b" * 32).job_id, BuildJobId("b" * 32))

    def test_corrupt_job_file_is_skipped_and_reported_safely(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            repository = _repository(root)
            snapshot = _submit(repository, "4" * 32)
            corrupt_path = root / "build_jobs.d" / "jobs" / f"{'5' * 32}.json"
            corrupt_path.write_text("{not json with secret-value", encoding="utf-8")

            page = repository.list_page(BuildJobListQuery(limit=10))
            missing = repository.get(BuildJobId("5" * 32))
            summary = repository.diagnostics().to_public_dict()

            self.assertEqual([item.job_id for item in page.jobs], [snapshot.job_id])
            self.assertIsNone(missing)
            self.assertEqual(summary["warning_count"], 1)
            self.assertEqual(summary["warning_codes"], ["BUILD_JOB_STORE_CORRUPT_RECORD"])
            self.assertNotIn("secret-value", json.dumps(summary, ensure_ascii=False))

    def test_invalid_job_envelope_is_skipped_and_reported_safely(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            repository = _repository(root)
            snapshot = _submit(repository, "7" * 32)
            valid_path = root / "build_jobs.d" / "jobs" / f"{snapshot.job_id}.json"
            invalid_payload = json.loads(valid_path.read_text(encoding="utf-8"))
            invalid_payload["snapshot"]["job_id"] = "8" * 32
            invalid_payload["snapshot"]["status"] = "not-a-status"
            invalid_payload["snapshot"]["request_id"] = "secret-invalid-status"
            invalid_path = root / "build_jobs.d" / "jobs" / f"{'8' * 32}.json"
            invalid_path.write_text(json.dumps(invalid_payload), encoding="utf-8")

            page = repository.list_page(BuildJobListQuery(limit=10))
            missing = repository.get(BuildJobId("8" * 32))
            summary = repository.diagnostics().to_public_dict()

            self.assertEqual([item.job_id for item in page.jobs], [snapshot.job_id])
            self.assertIsNone(missing)
            self.assertEqual(summary["warning_count"], 1)
            self.assertEqual(summary["warning_codes"], ["BUILD_JOB_STORE_CORRUPT_RECORD"])
            self.assertNotIn("secret-invalid-status", json.dumps(summary, ensure_ascii=False))

    def test_repository_lists_jobs_newest_first_with_cursor(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            clock = MutableClock()
            repository = FileBuildJobRepository(
                str(Path(temp_dir) / "build_jobs.json"),
                now=clock.now,
                settings=BuildJobRepositorySettings(
                    retention_limit=100,
                    list_default_limit=2,
                    list_max_limit=2,
                ),
            )
            for job_id in ("1" * 32, "2" * 32, "3" * 32):
                snapshot = _submit(repository, job_id)
                _succeed(repository, snapshot)
                clock.advance(seconds=1)

            first_page = repository.list_page(BuildJobListQuery(limit=2))
            second_page = repository.list_page(
                BuildJobListQuery(limit=2, cursor=first_page.next_cursor)
            )

            self.assertEqual(
                [job.job_id for job in first_page.jobs],
                [BuildJobId("3" * 32), BuildJobId("2" * 32)],
            )
            self.assertTrue(first_page.next_cursor)
            self.assertEqual([job.job_id for job in second_page.jobs], [BuildJobId("1" * 32)])
            self.assertEqual(second_page.next_cursor, "")

    def test_repository_rejects_job_file_with_mismatched_payload_id(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            repository = _repository(root)
            snapshot = _submit(repository, "b" * 32)
            source_path = root / "build_jobs.d" / "jobs" / f"{snapshot.job_id}.json"
            mismatched_path = root / "build_jobs.d" / "jobs" / f"{'a' * 32}.json"
            mismatched_path.write_text(source_path.read_text(encoding="utf-8"), encoding="utf-8")

            self.assertIsNone(repository.get(BuildJobId("a" * 32)))
            listed_job_ids = {
                job.job_id for job in repository.list_page(BuildJobListQuery(limit=50)).jobs
            }
            summary = repository.diagnostics().to_public_dict()

            self.assertNotIn(BuildJobId("a" * 32), listed_job_ids)
            self.assertIn(BuildJobId("b" * 32), listed_job_ids)
            self.assertEqual(summary["warning_count"], 1)
            self.assertIn("BUILD_JOB_STORE_CORRUPT_RECORD", summary["warning_codes"])

    def test_repository_deduplicates_corruption_warning_for_same_record(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            repository = _repository(root)
            job_id = BuildJobId("a" * 32)
            job_path = root / "build_jobs.d" / "jobs" / f"{job_id}.json"
            job_path.write_text("not json", encoding="utf-8")

            self.assertIsNone(repository.get(job_id))
            self.assertIsNone(repository.get(job_id))

            self.assertEqual(repository.diagnostics().to_public_dict()["warning_count"], 1)

    def test_repository_writes_one_job_envelope_and_preserves_legacy_store_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            legacy_path = root / "build_jobs.json"
            legacy_path.write_text(
                json.dumps({"schema_version": "legacy", "jobs": []}),
                encoding="utf-8",
            )
            original_legacy_text = legacy_path.read_text(encoding="utf-8")
            repository = _repository(
                root,
                settings=BuildJobRepositorySettings(
                    retention_limit=100,
                    list_default_limit=50,
                    list_max_limit=100,
                ),
            )

            snapshot = _submit(repository, "a" * 32)

            job_path = root / "build_jobs.d" / "jobs" / f"{'a' * 32}.json"
            self.assertEqual(snapshot.job_id, BuildJobId("a" * 32))
            self.assertTrue(job_path.exists())
            self.assertEqual(legacy_path.read_text(encoding="utf-8"), original_legacy_text)
            stored_job = json.loads(job_path.read_text(encoding="utf-8"))
            self.assertEqual(stored_job["schema_version"], 3)
            self.assertEqual(stored_job["snapshot"]["status"], "queued")


if __name__ == "__main__":
    unittest.main()
