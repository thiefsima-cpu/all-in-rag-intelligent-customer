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


class BuildJobRepositoryTests(unittest.TestCase):
    def test_repository_imports_legacy_jobs_once_without_deleting_legacy_file(self) -> None:
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
                        "created_at": "2026-06-28T00:00:00Z",
                        "message": "Knowledge base build completed.",
                    }
                ],
            }
            legacy_path.write_text(json.dumps(legacy_payload), encoding="utf-8")

            first = BuildJobRepository(
                str(legacy_path),
                now=_now,
                settings=BuildJobRepositorySettings(),
            )
            second = BuildJobRepository(
                str(legacy_path),
                now=_now,
                settings=BuildJobRepositorySettings(),
            )

            self.assertEqual(first.get("b" * 32)["status"], "succeeded")
            self.assertEqual(second.get("b" * 32)["status"], "succeeded")
            self.assertTrue(legacy_path.exists())
            metadata = json.loads((root / "build_jobs.d" / "metadata.json").read_text())
            self.assertEqual(metadata["legacy_imports"][0]["path"], str(legacy_path))
            self.assertEqual(metadata["legacy_imports"][0]["status"], "imported")

    def test_repository_reports_parseable_invalid_metadata_safely(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            repository_dir = root / "build_jobs.d"
            repository_dir.mkdir()
            (repository_dir / "metadata.json").write_text("[]", encoding="utf-8")

            repository = BuildJobRepository(str(root / "build_jobs.json"), now=_now)
            summary = repository.corruption_summary()

            self.assertEqual(summary["warning_count"], 1)
            self.assertEqual(summary["warning_codes"], ["BUILD_JOB_STORE_CORRUPT_METADATA"])
            self.assertNotIn(str(root), json.dumps(summary, ensure_ascii=False))

    def test_repository_reports_invalid_legacy_job_entries_safely(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            legacy_path = root / "build_jobs.json"
            legacy_path.write_text(
                json.dumps(
                    {
                        "schema_version": "graph-rag-build-jobs-v2",
                        "jobs": [
                            {
                                "job_id": "d" * 32,
                                "request_id": "valid-legacy",
                                "job_type": "build",
                                "status": "succeeded",
                                "created_at": "2026-06-29T00:00:00Z",
                            },
                            "legacy-secret-value",
                            {"job_id": "", "logs": ["another-secret-value"]},
                        ],
                    }
                ),
                encoding="utf-8",
            )

            repository = BuildJobRepository(str(legacy_path), now=_now)
            summary = repository.corruption_summary()

            self.assertEqual(repository.get("d" * 32)["status"], "succeeded")
            self.assertEqual(summary["warning_count"], 1)
            self.assertEqual(summary["warning_codes"], ["BUILD_JOB_STORE_CORRUPT_LEGACY"])
            dumped_summary = json.dumps(summary, ensure_ascii=False)
            self.assertNotIn("legacy-secret-value", dumped_summary)
            self.assertNotIn("another-secret-value", dumped_summary)

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
