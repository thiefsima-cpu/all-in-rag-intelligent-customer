from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from rag_modules.app.build_jobs import (
    BuildJobId,
    BuildJobIdempotencyConflictError,
    BuildJobRepositorySettings,
    BuildJobSubmissionDisposition,
    BuildJobType,
    SubmitBuildJob,
)
from rag_modules.runtime.build_jobs import FileBuildJobRepository

NOW = datetime(2026, 6, 29, tzinfo=timezone.utc)


def _now() -> datetime:
    return NOW


def _repository(root: Path) -> FileBuildJobRepository:
    return FileBuildJobRepository(
        str(root / "build_jobs.json"),
        now=_now,
        settings=BuildJobRepositorySettings(),
    )


def _command(
    job_id: str,
    *,
    request_id: str,
    job_type: BuildJobType = BuildJobType.BUILD,
    idempotency_key: str,
) -> SubmitBuildJob:
    return SubmitBuildJob(
        job_id=BuildJobId(job_id),
        request_id=request_id,
        job_type=job_type,
        idempotency_key=idempotency_key,
    )


class BuildJobRepositoryIdempotencyTests(unittest.TestCase):
    def test_same_idempotency_key_and_job_type_returns_original_job(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            repository = _repository(root)

            first = repository.submit(
                _command("d" * 32, request_id="request-1", idempotency_key="client-key-1")
            )
            repeated = repository.submit(
                _command("e" * 32, request_id="request-2", idempotency_key="client-key-1")
            )

            self.assertEqual(first.disposition, BuildJobSubmissionDisposition.CREATED)
            self.assertEqual(repeated.disposition, BuildJobSubmissionDisposition.REPLAYED)
            self.assertEqual(repeated.snapshot.job_id, first.snapshot.job_id)
            stored_text = "".join(
                path.read_text(encoding="utf-8") for path in (root / "build_jobs.d").rglob("*.json")
            )
            self.assertNotIn("client-key-1", stored_text)

    def test_same_idempotency_key_and_different_job_type_conflicts(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repository = _repository(Path(temp_dir))
            first = repository.submit(
                _command("f" * 32, request_id="request-1", idempotency_key="client-key-2")
            )

            with self.assertRaises(BuildJobIdempotencyConflictError) as caught:
                repository.submit(
                    _command(
                        "1" * 32,
                        request_id="request-2",
                        job_type=BuildJobType.REBUILD,
                        idempotency_key="client-key-2",
                    )
                )

            self.assertEqual(first.snapshot.job_type, BuildJobType.BUILD)
            self.assertEqual(caught.exception.snapshot.job_type, BuildJobType.BUILD)

    def test_missing_idempotency_index_is_repaired_from_job_record(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            repository = _repository(root)
            first = repository.submit(
                _command("a" * 32, request_id="request-1", idempotency_key="repair-key-1")
            )
            for path in (root / "build_jobs.d" / "idempotency").glob("*.json"):
                path.unlink()

            repeated = repository.submit(
                _command("b" * 32, request_id="request-2", idempotency_key="repair-key-1")
            )

            self.assertEqual(repeated.disposition, BuildJobSubmissionDisposition.REPLAYED)
            self.assertEqual(repeated.snapshot.job_id, first.snapshot.job_id)
            self.assertEqual(len(list((root / "build_jobs.d" / "idempotency").glob("*.json"))), 1)

    def test_corrupt_idempotency_index_is_repaired_and_conflicts_on_job_type(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            repository = _repository(root)
            first = repository.submit(
                _command("b" * 32, request_id="request-1", idempotency_key="repair-key-2")
            )
            index_path = next((root / "build_jobs.d" / "idempotency").glob("*.json"))
            index_path.write_text("{broken secret-index-value", encoding="utf-8")

            with self.assertRaises(BuildJobIdempotencyConflictError) as caught:
                repository.submit(
                    _command(
                        "c" * 32,
                        request_id="request-2",
                        job_type=BuildJobType.REBUILD,
                        idempotency_key="repair-key-2",
                    )
                )
            summary_text = json.dumps(repository.diagnostics().to_public_dict(), ensure_ascii=False)

            self.assertEqual(first.snapshot.job_type, BuildJobType.BUILD)
            self.assertEqual(caught.exception.snapshot.job_type, BuildJobType.BUILD)
            self.assertNotIn("secret-index-value", summary_text)


if __name__ == "__main__":
    unittest.main()
