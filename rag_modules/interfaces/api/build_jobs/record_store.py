"""Job-record file storage for directory-backed build-job repositories."""

from __future__ import annotations

import json
import os
from collections.abc import Callable, Mapping, Sequence

from ....runtime.artifacts import write_json_atomic
from .models import BuildJobRecord

_VALID_JOB_TYPES = frozenset({"build", "rebuild"})
_VALID_JOB_STATUSES = frozenset({"queued", "running", "succeeded", "failed"})
_VALID_RESULT_KEYS = frozenset({"message", "diagnostics", "stats"})

_WarningRecorder = Callable[[str, str, str], None]


class BuildJobRecordStore:
    """Load, validate, and write build-job JSON records."""

    def __init__(
        self,
        jobs_dir: str,
        *,
        legacy_identifier: str,
        warn: _WarningRecorder,
    ) -> None:
        self.jobs_dir = str(jobs_dir)
        self.legacy_identifier = str(legacy_identifier)
        self._warn = warn

    def job_path(self, job_id: str) -> str:
        return os.path.join(self.jobs_dir, f"{job_id}.json")

    def load(self, job_id: str) -> BuildJobRecord | None:
        path = self.job_path(job_id)
        if not os.path.exists(path):
            return None
        try:
            with open(path, "r", encoding="utf-8") as file:
                payload = json.load(file)
            if not isinstance(payload, Mapping):
                self._warn("BUILD_JOB_STORE_CORRUPT_RECORD", "job", job_id)
                return None
            job = BuildJobRecord.from_dict(payload)
            if job.job_id != job_id or not self.is_valid_job_record(job):
                self._warn("BUILD_JOB_STORE_CORRUPT_RECORD", "job", job_id)
                return None
            return job if job.job_id else None
        except (OSError, TypeError, ValueError):
            self._warn("BUILD_JOB_STORE_CORRUPT_RECORD", "job", job_id)
            return None

    def load_all(self) -> list[BuildJobRecord]:
        if not os.path.isdir(self.jobs_dir):
            return []
        jobs: list[BuildJobRecord] = []
        for filename in os.listdir(self.jobs_dir):
            if not filename.endswith(".json"):
                continue
            job = self.load(filename[:-5])
            if job is not None:
                jobs.append(job)
        return jobs

    def require(self, job_id: str) -> BuildJobRecord:
        job = self.load(job_id)
        if job is None:
            raise KeyError(job_id)
        return job

    def write(self, job: BuildJobRecord) -> None:
        write_json_atomic(self.job_path(job.job_id), job.to_dict(include_internal=True))

    def replace(self, jobs: Sequence[Mapping[str, object]]) -> None:
        replacements: dict[str, BuildJobRecord] = {}
        saw_invalid_entry = False
        for item in jobs:
            if not isinstance(item, Mapping):
                saw_invalid_entry = True
                continue
            job = BuildJobRecord.from_dict(item)
            if not job.job_id or not self.is_valid_job_record(job):
                saw_invalid_entry = True
                continue
            replacements[job.job_id] = job
        if os.path.isdir(self.jobs_dir):
            for filename in os.listdir(self.jobs_dir):
                if not filename.endswith(".json"):
                    continue
                job_id = filename[:-5]
                if job_id in replacements:
                    continue
                try:
                    os.remove(self.job_path(job_id))
                except FileNotFoundError:
                    pass
        for job in replacements.values():
            self.write(job)
        if saw_invalid_entry:
            self._warn(
                "BUILD_JOB_STORE_CORRUPT_LEGACY",
                "legacy",
                self.legacy_identifier,
            )

    @staticmethod
    def is_valid_job_record(job: BuildJobRecord) -> bool:
        if job.job_type not in _VALID_JOB_TYPES or job.status not in _VALID_JOB_STATUSES:
            return False
        if job.result is None:
            return True
        if not set(job.result).issubset(_VALID_RESULT_KEYS):
            return False
        message = job.result.get("message")
        if message is not None and not isinstance(message, str):
            return False
        for key in ("diagnostics", "stats"):
            value = job.result.get(key)
            if value is not None and not isinstance(value, Mapping):
                return False
        return True


__all__ = ["BuildJobRecordStore"]
