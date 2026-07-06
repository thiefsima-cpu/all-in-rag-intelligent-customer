from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from rag_modules.app.build_jobs import (
    BuildJobConcurrentUpdateError,
    BuildJobEvent,
    BuildJobEventType,
    BuildJobId,
    BuildJobRepositorySettings,
    BuildJobSubmissionDisposition,
    BuildJobType,
    JobCancellationRequested,
    SubmitBuildJob,
)
from rag_modules.runtime.build_jobs import FileBuildJobRepository

NOW = datetime(2026, 7, 6, tzinfo=timezone.utc)


def _now() -> datetime:
    return NOW


def _repository(root: Path) -> FileBuildJobRepository:
    return FileBuildJobRepository(
        str(root / "build_jobs.json"),
        now=_now,
        settings=BuildJobRepositorySettings(
            retention_limit=100,
            list_default_limit=50,
            list_max_limit=100,
            lease_seconds=30,
        ),
    )


class BuildJobRepositoryPortTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
