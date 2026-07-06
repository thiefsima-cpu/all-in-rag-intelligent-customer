"""Backend-neutral build-job application errors."""

from __future__ import annotations

from .models import BuildJobId, BuildJobSnapshot


class BuildJobError(RuntimeError):
    pass


class BuildJobNotFoundError(BuildJobError):
    def __init__(self, job_id: BuildJobId) -> None:
        super().__init__(str(job_id))
        self.job_id = job_id


class BuildJobConflictError(BuildJobError):
    def __init__(self, message: str, snapshot: BuildJobSnapshot) -> None:
        super().__init__(message)
        self.snapshot = snapshot


class BuildJobIdempotencyConflictError(BuildJobConflictError):
    pass


class BuildJobInvalidTransitionError(BuildJobError):
    pass


class BuildJobConcurrentUpdateError(BuildJobError):
    pass


class BuildJobLeaseLostError(BuildJobError):
    pass


class BuildJobRepositoryError(BuildJobError):
    pass


class BuildJobDispatchError(BuildJobError):
    pass


__all__ = [
    "BuildJobConcurrentUpdateError",
    "BuildJobConflictError",
    "BuildJobDispatchError",
    "BuildJobError",
    "BuildJobIdempotencyConflictError",
    "BuildJobInvalidTransitionError",
    "BuildJobLeaseLostError",
    "BuildJobNotFoundError",
    "BuildJobRepositoryError",
]
