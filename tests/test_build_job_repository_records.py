from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from rag_modules.interfaces.api.build_jobs import (
    BuildJobRepository,
    BuildJobRepositorySettings,
)


def _now() -> str:
    return "2026-06-29T00:00:00Z"


class BuildJobRepositoryRecordTests(unittest.TestCase):
    def test_corrupt_job_file_is_skipped_and_reported_safely(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            repository = BuildJobRepository(
                str(root / "build_jobs.json"),
                now=_now,
                settings=BuildJobRepositorySettings(),
            )
            created, job, build_lock = repository.create_or_active(
                job_id="4" * 32,
                request_id="request-4",
                job_type="build",
                message="Knowledge base build job queued.",
                idempotency_key="",
            )
            if build_lock is not None:
                build_lock.release()
            self.assertTrue(created)
            corrupt_path = root / "build_jobs.d" / "jobs" / f"{'5' * 32}.json"
            corrupt_path.write_text("{not json with secret-value", encoding="utf-8")

            page = repository.list_page(limit=10, cursor="")
            missing = repository.get("5" * 32)
            summary = repository.corruption_summary()

            self.assertEqual([item["job_id"] for item in page.jobs], [job["job_id"]])
            self.assertIsNone(missing)
            self.assertEqual(summary["warning_count"], 1)
            self.assertEqual(summary["warning_codes"], ["BUILD_JOB_STORE_CORRUPT_RECORD"])
            self.assertNotIn("secret-value", json.dumps(summary, ensure_ascii=False))

    def test_invalid_job_record_is_skipped_and_reported_safely(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            repository = BuildJobRepository(
                str(root / "build_jobs.json"),
                now=_now,
                settings=BuildJobRepositorySettings(),
            )
            created, job, build_lock = repository.create_or_active(
                job_id="7" * 32,
                request_id="request-7",
                job_type="build",
                message="Knowledge base build job queued.",
                idempotency_key="",
            )
            if build_lock is not None:
                build_lock.release()
            self.assertTrue(created)
            invalid_path = root / "build_jobs.d" / "jobs" / f"{'8' * 32}.json"
            invalid_path.write_text(
                json.dumps(
                    {
                        "job_id": "8" * 32,
                        "request_id": "secret-invalid-status",
                        "job_type": "build",
                        "status": "not-a-status",
                        "created_at": "2026-06-29T00:00:00Z",
                    }
                ),
                encoding="utf-8",
            )

            page = repository.list_page(limit=10, cursor="")
            missing = repository.get("8" * 32)
            summary = repository.corruption_summary()

            self.assertEqual([item["job_id"] for item in page.jobs], [job["job_id"]])
            self.assertIsNone(missing)
            self.assertEqual(summary["warning_count"], 1)
            self.assertEqual(summary["warning_codes"], ["BUILD_JOB_STORE_CORRUPT_RECORD"])
            self.assertNotIn("secret-invalid-status", json.dumps(summary, ensure_ascii=False))

    def test_repository_lists_jobs_newest_first_with_cursor(self) -> None:
        created_times = iter(
            [
                "2026-06-29T00:00:00Z",
                "2026-06-29T00:00:01Z",
                "2026-06-29T00:00:02Z",
                "2026-06-29T00:00:03Z",
                "2026-06-29T00:00:04Z",
                "2026-06-29T00:00:05Z",
            ]
        )

        def next_time() -> str:
            return next(created_times)

        with tempfile.TemporaryDirectory() as temp_dir:
            repository = BuildJobRepository(
                str(Path(temp_dir) / "build_jobs.json"),
                now=next_time,
                settings=BuildJobRepositorySettings(
                    retention_limit=100,
                    list_default_limit=2,
                    list_max_limit=2,
                ),
            )
            for job_id in ("1" * 32, "2" * 32, "3" * 32):
                created, job, build_lock = repository.create_or_active(
                    job_id=job_id,
                    request_id=f"request-{job_id[0]}",
                    job_type="build",
                    message="Knowledge base build job queued.",
                    idempotency_key="",
                )
                if build_lock is not None:
                    build_lock.release()
                repository.mark_succeeded(
                    job["job_id"],
                    result={"message": "Knowledge base build completed."},
                )
                self.assertTrue(created)

            first_page = repository.list_page(limit=2, cursor="")
            second_page = repository.list_page(limit=2, cursor=first_page.next_cursor)

            self.assertEqual([job["job_id"] for job in first_page.jobs], ["3" * 32, "2" * 32])
            self.assertTrue(first_page.next_cursor)
            self.assertEqual([job["job_id"] for job in second_page.jobs], ["1" * 32])
            self.assertEqual(second_page.next_cursor, "")

    def test_repository_rejects_job_file_with_mismatched_payload_id(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            legacy_path = root / "build_jobs.json"
            repository = BuildJobRepository(str(legacy_path), now=_now)
            requested_job_id = "a" * 32
            payload_job_id = "b" * 32
            job_path = Path(repository.jobs_dir) / f"{requested_job_id}.json"
            job_path.write_text(
                json.dumps(
                    {
                        "job_id": payload_job_id,
                        "request_id": "request-1",
                        "job_type": "build",
                        "status": "succeeded",
                        "created_at": _now(),
                    }
                ),
                encoding="utf-8",
            )

            self.assertIsNone(repository.get(requested_job_id))
            listed_job_ids = {job["job_id"] for job in repository.list_page(limit=50).jobs}
            summary = repository.corruption_summary()

            self.assertNotIn(payload_job_id, listed_job_ids)
            self.assertEqual(summary["warning_count"], 1)
            self.assertIn("BUILD_JOB_STORE_CORRUPT_RECORD", summary["warning_codes"])

    def test_repository_deduplicates_corruption_warning_for_same_record(self) -> None:
        detected_at_values = iter(
            [
                "2026-06-29T00:00:00Z",
                "2026-06-29T00:00:01Z",
            ]
        )

        def now() -> str:
            return next(detected_at_values)

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            legacy_path = root / "build_jobs.json"
            repository = BuildJobRepository(str(legacy_path), now=now)
            job_id = "a" * 32
            job_path = Path(repository.jobs_dir) / f"{job_id}.json"
            job_path.write_text("not json", encoding="utf-8")

            self.assertIsNone(repository.get(job_id))
            self.assertIsNone(repository.get(job_id))

            self.assertEqual(repository.corruption_summary()["warning_count"], 1)

    def test_repository_writes_one_job_file_and_preserves_legacy_store(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            legacy_path = root / "build_jobs.json"
            legacy_path.write_text(
                json.dumps({"schema_version": "legacy", "jobs": []}),
                encoding="utf-8",
            )
            original_legacy_text = legacy_path.read_text(encoding="utf-8")
            repository = BuildJobRepository(
                str(legacy_path),
                now=_now,
                settings=BuildJobRepositorySettings(
                    retention_limit=100,
                    list_default_limit=50,
                    list_max_limit=100,
                ),
            )

            created, job, build_lock = repository.create_or_active(
                job_id="a" * 32,
                request_id="request-1",
                job_type="build",
                message="Knowledge base build job queued.",
                idempotency_key="",
            )
            try:
                repository.mark_running("a" * 32, message="Knowledge base build started.")
            finally:
                if build_lock is not None:
                    build_lock.release()

            job_path = root / "build_jobs.d" / "jobs" / f"{'a' * 32}.json"
            self.assertTrue(created)
            self.assertEqual(job["job_id"], "a" * 32)
            self.assertTrue(job_path.exists())
            self.assertEqual(legacy_path.read_text(encoding="utf-8"), original_legacy_text)
            stored_job = json.loads(job_path.read_text(encoding="utf-8"))
            self.assertEqual(stored_job["status"], "running")
            self.assertEqual(stored_job["message"], "Knowledge base build started.")


if __name__ == "__main__":
    unittest.main()
