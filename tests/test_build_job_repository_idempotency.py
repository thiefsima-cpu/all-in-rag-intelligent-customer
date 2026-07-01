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


class BuildJobRepositoryIdempotencyTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
