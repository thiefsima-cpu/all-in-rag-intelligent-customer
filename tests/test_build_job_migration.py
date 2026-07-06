from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from rag_modules.app.build_jobs import (
    BuildJobId,
    BuildJobRepositoryError,
    BuildJobStatus,
)
from rag_modules.runtime.build_jobs import BuildJobStoreMigrator, FileBuildJobRepository

NOW = datetime(2026, 7, 6, tzinfo=timezone.utc)


def _now() -> datetime:
    return NOW


def _record(
    job_id: str,
    status: str,
    *,
    job_type: str = "build",
    retry_of_job_id: str = "",
) -> dict:
    return {
        "job_id": job_id,
        "request_id": f"request-{job_id[0]}",
        "job_type": job_type,
        "status": status,
        "created_at": NOW.isoformat(),
        "started_at": NOW.isoformat() if status in {"running", "cancel_requested"} else "",
        "finished_at": NOW.isoformat() if status in {"succeeded", "failed", "cancelled"} else "",
        "message": f"legacy {status}",
        "error": {"secret": "raw backend error"} if status == "failed" else None,
        "logs": ["legacy raw error secret"] if status == "failed" else [],
        "result": {"message": f"legacy {status}"} if status in {"succeeded", "cancelled"} else None,
        "idempotency_key_hash": f"hash-{job_id[0]}",
        "retry_of_job_id": retry_of_job_id,
    }


def _write_v2_sources(root: Path) -> None:
    jobs_dir = root / "build_jobs.d" / "jobs"
    jobs_dir.mkdir(parents=True)
    for payload in (
        _record("a" * 32, "succeeded"),
        _record("b" * 32, "failed"),
        _record("c" * 32, "running"),
        _record("d" * 32, "cancelled"),
    ):
        (jobs_dir / f"{payload['job_id']}.json").write_text(
            json.dumps(payload),
            encoding="utf-8",
        )
    (root / "build_jobs.json").write_text(
        json.dumps(
            {
                "schema_version": "graph-rag-build-jobs-v2",
                "jobs": [_record("e" * 32, "queued", retry_of_job_id="9" * 32)],
            }
        ),
        encoding="utf-8",
    )


class BuildJobMigrationTests(unittest.TestCase):
    def test_migrates_v2_records_to_revision_zero_v3_envelopes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_v2_sources(root)

            migrator = BuildJobStoreMigrator(str(root / "build_jobs.json"), now=_now)
            migrator.migrate()
            repository = FileBuildJobRepository(str(root / "build_jobs.json"), now=_now)

            migrated = repository.get(BuildJobId("a" * 32))
            self.assertIsNotNone(migrated)
            assert migrated is not None
            self.assertEqual(migrated.revision, 0)
            self.assertEqual(migrated.status, BuildJobStatus.SUCCEEDED)
            self.assertEqual(
                repository.get(BuildJobId("e" * 32)).retry_of_job_id,
                BuildJobId("9" * 32),
            )
            self.assertEqual(
                repository.find_dispatchable(limit=10),
                (BuildJobId("e" * 32),),
            )
            self.assertTrue((root / "build_jobs.v2.backup").exists())
            self.assertEqual(
                json.loads((root / "build_jobs.d" / "metadata.json").read_text())["schema_version"],
                3,
            )

    def test_migrated_running_job_is_interrupted_by_first_recovery(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_v2_sources(root)
            BuildJobStoreMigrator(str(root / "build_jobs.json"), now=_now).migrate()
            repository = FileBuildJobRepository(str(root / "build_jobs.json"), now=_now)

            running = repository.get(BuildJobId("c" * 32))
            self.assertIsNotNone(running)
            assert running is not None
            self.assertEqual(running.status, BuildJobStatus.RUNNING)

            recovered = repository.recover_expired_leases()

            self.assertEqual([snapshot.job_id for snapshot in recovered], [BuildJobId("c" * 32)])
            self.assertEqual(
                repository.get(BuildJobId("c" * 32)).status,
                BuildJobStatus.INTERRUPTED,
            )

    def test_second_migration_is_noop_when_v3_metadata_exists(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_v2_sources(root)
            migrator = BuildJobStoreMigrator(str(root / "build_jobs.json"), now=_now)
            migrator.migrate()
            first_metadata = (root / "build_jobs.d" / "metadata.json").read_text(encoding="utf-8")

            migrator.migrate()

            self.assertEqual(
                (root / "build_jobs.d" / "metadata.json").read_text(encoding="utf-8"),
                first_metadata,
            )

    def test_malformed_v2_input_raises_and_leaves_sources_untouched(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            jobs_dir = root / "build_jobs.d" / "jobs"
            jobs_dir.mkdir(parents=True)
            corrupt_path = jobs_dir / f"{'f' * 32}.json"
            corrupt_path.write_text("{not json with secret-value", encoding="utf-8")
            original = corrupt_path.read_text(encoding="utf-8")

            with self.assertRaises(BuildJobRepositoryError):
                BuildJobStoreMigrator(str(root / "build_jobs.json"), now=_now).migrate()

            self.assertEqual(corrupt_path.read_text(encoding="utf-8"), original)
            self.assertTrue((root / "build_jobs.d").exists())
            self.assertFalse((root / "build_jobs.v2.backup").exists())

    def test_repository_rejects_unmigrated_v2_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_v2_sources(root)

            with self.assertRaises(BuildJobRepositoryError):
                FileBuildJobRepository(str(root / "build_jobs.json"), now=_now)


if __name__ == "__main__":
    unittest.main()
