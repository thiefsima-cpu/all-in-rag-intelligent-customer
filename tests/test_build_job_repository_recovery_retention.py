from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

from rag_modules.app.build_jobs import (
    BuildJobEvent,
    BuildJobEventType,
    BuildJobId,
    BuildJobListQuery,
    BuildJobRepositoryError,
    BuildJobRepositorySettings,
    BuildJobSnapshot,
    BuildJobStatus,
    BuildJobType,
    JobStarted,
    JobSucceeded,
    SubmitBuildJob,
    WorkerIdentity,
)
from rag_modules.runtime.build_jobs import BuildJobStoreMigrator, FileBuildJobRepository

NOW = datetime(2026, 6, 29, tzinfo=timezone.utc)


class MutableClock:
    def __init__(self) -> None:
        self.current = NOW

    def now(self) -> datetime:
        return self.current

    def advance(self, *, seconds: float) -> None:
        self.current += timedelta(seconds=seconds)


def _repository(
    root: Path,
    clock: MutableClock,
    *,
    settings: BuildJobRepositorySettings | None = None,
) -> FileBuildJobRepository:
    return FileBuildJobRepository(
        str(root / "build_jobs.json"),
        now=clock.now,
        settings=settings,
    )


def _event(
    snapshot: BuildJobSnapshot,
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


def _submit(
    repository: FileBuildJobRepository,
    job_id: str,
    *,
    idempotency_key: str = "",
) -> BuildJobSnapshot:
    return repository.submit(
        SubmitBuildJob(
            job_id=BuildJobId(job_id),
            request_id=f"request-{job_id[0]}",
            job_type=BuildJobType.BUILD,
            idempotency_key=idempotency_key,
        )
    ).snapshot


def _succeed(
    repository: FileBuildJobRepository,
    snapshot: BuildJobSnapshot,
    *,
    clock: MutableClock,
) -> None:
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


class BuildJobRepositoryRecoveryRetentionTests(unittest.TestCase):
    def test_retention_archives_old_terminal_jobs_and_preserves_active_jobs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            clock = MutableClock()
            repository = _repository(
                root,
                clock,
                settings=BuildJobRepositorySettings(
                    retention_limit=1,
                    list_default_limit=10,
                    list_max_limit=10,
                ),
            )
            oldest = _submit(repository, "1" * 32, idempotency_key="key-1")
            _succeed(repository, oldest, clock=clock)
            clock.advance(seconds=1)
            newest_terminal = _submit(repository, "2" * 32, idempotency_key="key-2")
            _succeed(repository, newest_terminal, clock=clock)
            clock.advance(seconds=1)
            active = _submit(repository, "3" * 32, idempotency_key="key-3")

            page = repository.list_page(BuildJobListQuery(limit=10))

            self.assertIsNone(repository.get(oldest.job_id))
            self.assertEqual(
                repository.get(newest_terminal.job_id).status, BuildJobStatus.SUCCEEDED
            )
            self.assertEqual(repository.get(active.job_id).status, BuildJobStatus.QUEUED)
            self.assertEqual(
                [job.job_id for job in page.jobs],
                [BuildJobId("3" * 32), BuildJobId("2" * 32)],
            )
            idempotency_payloads = [
                json.loads(path.read_text(encoding="utf-8"))
                for path in (root / "build_jobs.d" / "idempotency").glob("*.json")
            ]
            self.assertEqual(len(idempotency_payloads), 3)
            self.assertIn(str(oldest.job_id), {payload["job_id"] for payload in idempotency_payloads})
            self.assertTrue(
                (root / "build_jobs.d" / "archive" / f"{oldest.job_id}.json").exists()
            )

    def test_repository_requires_explicit_migration_for_legacy_jobs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            legacy_path = root / "build_jobs.json"
            legacy_payload = {
                "schema_version": "graph-rag-build-jobs-v2",
                "jobs": [
                    {
                        "job_id": "b" * 32,
                        "request_id": "legacy-request",
                        "job_type": "build",
                        "status": "succeeded",
                        "created_at": NOW.isoformat(),
                        "message": "Knowledge base build completed.",
                    }
                ],
            }
            legacy_path.write_text(json.dumps(legacy_payload), encoding="utf-8")

            repository_dir = root / "build_jobs.d"
            (repository_dir / "jobs").mkdir(parents=True)
            (repository_dir / "jobs" / f"{'c' * 32}.json").write_text(
                json.dumps(
                    {
                        "job_id": "c" * 32,
                        "request_id": "legacy-v2-file",
                        "job_type": "build",
                        "status": "queued",
                        "created_at": NOW.isoformat(),
                    }
                ),
                encoding="utf-8",
            )

            with self.assertRaises(BuildJobRepositoryError):
                FileBuildJobRepository(str(legacy_path), now=MutableClock().now)

            BuildJobStoreMigrator(str(legacy_path), now=MutableClock().now).migrate()
            migrated = FileBuildJobRepository(str(legacy_path), now=MutableClock().now)

            self.assertEqual(migrated.get(BuildJobId("b" * 32)).status, BuildJobStatus.SUCCEEDED)
            self.assertEqual(migrated.get(BuildJobId("c" * 32)).status, BuildJobStatus.QUEUED)
            self.assertTrue((root / "build_jobs.v2.backup").exists())

    def test_repository_rejects_invalid_metadata_instead_of_guessing(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            repository_dir = root / "build_jobs.d"
            repository_dir.mkdir()
            (repository_dir / "metadata.json").write_text("[]", encoding="utf-8")

            with self.assertRaises(BuildJobRepositoryError):
                FileBuildJobRepository(str(root / "build_jobs.json"), now=MutableClock().now)

    def test_expired_claimed_job_is_interrupted_and_publicly_reported_failed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            clock = MutableClock()
            repository = _repository(
                root,
                clock,
                settings=BuildJobRepositorySettings(lease_seconds=1),
            )
            snapshot = _submit(repository, "a" * 32)
            lease = repository.claim_next(WorkerIdentity("worker-1", "in_process"))
            self.assertIsNotNone(lease)

            clock.advance(seconds=1)
            recovered = repository.recover_expired_leases()

            restored = repository.get(snapshot.job_id)
            self.assertEqual([item.job_id for item in recovered], [snapshot.job_id])
            self.assertIsNotNone(restored)
            assert restored is not None
            self.assertEqual(restored.status, BuildJobStatus.INTERRUPTED)
            self.assertEqual(restored.to_public_dict()["status"], "failed")
            self.assertEqual(
                restored.to_public_dict()["logs"], ["Build interrupted by service restart."]
            )


if __name__ == "__main__":
    unittest.main()
