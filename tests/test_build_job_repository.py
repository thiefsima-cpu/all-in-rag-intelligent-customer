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

    def test_same_idempotency_key_and_job_type_returns_original_job(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repository = BuildJobRepository(
                str(Path(temp_dir) / "build_jobs.json"),
                now=_now,
                settings=BuildJobRepositorySettings(),
            )
            created, first_job, first_lock = repository.create_or_active(
                job_id="d" * 32,
                request_id="request-1",
                job_type="build",
                message="Knowledge base build job queued.",
                idempotency_key="client-key-1",
            )
            if first_lock is not None:
                first_lock.release()

            repeated_lock = None
            try:
                repeated, repeated_job, repeated_lock = repository.create_or_active(
                    job_id="e" * 32,
                    request_id="request-2",
                    job_type="build",
                    message="Knowledge base build job queued.",
                    idempotency_key="client-key-1",
                )
            finally:
                if repeated_lock is not None:
                    repeated_lock.release()

            self.assertTrue(created)
            self.assertFalse(repeated)
            self.assertIsNone(repeated_lock)
            self.assertEqual(repeated_job["job_id"], first_job["job_id"])
            stored_text = "".join(
                path.read_text(encoding="utf-8")
                for path in (Path(temp_dir) / "build_jobs.d").rglob("*.json")
            )
            self.assertNotIn("client-key-1", stored_text)

    def test_same_idempotency_key_and_different_job_type_conflicts(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repository = BuildJobRepository(
                str(Path(temp_dir) / "build_jobs.json"),
                now=_now,
                settings=BuildJobRepositorySettings(),
            )
            created, first_job, first_lock = repository.create_or_active(
                job_id="f" * 32,
                request_id="request-1",
                job_type="build",
                message="Knowledge base build job queued.",
                idempotency_key="client-key-2",
            )
            if first_lock is not None:
                first_lock.release()

            second_lock = None
            try:
                with self.assertRaises(ValueError) as caught:
                    _, _, second_lock = repository.create_or_active(
                        job_id="1" * 32,
                        request_id="request-2",
                        job_type="rebuild",
                        message="Knowledge base rebuild job queued.",
                        idempotency_key="client-key-2",
                    )
            finally:
                if second_lock is not None:
                    second_lock.release()

            self.assertTrue(created)
            self.assertEqual(first_job["job_type"], "build")
            self.assertIn("idempotency key already used for build", str(caught.exception))

    def test_missing_idempotency_index_is_repaired_from_job_record(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            repository = BuildJobRepository(
                str(root / "build_jobs.json"),
                now=_now,
                settings=BuildJobRepositorySettings(),
            )
            created, first_job, first_lock = repository.create_or_active(
                job_id="a" * 32,
                request_id="request-1",
                job_type="build",
                message="Knowledge base build job queued.",
                idempotency_key="repair-key-1",
            )
            if first_lock is not None:
                first_lock.release()
            self.assertTrue(created)
            for path in (root / "build_jobs.d" / "idempotency").glob("*.json"):
                path.unlink()

            repeated_lock = None
            try:
                repeated, repeated_job, repeated_lock = repository.create_or_active(
                    job_id="b" * 32,
                    request_id="request-2",
                    job_type="build",
                    message="Knowledge base build job queued.",
                    idempotency_key="repair-key-1",
                )
            finally:
                if repeated_lock is not None:
                    repeated_lock.release()

            self.assertFalse(repeated)
            self.assertIsNone(repeated_lock)
            self.assertEqual(repeated_job["job_id"], first_job["job_id"])
            self.assertEqual(len(list((root / "build_jobs.d" / "idempotency").glob("*.json"))), 1)

    def test_corrupt_idempotency_index_is_repaired_and_conflicts_on_job_type(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            repository = BuildJobRepository(
                str(root / "build_jobs.json"),
                now=_now,
                settings=BuildJobRepositorySettings(),
            )
            created, first_job, first_lock = repository.create_or_active(
                job_id="b" * 32,
                request_id="request-1",
                job_type="build",
                message="Knowledge base build job queued.",
                idempotency_key="repair-key-2",
            )
            if first_lock is not None:
                first_lock.release()
            self.assertTrue(created)
            index_path = next((root / "build_jobs.d" / "idempotency").glob("*.json"))
            index_path.write_text("{broken secret-index-value", encoding="utf-8")

            second_lock = None
            try:
                with self.assertRaises(ValueError) as caught:
                    _, _, second_lock = repository.create_or_active(
                        job_id="c" * 32,
                        request_id="request-2",
                        job_type="rebuild",
                        message="Knowledge base rebuild job queued.",
                        idempotency_key="repair-key-2",
                    )
            finally:
                if second_lock is not None:
                    second_lock.release()
            summary_text = json.dumps(repository.corruption_summary(), ensure_ascii=False)

            self.assertEqual(first_job["job_type"], "build")
            self.assertIn("idempotency key already used for build", str(caught.exception))
            self.assertNotIn("secret-index-value", summary_text)

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
