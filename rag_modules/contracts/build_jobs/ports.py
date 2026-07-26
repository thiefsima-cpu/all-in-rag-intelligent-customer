"""Stable build-job application ports."""

from __future__ import annotations

from typing import Protocol

from .events import BuildJobEvent
from .models import (
    BuildJobEventListQuery,
    BuildJobEventPage,
    BuildJobId,
    BuildJobLease,
    BuildJobListQuery,
    BuildJobPage,
    BuildJobRepositoryDiagnostics,
    BuildJobSnapshot,
    BuildJobSubmission,
    SubmitBuildJob,
    WorkerIdentity,
)


class BuildJobRepositoryPort(Protocol):
    @property
    def list_default_limit(self) -> int: ...

    def submit(self, command: SubmitBuildJob) -> BuildJobSubmission: ...

    def get(self, job_id: BuildJobId) -> BuildJobSnapshot | None: ...

    def list_page(self, query: BuildJobListQuery) -> BuildJobPage: ...

    def list_events(
        self,
        job_id: BuildJobId,
        query: BuildJobEventListQuery,
    ) -> BuildJobEventPage: ...

    def claim_next(self, worker: WorkerIdentity) -> BuildJobLease | None: ...

    def renew_lease(self, lease: BuildJobLease) -> BuildJobLease: ...

    def apply(
        self,
        event: BuildJobEvent,
        *,
        expected_revision: int,
        lease: BuildJobLease | None = None,
    ) -> BuildJobSnapshot: ...

    def find_dispatchable(self, *, limit: int) -> tuple[BuildJobId, ...]: ...

    def recover_expired_leases(self) -> tuple[BuildJobSnapshot, ...]: ...

    def apply_retention(self) -> None: ...

    def diagnostics(self) -> BuildJobRepositoryDiagnostics: ...

    def close(self) -> None: ...


class BuildJobRunnerPort(Protocol):
    def start(self) -> None: ...

    def schedule(self, job_id: BuildJobId) -> None: ...

    def notify_cancellation(self, job_id: BuildJobId) -> None: ...

    def shutdown(self) -> None: ...


__all__ = ["BuildJobRepositoryPort", "BuildJobRunnerPort"]
