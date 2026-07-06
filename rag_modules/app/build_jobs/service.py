"""Build-job application use cases orchestrated through stable ports."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import datetime, timezone

from .errors import (
    BuildJobConcurrentUpdateError,
    BuildJobConflictError,
    BuildJobDispatchError,
    BuildJobNotFoundError,
)
from .events import BuildJobEvent, BuildJobEventType, JobCancellationRequested
from .models import (
    BuildJobId,
    BuildJobListQuery,
    BuildJobPage,
    BuildJobSnapshot,
    BuildJobStatus,
    BuildJobSubmissionDisposition,
    BuildJobType,
    SubmitBuildJob,
)
from .ports import BuildJobRepositoryPort, BuildJobRunnerPort

_Clock = Callable[[], datetime]
_IdFactory = Callable[[], str]
_DispatchWarningRecorder = Callable[[BuildJobId], None]
_RETRYABLE_STATUSES = frozenset(
    {
        BuildJobStatus.FAILED,
        BuildJobStatus.CANCELLED,
        BuildJobStatus.INTERRUPTED,
    }
)
_TERMINAL_STATUSES = frozenset(
    {
        BuildJobStatus.SUCCEEDED,
        BuildJobStatus.FAILED,
        BuildJobStatus.CANCELLED,
        BuildJobStatus.INTERRUPTED,
    }
)


class BuildJobApplicationService:
    def __init__(
        self,
        *,
        repository: BuildJobRepositoryPort,
        runner: BuildJobRunnerPort,
        new_id: _IdFactory | None = None,
        now: _Clock | None = None,
        record_dispatch_warning: _DispatchWarningRecorder | None = None,
    ) -> None:
        self._repository = repository
        self._runner = runner
        self._new_id = new_id or (lambda: uuid.uuid4().hex)
        self._now = now or (lambda: datetime.now(timezone.utc))
        self._record_dispatch_warning = record_dispatch_warning or (lambda _job_id: None)

    def submit(self, *, rebuild: bool, request_id: str, idempotency_key: str) -> BuildJobSnapshot:
        command = SubmitBuildJob(
            job_id=BuildJobId(self._new_id()),
            request_id=request_id,
            job_type=BuildJobType.REBUILD if rebuild else BuildJobType.BUILD,
            idempotency_key=idempotency_key,
        )
        return self._submit_command(command)

    def retry(
        self,
        job_id: BuildJobId,
        *,
        request_id: str,
        idempotency_key: str,
    ) -> BuildJobSnapshot:
        snapshot = self.get(job_id)
        if snapshot.status not in _RETRYABLE_STATUSES:
            raise BuildJobConflictError(
                "Only failed, cancelled, or interrupted build jobs can be retried.",
                snapshot,
            )
        command = SubmitBuildJob(
            job_id=BuildJobId(self._new_id()),
            request_id=request_id,
            job_type=snapshot.job_type,
            idempotency_key=idempotency_key,
            retry_of_job_id=snapshot.job_id,
        )
        return self._submit_command(command)

    def get(self, job_id: BuildJobId) -> BuildJobSnapshot:
        snapshot = self._repository.get(job_id)
        if snapshot is None:
            raise BuildJobNotFoundError(job_id)
        return snapshot

    def list_page(
        self,
        *,
        limit: int | None = None,
        cursor: str = "",
        status: BuildJobStatus | None = None,
    ) -> BuildJobPage:
        return self._repository.list_page(
            BuildJobListQuery(
                status=status,
                limit=limit or self._repository.list_default_limit,
                cursor=cursor,
            )
        )

    def cancel(self, job_id: BuildJobId) -> BuildJobSnapshot:
        last_conflict: BuildJobConcurrentUpdateError | None = None
        for _attempt in range(3):
            snapshot = self.get(job_id)
            if snapshot.status is BuildJobStatus.CANCELLED:
                return snapshot
            if snapshot.status is BuildJobStatus.CANCEL_REQUESTED:
                return snapshot
            if snapshot.status in _TERMINAL_STATUSES:
                raise BuildJobConflictError("Terminal build jobs cannot be cancelled.", snapshot)
            event = BuildJobEvent(
                event_id=f"{snapshot.job_id}:{snapshot.revision + 1}",
                job_id=snapshot.job_id,
                revision=snapshot.revision + 1,
                event_type=BuildJobEventType.CANCELLATION_REQUESTED,
                schema_version=1,
                occurred_at=self._now(),
                request_id=snapshot.request_id,
                payload=JobCancellationRequested(),
            )
            try:
                updated = self._repository.apply(event, expected_revision=snapshot.revision)
            except BuildJobConcurrentUpdateError as exc:
                last_conflict = exc
                continue
            self._runner.notify_cancellation(snapshot.job_id)
            return updated
        assert last_conflict is not None
        raise last_conflict

    def startup(self) -> tuple[BuildJobSnapshot, ...]:
        recovered = self._repository.recover_expired_leases()
        self._runner.start()
        return recovered

    def shutdown(self) -> None:
        self._runner.shutdown()

    def _submit_command(self, command: SubmitBuildJob) -> BuildJobSnapshot:
        submission = self._repository.submit(command)
        if submission.disposition is BuildJobSubmissionDisposition.CREATED:
            try:
                self._runner.schedule(submission.snapshot.job_id)
            except BuildJobDispatchError:
                self._record_dispatch_warning(submission.snapshot.job_id)
        return submission.snapshot


__all__ = ["BuildJobApplicationService"]
