"""Idempotency index storage for build-job repositories."""

from __future__ import annotations

import hashlib
import json
import os
import re
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from ....runtime.artifacts import write_json_atomic
from .models import BuildJobRecord

_IDEMPOTENCY_KEY_PATTERN = re.compile(r"[!-~]{1,128}\Z", flags=re.ASCII)
_IDEMPOTENCY_FORBIDDEN_CHARS = frozenset({"/", "\\"})
_VALID_JOB_TYPES = frozenset({"build", "rebuild"})

_WarningRecorder = Callable[[str, str, str], None]
_Now = Callable[[], str]


class BuildJobIdempotencyIndex:
    """Manage hashed idempotency-key index files."""

    def __init__(self, idempotency_dir: str, *, now: _Now, warn: _WarningRecorder) -> None:
        self.idempotency_dir = str(idempotency_dir)
        self._now = now
        self._warn = warn

    @staticmethod
    def validate_key(value: str) -> str:
        key = str(value or "")
        if not key:
            return ""
        if not _IDEMPOTENCY_KEY_PATTERN.fullmatch(key):
            raise ValueError("invalid Idempotency-Key")
        if any(character in key for character in _IDEMPOTENCY_FORBIDDEN_CHARS):
            raise ValueError("invalid Idempotency-Key")
        return key

    @classmethod
    def key_hash(cls, value: str) -> str:
        key = cls.validate_key(value)
        if not key:
            return ""
        return hashlib.sha256(key.encode("utf-8")).hexdigest()

    def index_path(self, key_hash: str) -> str:
        return os.path.join(self.idempotency_dir, f"{key_hash}.json")

    def load(self, key_hash: str) -> dict[str, Any] | None:
        path = self.index_path(key_hash)
        if not os.path.exists(path):
            return None
        try:
            with open(path, "r", encoding="utf-8") as file:
                payload = json.load(file)
            if not isinstance(payload, Mapping):
                self._warn("BUILD_JOB_STORE_CORRUPT_IDEMPOTENCY", "idempotency", key_hash[:12])
                return None
            idempotency = dict(payload)
            if not self.is_valid(key_hash, idempotency):
                self._warn("BUILD_JOB_STORE_CORRUPT_IDEMPOTENCY", "idempotency", key_hash[:12])
                return None
            return idempotency
        except (OSError, TypeError, ValueError):
            self._warn("BUILD_JOB_STORE_CORRUPT_IDEMPOTENCY", "idempotency", key_hash[:12])
            return None

    def write(self, *, key_hash: str, job_id: str, job_type: str) -> None:
        write_json_atomic(
            self.index_path(key_hash),
            {
                "key_hash": key_hash,
                "job_id": job_id,
                "job_type": job_type,
                "created_at": self._now(),
            },
        )

    def remove_for_job(self, job_id: str) -> None:
        if not os.path.isdir(self.idempotency_dir):
            return
        for filename in os.listdir(self.idempotency_dir):
            if not filename.endswith(".json"):
                continue
            path = os.path.join(self.idempotency_dir, filename)
            try:
                with open(path, "r", encoding="utf-8") as file:
                    payload = json.load(file)
                if isinstance(payload, Mapping) and str(payload.get("job_id") or "") == job_id:
                    os.remove(path)
            except (OSError, TypeError, ValueError):
                self._warn(
                    "BUILD_JOB_STORE_CORRUPT_IDEMPOTENCY",
                    "idempotency",
                    filename[:-5][:12],
                )

    def scan(self) -> None:
        if not os.path.isdir(self.idempotency_dir):
            return
        for filename in os.listdir(self.idempotency_dir):
            if filename.endswith(".json"):
                self.load(filename[:-5])

    def repair_from_jobs(
        self,
        key_hash: str,
        jobs: Sequence[BuildJobRecord],
    ) -> BuildJobRecord | None:
        for job in jobs:
            if job.idempotency_key_hash != key_hash:
                continue
            self.write(key_hash=key_hash, job_id=job.job_id, job_type=job.job_type)
            return job
        return None

    @staticmethod
    def is_valid(key_hash: str, payload: Mapping[str, Any]) -> bool:
        return (
            str(payload.get("key_hash") or "") == key_hash
            and bool(str(payload.get("job_id") or ""))
            and str(payload.get("job_type") or "") in _VALID_JOB_TYPES
        )


__all__ = ["BuildJobIdempotencyIndex"]
