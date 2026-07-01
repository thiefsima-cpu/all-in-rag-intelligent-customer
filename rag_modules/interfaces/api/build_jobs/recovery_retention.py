"""Recovery, retention, and legacy import support for build-job repositories."""

from __future__ import annotations

import json
import os
from collections.abc import Callable, Mapping, Sequence

from .idempotency_index import BuildJobIdempotencyIndex
from .models import (
    BUILD_JOB_STORE_SCHEMA_VERSION,
    BuildJobRecord,
    BuildJobRepositorySettings,
    build_failure,
)
from .record_store import BuildJobRecordStore

BUILD_JOB_REPOSITORY_SCHEMA_VERSION = "graph-rag-build-job-repository-v1"
_ACTIVE_JOB_STATUSES = frozenset({"queued", "running"})

_WarningRecorder = Callable[[str, str, str], None]
_Now = Callable[[], str]


class BuildJobRepositoryRecoveryRetention:
    """Coordinate repository metadata, recovery, and retention policies."""

    def __init__(
        self,
        *,
        path: str,
        metadata_path: str,
        settings: BuildJobRepositorySettings,
        now: _Now,
        record_store: BuildJobRecordStore,
        idempotency_index: BuildJobIdempotencyIndex,
        warn: _WarningRecorder,
    ) -> None:
        self.path = str(path)
        self.metadata_path = str(metadata_path)
        self.settings = settings
        self._now = now
        self._record_store = record_store
        self._idempotency_index = idempotency_index
        self._warn = warn

    def apply_retention(self) -> None:
        terminal_jobs = [
            job for job in self._record_store.load_all() if job.status not in _ACTIVE_JOB_STATUSES
        ]
        terminal_jobs.sort(key=lambda item: (item.created_at, item.job_id), reverse=True)
        for job in terminal_jobs[self.settings.retention_limit :]:
            try:
                os.remove(self._record_store.job_path(job.job_id))
            except FileNotFoundError:
                pass
            self._idempotency_index.remove_for_job(job.job_id)

    def scan_for_corruption(self) -> None:
        self.load_metadata()
        self._record_store.load_all()
        self._idempotency_index.scan()

    def active(self) -> BuildJobRecord | None:
        for job in self._record_store.load_all():
            if job.status in _ACTIVE_JOB_STATUSES:
                return job
        return None

    def recover_interrupted(self) -> None:
        for job in self._record_store.load_all():
            if job.status in _ACTIVE_JOB_STATUSES:
                self.mark_interrupted(job)

    def mark_interrupted(self, job: BuildJobRecord) -> None:
        job.status = "failed"
        job.finished_at = self._now()
        job.error = build_failure(job.request_id)
        job.message = "Knowledge base build interrupted by service restart."
        job.logs.append("Build interrupted by service restart.")
        self._record_store.write(job)
        self.apply_retention()

    def import_legacy_store_once(self) -> None:
        metadata = self.load_metadata()
        imports = [
            dict(item)
            for item in list(metadata.get("legacy_imports") or [])
            if isinstance(item, Mapping)
        ]
        if any(item.get("path") == self.path for item in imports):
            return
        if not os.path.exists(self.path):
            self.write_metadata(legacy_imports=imports)
            return
        try:
            with open(self.path, "r", encoding="utf-8") as file:
                payload = json.load(file)
            jobs = payload.get("jobs") if isinstance(payload, Mapping) else None
            if not isinstance(jobs, list):
                self._warn(
                    "BUILD_JOB_STORE_CORRUPT_LEGACY",
                    "legacy",
                    os.path.basename(self.path),
                )
                imports.append({"path": self.path, "status": "corrupt"})
                self.write_metadata(legacy_imports=imports)
                return
            for item in jobs:
                if not isinstance(item, Mapping):
                    self._warn(
                        "BUILD_JOB_STORE_CORRUPT_LEGACY",
                        "legacy",
                        os.path.basename(self.path),
                    )
                    continue
                try:
                    job = BuildJobRecord.from_dict(item)
                except (TypeError, ValueError):
                    self._warn(
                        "BUILD_JOB_STORE_CORRUPT_LEGACY",
                        "legacy",
                        os.path.basename(self.path),
                    )
                    continue
                if not job.job_id:
                    self._warn(
                        "BUILD_JOB_STORE_CORRUPT_LEGACY",
                        "legacy",
                        os.path.basename(self.path),
                    )
                    continue
                if not self._record_store.is_valid_job_record(job):
                    self._warn(
                        "BUILD_JOB_STORE_CORRUPT_LEGACY",
                        "legacy",
                        os.path.basename(self.path),
                    )
                    continue
                if not os.path.exists(self._record_store.job_path(job.job_id)):
                    self._record_store.write(job)
            self.apply_retention()
            imports.append({"path": self.path, "status": "imported"})
            self.write_metadata(legacy_imports=imports)
        except (OSError, TypeError, ValueError):
            self._warn(
                "BUILD_JOB_STORE_CORRUPT_LEGACY",
                "legacy",
                os.path.basename(self.path),
            )
            imports.append({"path": self.path, "status": "corrupt"})
            self.write_metadata(legacy_imports=imports)

    def load_metadata(self) -> dict:
        if not os.path.exists(self.metadata_path):
            return {}
        try:
            with open(self.metadata_path, "r", encoding="utf-8") as file:
                payload = json.load(file)
            if not isinstance(payload, Mapping):
                self._warn(
                    "BUILD_JOB_STORE_CORRUPT_METADATA",
                    "metadata",
                    os.path.basename(self.metadata_path),
                )
                return {}
            metadata = dict(payload)
            legacy_imports = metadata.get("legacy_imports")
            if legacy_imports is None:
                return metadata
            if not isinstance(legacy_imports, list):
                self._warn(
                    "BUILD_JOB_STORE_CORRUPT_METADATA",
                    "metadata",
                    os.path.basename(self.metadata_path),
                )
                metadata["legacy_imports"] = []
                return metadata
            valid_imports: list[dict[str, object]] = []
            for item in legacy_imports:
                if not isinstance(item, Mapping) or not item.get("path"):
                    self._warn(
                        "BUILD_JOB_STORE_CORRUPT_METADATA",
                        "metadata",
                        os.path.basename(self.metadata_path),
                    )
                    continue
                valid_imports.append(dict(item))
            metadata["legacy_imports"] = valid_imports
            return metadata
        except (OSError, TypeError, ValueError):
            self._warn(
                "BUILD_JOB_STORE_CORRUPT_METADATA",
                "metadata",
                os.path.basename(self.metadata_path),
            )
            return {}

    def write_metadata(
        self,
        *,
        legacy_imports: Sequence[Mapping[str, object]] | None = None,
    ) -> None:
        from ....runtime.artifacts import write_json_atomic

        write_json_atomic(
            self.metadata_path,
            {
                "schema_version": BUILD_JOB_REPOSITORY_SCHEMA_VERSION,
                "legacy_schema_version": BUILD_JOB_STORE_SCHEMA_VERSION,
                "legacy_path": self.path,
                "legacy_imports": [dict(item) for item in legacy_imports or []],
            },
        )


__all__ = [
    "BUILD_JOB_REPOSITORY_SCHEMA_VERSION",
    "BuildJobRepositoryRecoveryRetention",
]
