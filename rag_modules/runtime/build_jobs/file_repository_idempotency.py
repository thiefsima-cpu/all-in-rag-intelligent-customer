"""Idempotency index helpers for file-backed build jobs."""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from pathlib import Path
from typing import TYPE_CHECKING

from rag_modules.contracts.build_jobs import BuildJobId, BuildJobSnapshot, BuildJobType, JobQueued
from rag_modules.runtime.artifacts import write_json_atomic

from . import file_repository_storage as storage
from .file_repository_codecs import datetime_from_json

if TYPE_CHECKING:
    from .file_repository import FileBuildJobRepository


def write_idempotency_index(
    repository: FileBuildJobRepository,
    key_hash: str,
    snapshot: BuildJobSnapshot,
) -> None:
    if not key_hash:
        return
    write_json_atomic(
        storage.idempotency_path(repository, key_hash),
        {
            "key_hash": key_hash,
            "job_id": str(snapshot.job_id),
            "job_type": snapshot.job_type.value,
            "created_at": repository._now().isoformat(),
        },
    )


def remove_idempotency_indexes_for_job(
    repository: FileBuildJobRepository,
    job_id: BuildJobId,
) -> None:
    if not os.path.isdir(repository.idempotency_dir):
        return
    for path in Path(repository.idempotency_dir).glob("*.json"):
        try:
            with open(path, "r", encoding="utf-8") as file:
                payload = json.load(file)
            if isinstance(payload, Mapping) and str(payload.get("job_id") or "") == str(job_id):
                os.remove(path)
        except (OSError, TypeError, ValueError):
            storage.record_warning(
                repository,
                "BUILD_JOB_STORE_CORRUPT_IDEMPOTENCY",
                "idempotency",
                path.stem[:12],
            )


def find_idempotent_job(
    repository: FileBuildJobRepository,
    key_hash: str,
) -> BuildJobSnapshot | None:
    if not key_hash:
        return None
    indexed = find_indexed_idempotent_job(repository, key_hash)
    if indexed is not None:
        return indexed
    for envelope in [
        *storage.load_all_envelopes(repository),
        *storage.load_all_archived_envelopes(repository),
    ]:
        queued = envelope.events[0].payload if envelope.events else None
        if isinstance(queued, JobQueued) and queued.idempotency_key_hash == key_hash:
            write_idempotency_index(repository, key_hash, envelope.snapshot)
            return envelope.snapshot
    return None


def find_indexed_idempotent_job(
    repository: FileBuildJobRepository,
    key_hash: str,
) -> BuildJobSnapshot | None:
    path = storage.idempotency_path(repository, key_hash)
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as file:
            payload = json.load(file)
        if not isinstance(payload, Mapping):
            return None
        if str(payload.get("key_hash") or "") != key_hash:
            return None
        job_id = BuildJobId(str(payload.get("job_id") or ""))
        envelope = storage.load_any_envelope(repository, job_id)
        if envelope is None:
            return None
        queued = envelope.events[0].payload if envelope.events else None
        if not isinstance(queued, JobQueued) or queued.idempotency_key_hash != key_hash:
            return None
        return envelope.snapshot
    except (OSError, TypeError, ValueError):
        return None


def scan_idempotency_for_corruption(repository: FileBuildJobRepository) -> None:
    if not os.path.isdir(repository.idempotency_dir):
        return
    for path in Path(repository.idempotency_dir).glob("*.json"):
        try:
            with open(path, "r", encoding="utf-8") as file:
                payload = json.load(file)
            if not isinstance(payload, Mapping):
                raise ValueError("idempotency index must be an object")
            key_hash = str(payload["key_hash"])
            if key_hash != path.stem:
                raise ValueError("idempotency index file name does not match key hash")
            BuildJobId(str(payload["job_id"]))
            BuildJobType(str(payload["job_type"]))
            datetime_from_json(payload["created_at"])
        except (OSError, TypeError, ValueError, KeyError):
            storage.record_warning(
                repository,
                "BUILD_JOB_STORE_CORRUPT_IDEMPOTENCY",
                "idempotency",
                path.stem[:12],
            )


__all__ = [
    "find_idempotent_job",
    "remove_idempotency_indexes_for_job",
    "scan_idempotency_for_corruption",
    "write_idempotency_index",
]
