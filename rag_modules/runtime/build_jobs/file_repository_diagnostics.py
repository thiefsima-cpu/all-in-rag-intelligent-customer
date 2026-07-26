"""Diagnostics scans for file-backed build-job repositories."""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING

from rag_modules.contracts.build_jobs import BuildJobId

from . import file_repository_idempotency as idempotency
from . import file_repository_storage as storage

if TYPE_CHECKING:
    from .file_repository import FileBuildJobRepository


def scan_for_corruption(repository: FileBuildJobRepository) -> None:
    _scan_envelopes(repository, repository.jobs_dir, "job")
    _scan_envelopes(repository, repository.archive_dir, "archive")
    _scan_archive_timestamps(repository)
    idempotency.scan_idempotency_for_corruption(repository)


def _scan_envelopes(repository: FileBuildJobRepository, directory: str, component: str) -> None:
    if not os.path.isdir(directory):
        return
    for path in Path(directory).glob("*.json"):
        try:
            job_id = BuildJobId(path.stem)
        except ValueError:
            storage.record_warning(repository, "BUILD_JOB_STORE_CORRUPT_RECORD", component, path.stem)
            continue
        if component == "job":
            storage.load_envelope(repository, job_id)
        else:
            storage.load_archived_envelope(repository, job_id)
            storage.load_archived_at(repository, job_id)


def _scan_archive_timestamps(repository: FileBuildJobRepository) -> None:
    if not os.path.isdir(repository.archive_dir):
        return
    for path in Path(repository.archive_dir).glob("*.archived-at"):
        try:
            job_id = BuildJobId(path.name.removesuffix(".archived-at"))
        except ValueError:
            storage.record_warning(repository, "BUILD_JOB_STORE_CORRUPT_RECORD", "archive", path.name)
            continue
        storage.load_archived_at(repository, job_id)


__all__ = ["scan_for_corruption"]
