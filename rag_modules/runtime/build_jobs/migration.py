"""One-time fail-closed migration from V2 build-job storage to V3 envelopes."""

from __future__ import annotations

import copy
import json
import os
import shutil
from collections.abc import Callable, Mapping
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from rag_modules.contracts.build_jobs import (
    BuildJobId,
    BuildJobRepositoryError,
    BuildJobSnapshot,
    BuildJobStatus,
    BuildJobType,
    WorkerIdentity,
    build_failed_error,
)
from rag_modules.runtime.artifacts import write_json_atomic

from .locks import InterprocessFileLock
from .serialization import (
    BUILD_JOB_ENVELOPE_SCHEMA_VERSION,
    BuildJobEnvelope,
    envelope_from_dict,
    envelope_to_dict,
    snapshot_to_dict,
)

_Now = Callable[[], datetime]
_V2_STATUSES = frozenset(
    {"queued", "running", "cancel_requested", "succeeded", "failed", "cancelled"}
)
_V2_JOB_TYPES = frozenset({"build", "rebuild"})


class BuildJobStoreMigrator:
    def __init__(self, path: str, *, now: _Now) -> None:
        self.path = str(path)
        self._now = now
        self.repository_dir = _repository_dir_for_path(self.path)
        self.jobs_dir = os.path.join(self.repository_dir, "jobs")
        self.metadata_path = os.path.join(self.repository_dir, "metadata.json")
        parent = os.path.dirname(self.path) or "."
        self.staging_dir = os.path.join(parent, "build_jobs.v3.staging")
        self.backup_dir = os.path.join(parent, "build_jobs.v2.backup")
        self._lock_path = f"{self.path}.migration.lock"

    def migrate(self) -> None:
        with InterprocessFileLock(self._lock_path):
            if self._v3_metadata_valid():
                return
            if os.path.exists(self.staging_dir):
                raise BuildJobRepositoryError("Build job V3 migration staging already exists.")
            if os.path.exists(self.backup_dir) and os.path.exists(self.repository_dir):
                raise BuildJobRepositoryError("Build job V2 backup already exists.")
            snapshots = self._load_v2_snapshots()
            try:
                self._write_staging(snapshots)
                self._verify_staging()
                self._publish_staging()
            except Exception as exc:
                self._rollback_publication()
                _remove_tree(self.staging_dir)
                if isinstance(exc, BuildJobRepositoryError):
                    raise
                raise BuildJobRepositoryError("Build job V2 migration failed.") from exc

    def _v3_metadata_valid(self) -> bool:
        if not os.path.exists(self.metadata_path):
            return False
        try:
            with open(self.metadata_path, "r", encoding="utf-8") as file:
                metadata = json.load(file)
            return (
                isinstance(metadata, Mapping)
                and int(metadata.get("schema_version", 0)) == BUILD_JOB_ENVELOPE_SCHEMA_VERSION
            )
        except (OSError, TypeError, ValueError):
            return False

    def _load_v2_snapshots(self) -> list[BuildJobSnapshot]:
        records: dict[BuildJobId, BuildJobSnapshot] = {}
        for payload in self._iter_v2_directory_records():
            snapshot = _snapshot_from_v2_record(payload)
            records[snapshot.job_id] = snapshot
        for payload in self._iter_v2_legacy_file_records():
            snapshot = _snapshot_from_v2_record(payload)
            if snapshot.job_id in records and snapshot_to_dict(
                records[snapshot.job_id]
            ) != snapshot_to_dict(snapshot):
                raise BuildJobRepositoryError("Conflicting V2 build job records.")
            records[snapshot.job_id] = snapshot
        return list(records.values())

    def _iter_v2_directory_records(self) -> list[Mapping[str, Any]]:
        if not os.path.isdir(self.jobs_dir):
            return []
        records: list[Mapping[str, Any]] = []
        for path in sorted(Path(self.jobs_dir).glob("*.json")):
            try:
                with open(path, "r", encoding="utf-8") as file:
                    payload = json.load(file)
            except (OSError, TypeError, ValueError) as exc:
                raise BuildJobRepositoryError("Malformed V2 build job record.") from exc
            if not isinstance(payload, Mapping):
                raise BuildJobRepositoryError("Malformed V2 build job record.")
            records.append(payload)
        return records

    def _iter_v2_legacy_file_records(self) -> list[Mapping[str, Any]]:
        if not os.path.exists(self.path):
            return []
        try:
            with open(self.path, "r", encoding="utf-8") as file:
                payload = json.load(file)
        except (OSError, TypeError, ValueError) as exc:
            raise BuildJobRepositoryError("Malformed V2 build job legacy file.") from exc
        if not isinstance(payload, Mapping):
            raise BuildJobRepositoryError("Malformed V2 build job legacy file.")
        jobs = payload.get("jobs", [])
        if not isinstance(jobs, list):
            raise BuildJobRepositoryError("Malformed V2 build job legacy file.")
        records: list[Mapping[str, Any]] = []
        for item in jobs:
            if not isinstance(item, Mapping):
                raise BuildJobRepositoryError("Malformed V2 build job legacy file.")
            records.append(item)
        return records

    def _write_staging(self, snapshots: list[BuildJobSnapshot]) -> None:
        jobs_dir = os.path.join(self.staging_dir, "jobs")
        archive_dir = os.path.join(self.staging_dir, "archive")
        idempotency_dir = os.path.join(self.staging_dir, "idempotency")
        leases_dir = os.path.join(self.staging_dir, "leases")
        os.makedirs(jobs_dir, exist_ok=True)
        os.makedirs(archive_dir, exist_ok=True)
        os.makedirs(idempotency_dir, exist_ok=True)
        os.makedirs(leases_dir, exist_ok=True)
        write_json_atomic(
            os.path.join(self.staging_dir, "metadata.json"),
            {"schema_version": BUILD_JOB_ENVELOPE_SCHEMA_VERSION},
        )
        for snapshot in snapshots:
            envelope = BuildJobEnvelope(
                revision=snapshot.revision,
                baseline=snapshot,
                snapshot=snapshot,
                events=(),
            )
            write_json_atomic(
                os.path.join(jobs_dir, f"{snapshot.job_id}.json"),
                envelope_to_dict(envelope),
            )
            if snapshot.idempotency_key_hash:
                write_json_atomic(
                    os.path.join(idempotency_dir, f"{snapshot.idempotency_key_hash}.json"),
                    {
                        "key_hash": snapshot.idempotency_key_hash,
                        "job_id": str(snapshot.job_id),
                        "job_type": snapshot.job_type.value,
                        "created_at": self._now().isoformat(),
                    },
                )
            if snapshot.status in {BuildJobStatus.RUNNING, BuildJobStatus.CANCEL_REQUESTED}:
                token = f"migrated-expired-{snapshot.job_id}"
                write_json_atomic(
                    os.path.join(leases_dir, f"{snapshot.job_id}.json"),
                    {
                        "job_id": str(snapshot.job_id),
                        "revision": snapshot.revision,
                        "worker": {
                            "worker_id": "migrated-v2",
                            "runner_backend": "in_process",
                        },
                        "lease_token": token,
                        "lease_expires_at": (self._now() - timedelta(seconds=1)).isoformat(),
                    },
                )

    def _verify_staging(self) -> None:
        jobs_dir = os.path.join(self.staging_dir, "jobs")
        for path in sorted(Path(jobs_dir).glob("*.json")):
            with open(path, "r", encoding="utf-8") as file:
                payload = json.load(file)
            if not isinstance(payload, Mapping):
                raise BuildJobRepositoryError("Malformed staged V3 build job envelope.")
            envelope_from_dict(payload)

    def _publish_staging(self) -> None:
        if os.path.exists(self.repository_dir):
            os.replace(self.repository_dir, self.backup_dir)
        os.replace(self.staging_dir, self.repository_dir)

    def _rollback_publication(self) -> None:
        if os.path.exists(self.repository_dir) and not self._v3_metadata_valid():
            _remove_tree(self.repository_dir)
        if os.path.exists(self.backup_dir) and not os.path.exists(self.repository_dir):
            os.replace(self.backup_dir, self.repository_dir)


def _snapshot_from_v2_record(payload: Mapping[str, Any]) -> BuildJobSnapshot:
    try:
        job_id = BuildJobId(str(payload["job_id"]))
        status = BuildJobStatus(str(payload.get("status") or "failed"))
        job_type = BuildJobType(str(payload.get("job_type") or "build"))
        if status.value not in _V2_STATUSES or job_type.value not in _V2_JOB_TYPES:
            raise ValueError
        request_id = str(payload.get("request_id") or "")
        retry_of_job_id = str(payload.get("retry_of_job_id") or "")
        raw_result = payload.get("result")
        raw_logs = payload.get("logs") or []
        if not isinstance(raw_logs, list):
            raise ValueError
        snapshot = BuildJobSnapshot(
            job_id=job_id,
            request_id=request_id,
            job_type=job_type,
            status=status,
            revision=0,
            created_at=_datetime_from_v2(payload.get("created_at")),
            started_at=_optional_datetime_from_v2(payload.get("started_at")),
            finished_at=_optional_datetime_from_v2(payload.get("finished_at")),
            message=str(payload.get("message") or ""),
            error=build_failed_error(request_id) if payload.get("error") else None,
            logs=tuple(_safe_build_log(item) for item in raw_logs),
            result=copy.deepcopy(dict(raw_result)) if isinstance(raw_result, Mapping) else None,
            retry_of_job_id=BuildJobId(retry_of_job_id) if retry_of_job_id else None,
            idempotency_key_hash=str(payload.get("idempotency_key_hash") or ""),
            worker=(
                WorkerIdentity("migrated-v2", "in_process")
                if status in {BuildJobStatus.RUNNING, BuildJobStatus.CANCEL_REQUESTED}
                else None
            ),
            lease_token=(
                f"migrated-expired-{job_id}"
                if status in {BuildJobStatus.RUNNING, BuildJobStatus.CANCEL_REQUESTED}
                else ""
            ),
            lease_expires_at=(
                datetime.fromtimestamp(0, tz=_datetime_from_v2(payload.get("created_at")).tzinfo)
                if status in {BuildJobStatus.RUNNING, BuildJobStatus.CANCEL_REQUESTED}
                else None
            ),
        )
        return snapshot
    except (KeyError, TypeError, ValueError) as exc:
        raise BuildJobRepositoryError("Malformed V2 build job record.") from exc


def _datetime_from_v2(value: object) -> datetime:
    text = str(value or "")
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    return datetime.fromisoformat(text)


def _optional_datetime_from_v2(value: object) -> datetime | None:
    return _datetime_from_v2(value) if value else None


def _safe_build_log(value: object) -> str:
    text = str(value or "")
    lowered = text.lower()
    if "error" in lowered or "fail" in lowered:
        return "Build failed."
    if text in {
        "Build progress updated.",
        "Build failed.",
        "Build interrupted by service restart.",
        "Build cancellation requested.",
        "Build cancelled.",
    }:
        return text
    return "Build progress updated."


def _repository_dir_for_path(path: str) -> str:
    parent = os.path.dirname(path) or "."
    stem, _ = os.path.splitext(os.path.basename(path))
    return os.path.join(parent, f"{stem}.d")


def _remove_tree(path: str) -> None:
    if os.path.exists(path):
        shutil.rmtree(path)


__all__ = ["BuildJobStoreMigrator"]
