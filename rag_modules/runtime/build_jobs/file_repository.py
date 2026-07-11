"""File-backed implementation of the build-job repository port."""

from __future__ import annotations

import os
import threading
from collections.abc import Callable
from datetime import datetime

from rag_modules.contracts.build_jobs import (
    BuildJobEvent,
    BuildJobId,
    BuildJobLease,
    BuildJobListQuery,
    BuildJobPage,
    BuildJobRepositoryDiagnostics,
    BuildJobRepositorySettings,
    BuildJobRepositoryWarning,
    BuildJobSnapshot,
    BuildJobSubmission,
    SubmitBuildJob,
    WorkerIdentity,
)

from . import file_repository_operations as operations
from . import file_repository_storage as storage
from .file_repository_events import (
    hash_idempotency_key,
    new_queued_event,
    validate_idempotency_key,
)

_Now = Callable[[], datetime]


class FileBuildJobRepository:
    """Persist build jobs as V3 event envelopes under a directory."""

    def __init__(
        self,
        path: str,
        *,
        now: _Now,
        settings: BuildJobRepositorySettings | None = None,
    ) -> None:
        self.path = str(path)
        self._now = now
        self.settings = settings or BuildJobRepositorySettings()
        self.repository_dir = self._repository_dir_for_path(self.path)
        self.jobs_dir = os.path.join(self.repository_dir, "jobs")
        self.idempotency_dir = os.path.join(self.repository_dir, "idempotency")
        self.leases_dir = os.path.join(self.repository_dir, "leases")
        self.metadata_path = os.path.join(self.repository_dir, "metadata.json")
        self._store_lock_path = f"{self.path}.lock"
        self._lock = threading.RLock()
        self._warnings: list[BuildJobRepositoryWarning] = []
        storage.ensure_v3_repository_or_empty(self)
        storage.ensure_directories(self)
        storage.write_metadata_if_missing(self)

    @property
    def list_default_limit(self) -> int:
        return self.settings.list_default_limit

    @staticmethod
    def _repository_dir_for_path(path: str) -> str:
        parent = os.path.dirname(path) or "."
        stem, _ = os.path.splitext(os.path.basename(path))
        return os.path.join(parent, f"{stem}.d")

    def submit(self, command: SubmitBuildJob) -> BuildJobSubmission:
        return operations.submit(self, command)

    def get(self, job_id: BuildJobId) -> BuildJobSnapshot | None:
        return operations.get(self, job_id)

    def list_page(self, query: BuildJobListQuery) -> BuildJobPage:
        return operations.list_page(self, query)

    def claim_next(self, worker: WorkerIdentity) -> BuildJobLease | None:
        return operations.claim_next(self, worker)

    def renew_lease(self, lease: BuildJobLease) -> BuildJobLease:
        return operations.renew_lease(self, lease)

    def apply(
        self,
        event: BuildJobEvent,
        *,
        expected_revision: int,
        lease: BuildJobLease | None = None,
    ) -> BuildJobSnapshot:
        return operations.apply(self, event, expected_revision=expected_revision, lease=lease)

    def find_dispatchable(self, *, limit: int) -> tuple[BuildJobId, ...]:
        return operations.find_dispatchable(self, limit=limit)

    def recover_expired_leases(self) -> tuple[BuildJobSnapshot, ...]:
        return operations.recover_expired_leases(self)

    def apply_retention(self) -> None:
        operations.apply_retention(self)

    def diagnostics(self) -> BuildJobRepositoryDiagnostics:
        return operations.diagnostics(self)


__all__ = [
    "FileBuildJobRepository",
    "hash_idempotency_key",
    "new_queued_event",
    "validate_idempotency_key",
]
