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


class BuildJobRepositoryRecoveryRetentionTests(unittest.TestCase):
    def test_retention_prunes_old_terminal_jobs_and_preserves_active_jobs(self) -> None:
        timestamps = (f"2026-06-29T00:00:{index:02d}Z" for index in range(20))

        def next_time() -> str:
            return next(timestamps)

        with tempfile.TemporaryDirectory() as temp_dir:
            repository = BuildJobRepository(
                str(Path(temp_dir) / "build_jobs.json"),
                now=next_time,
                settings=BuildJobRepositorySettings(
                    retention_limit=1,
                    list_default_limit=10,
                    list_max_limit=10,
                ),
            )
            for job_id in ("1" * 32, "2" * 32):
                created, job, build_lock = repository.create_or_active(
                    job_id=job_id,
                    request_id=f"request-{job_id[0]}",
                    job_type="build",
                    message="Knowledge base build job queued.",
                    idempotency_key=f"key-{job_id[0]}",
                )
                if build_lock is not None:
                    build_lock.release()
                repository.mark_succeeded(
                    job["job_id"],
                    result={"message": "Knowledge base build completed."},
                )
                self.assertTrue(created)

            active_created, active_job, active_lock = repository.create_or_active(
                job_id="3" * 32,
                request_id="request-3",
                job_type="build",
                message="Knowledge base build job queued.",
                idempotency_key="key-3",
            )
            if active_lock is not None:
                active_lock.release()

            page = repository.list_page(limit=10, cursor="")

            self.assertTrue(active_created)
            self.assertIsNone(repository.get("1" * 32))
            self.assertEqual(repository.get("2" * 32)["status"], "succeeded")
            self.assertEqual(repository.get(active_job["job_id"])["status"], "queued")
            self.assertEqual([job["job_id"] for job in page.jobs], ["3" * 32, "2" * 32])
            idempotency_payloads = [
                json.loads(path.read_text(encoding="utf-8"))
                for path in (Path(temp_dir) / "build_jobs.d" / "idempotency").glob("*.json")
            ]
            self.assertEqual(len(idempotency_payloads), 2)
            self.assertNotIn("1" * 32, {payload["job_id"] for payload in idempotency_payloads})

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

    def test_repository_continues_import_after_mapping_legacy_entry_errors(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            legacy_path = root / "build_jobs.json"
            legacy_path.write_text(
                json.dumps(
                    {
                        "schema_version": "graph-rag-build-jobs-v2",
                        "jobs": [
                            {
                                "job_id": "e" * 32,
                                "request_id": "bad-legacy",
                                "job_type": "build",
                                "status": "failed",
                                "created_at": "2026-06-29T00:00:00Z",
                                "logs": 1,
                            },
                            {
                                "job_id": "f" * 32,
                                "request_id": "valid-legacy",
                                "job_type": "build",
                                "status": "succeeded",
                                "created_at": "2026-06-29T00:00:01Z",
                            },
                        ],
                    }
                ),
                encoding="utf-8",
            )

            repository = BuildJobRepository(str(legacy_path), now=_now)
            summary = repository.corruption_summary()

            self.assertIsNone(repository.get("e" * 32))
            self.assertEqual(repository.get("f" * 32)["status"], "succeeded")
            self.assertEqual(summary["warning_count"], 1)
            self.assertEqual(summary["warning_codes"], ["BUILD_JOB_STORE_CORRUPT_LEGACY"])
            self.assertNotIn("bad-legacy", json.dumps(summary, ensure_ascii=False))

    def test_repository_marks_interrupted_active_job_failed_on_startup(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = str(Path(temp_dir) / "build_jobs.json")
            original = BuildJobRepository(path, now=_now, recover_interrupted=False)
            created, job, build_lock = original.create_or_active(
                job_id="a" * 32,
                request_id="request-1",
                job_type="build",
                message="Knowledge base build job queued.",
                idempotency_key="",
            )
            if build_lock is not None:
                build_lock.release()
            self.assertTrue(created)

            recovered = BuildJobRepository(path, now=_now)

            restored = recovered.get(job["job_id"])
            self.assertEqual(restored["status"], "failed")
            self.assertEqual(restored["error"]["code"], "BUILD_FAILED")
            self.assertEqual(restored["logs"], ["Build interrupted by service restart."])


if __name__ == "__main__":
    unittest.main()
