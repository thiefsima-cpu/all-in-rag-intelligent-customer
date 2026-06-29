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
