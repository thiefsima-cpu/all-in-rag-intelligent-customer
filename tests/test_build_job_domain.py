from __future__ import annotations

import json
import unittest
from datetime import datetime, timezone

from rag_modules.app.build_jobs import (
    BuildJobEvent,
    BuildJobEventListQuery,
    BuildJobEventPage,
    BuildJobEventType,
    BuildJobId,
    BuildJobInvalidTransitionError,
    BuildJobRepositoryDiagnostics,
    BuildJobRepositoryError,
    BuildJobRepositorySettings,
    BuildJobRepositoryUnavailableError,
    BuildJobSnapshot,
    BuildJobStatus,
    BuildJobType,
    JobClaimed,
    JobFailed,
    JobQueued,
    JobStarted,
    WorkerIdentity,
    public_build_job_event,
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
    def test_build_job_repository_port_includes_audit_and_close(self) -> None:
        from rag_modules.app.build_jobs import BuildJobRepositoryPort

        methods = {
            name for name, value in vars(BuildJobRepositoryPort).items() if callable(value)
        }

        self.assertTrue({"list_events", "close"} <= methods)

    def test_audit_contract_dtos_are_public_and_default_to_safe_values(self) -> None:
        self.assertEqual(
            BuildJobEventListQuery(),
            BuildJobEventListQuery(limit=None, cursor=""),
        )
        self.assertEqual(BuildJobEventPage(events=()).next_cursor, "")
        self.assertEqual(BuildJobRepositorySettings().audit_retention_days, 90)

    def test_repository_diagnostics_publish_backend_readiness_and_schema_version(self) -> None:
        public = BuildJobRepositoryDiagnostics(
            backend="postgresql",
            ready=False,
            schema_version="build-jobs-v1",
        ).to_public_dict()

        self.assertEqual(
            public,
            {
                "backend": "postgresql",
                "ready": False,
                "schema_version": "build-jobs-v1",
                "warning_count": 0,
                "warning_codes": [],
                "warnings": [],
            },
        )

    def test_repository_diagnostics_redacts_unrecognized_backend_and_schema_values(self) -> None:
        public = BuildJobRepositoryDiagnostics(
            backend="postgresql://user:private-password@db.example/build_jobs",
            schema_version="SELECT * FROM build_jobs WHERE token = 'private-token'",
        ).to_public_dict()

        self.assertEqual(public["backend"], "unknown")
        self.assertEqual(public["schema_version"], "")
        self.assertNotIn("private-password", json.dumps(public))
        self.assertNotIn("private-token", json.dumps(public))

    def test_repository_unavailable_error_is_a_public_repository_error(self) -> None:
        self.assertTrue(issubclass(BuildJobRepositoryUnavailableError, BuildJobRepositoryError))

    def test_public_claim_event_omits_lease_token(self) -> None:
        event = BuildJobEvent(
            event_id=f"{'a' * 32}:2",
            job_id=BuildJobId("a" * 32),
            revision=2,
            event_type=BuildJobEventType.CLAIMED,
            schema_version=1,
            occurred_at=NOW,
            request_id="request-a",
            payload=JobClaimed(
                worker=WorkerIdentity("worker-1", "external_worker"),
                lease_token="private-lease-token",
                lease_expires_at=NOW,
            ),
        )
        public = public_build_job_event(event)

        self.assertEqual(
            public["payload"],
            {
                "worker": {"worker_id": "worker-1", "runner_backend": "external_worker"},
                "lease_expires_at": NOW.isoformat(),
            },
        )
        self.assertNotIn("private-lease-token", json.dumps(public))

    def test_public_failed_event_redacts_terminal_result_details(self) -> None:
        event = BuildJobEvent(
            event_id=f"{'a' * 32}:4",
            job_id=BuildJobId("a" * 32),
            revision=4,
            event_type=BuildJobEventType.FAILED,
            schema_version=1,
            occurred_at=NOW,
            request_id="request-a",
            payload=JobFailed(
                message="private backend failure",
                result={
                    "database_url": "postgres://private-db-secret",
                    "nested": {"token": "private-token"},
                },
            ),
        )

        public = public_build_job_event(event)

        self.assertEqual(
            public["payload"],
            {"message": "Build failed.", "result": {"message": "Build failed."}},
        )
        self.assertNotIn("private-db-secret", json.dumps(public))
        self.assertNotIn("private-token", json.dumps(public))

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

    def test_runner_port_contains_execution_notifications_only(self) -> None:
        from rag_modules.app.build_jobs import BuildJobRepositoryPort, BuildJobRunnerPort

        runner_methods = {
            name for name, value in vars(BuildJobRunnerPort).items() if callable(value)
        }
        repository_methods = {
            name for name, value in vars(BuildJobRepositoryPort).items() if callable(value)
        }

        self.assertEqual(
            runner_methods.intersection({"start", "schedule", "notify_cancellation", "shutdown"}),
            {"start", "schedule", "notify_cancellation", "shutdown"},
        )
        self.assertFalse(runner_methods.intersection({"get", "list_page", "diagnostics", "apply"}))
        self.assertTrue({"submit", "get", "list_page", "claim_next", "apply"} <= repository_methods)
