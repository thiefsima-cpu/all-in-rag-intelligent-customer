from __future__ import annotations

import unittest
from datetime import datetime, timezone

from rag_modules.app.build_jobs import (
    BuildJobEvent,
    BuildJobEventType,
    BuildJobId,
    BuildJobInvalidTransitionError,
    BuildJobSnapshot,
    BuildJobStatus,
    BuildJobType,
    JobClaimed,
    JobFailed,
    JobQueued,
    JobStarted,
    WorkerIdentity,
    reduce_build_job,
)

NOW = datetime(2026, 7, 6, tzinfo=timezone.utc)
JOB_ID = BuildJobId("a" * 32)


def _event(event_type, payload, *, revision: int) -> BuildJobEvent:
    return BuildJobEvent(
        event_id=f"event-{revision}",
        job_id=JOB_ID,
        revision=revision,
        event_type=event_type,
        schema_version=1,
        occurred_at=NOW,
        request_id="request-1",
        payload=payload,
    )


class BuildJobDomainTests(unittest.TestCase):
    def test_reducer_creates_queued_snapshot_and_hides_internal_statuses(self) -> None:
        queued = reduce_build_job(
            None,
            _event(
                BuildJobEventType.QUEUED,
                JobQueued(job_type=BuildJobType.BUILD, idempotency_key_hash="hash"),
                revision=1,
            ),
        )

        self.assertEqual(queued.status, BuildJobStatus.QUEUED)
        self.assertEqual(queued.revision, 1)
        self.assertNotIn("idempotency_key_hash", queued.to_public_dict())

    def test_public_projection_sanitizes_errors_and_logs(self) -> None:
        snapshot = BuildJobSnapshot(
            job_id=JOB_ID,
            request_id="request-1",
            job_type=BuildJobType.BUILD,
            status=BuildJobStatus.FAILED,
            revision=4,
            created_at=NOW,
            error={
                "code": "SECRET_BACKEND_ERROR",
                "message": "raw backend secret",
                "request_id": "request-1",
            },
            logs=("raw backend error secret",),
        )

        public = snapshot.to_public_dict()

        self.assertEqual(
            public["error"],
            {
                "code": "BUILD_FAILED",
                "message": "The knowledge-base build failed.",
                "request_id": "request-1",
            },
        )
        self.assertEqual(public["logs"], ["Build failed."])

    def test_terminal_snapshot_rejects_later_event(self) -> None:
        queued = reduce_build_job(
            None,
            _event(
                BuildJobEventType.QUEUED,
                JobQueued(job_type=BuildJobType.BUILD),
                revision=1,
            ),
        )
        claimed = reduce_build_job(
            queued,
            _event(
                BuildJobEventType.CLAIMED,
                JobClaimed(
                    worker=WorkerIdentity("worker-1", "in_process"),
                    lease_token="lease-1",
                    lease_expires_at=NOW,
                ),
                revision=2,
            ),
        )
        started = reduce_build_job(
            claimed,
            _event(
                BuildJobEventType.STARTED,
                JobStarted(worker=WorkerIdentity("worker-1", "in_process")),
                revision=3,
            ),
        )
        failed = reduce_build_job(
            started,
            _event(
                BuildJobEventType.FAILED,
                JobFailed(message="Knowledge base build failed."),
                revision=4,
            ),
        )

        with self.assertRaises(BuildJobInvalidTransitionError):
            reduce_build_job(
                failed,
                _event(
                    BuildJobEventType.STARTED,
                    JobStarted(worker=WorkerIdentity("worker-1", "in_process")),
                    revision=5,
                ),
            )
