"""Build-job state transition facade backed by the repository."""

from __future__ import annotations

from .file_store import FileBuildJobStore
from .locks import _InterprocessFileLock
from .models import BuildJobListPage, BuildJobRepositorySettings
from .repository import BuildJobRepository


class PersistentBuildJobRegistry:
    """Own build-job state transitions through a durable repository."""

    def __init__(
        self,
        store: FileBuildJobStore,
        *,
        now,
        recover_interrupted: bool = True,
        settings: BuildJobRepositorySettings | None = None,
    ) -> None:
        self.store = store
        self.repository = BuildJobRepository(
            store.path,
            now=now,
            settings=settings,
            recover_interrupted=recover_interrupted,
        )

    def active(self) -> dict | None:
        return self.repository.active()

    def create(self, *, job_id: str, request_id: str, job_type: str, message: str) -> dict:
        created, job, build_lock = self.create_or_active(
            job_id=job_id,
            request_id=request_id,
            job_type=job_type,
            message=message,
        )
        if build_lock is not None:
            build_lock.release()
        if not created:
            raise RuntimeError("A build job is already in progress.")
        if job is None:
            raise RuntimeError("Build job was not created.")
        return job

    def create_or_active(
        self,
        *,
        job_id: str,
        request_id: str,
        job_type: str,
        message: str,
        idempotency_key: str = "",
    ) -> tuple[bool, dict | None, _InterprocessFileLock | None]:
        return self.repository.create_or_active(
            job_id=job_id,
            request_id=request_id,
            job_type=job_type,
            message=message,
            idempotency_key=idempotency_key,
        )

    def list(self) -> list[dict]:
        return list(reversed(self.repository.list_all()))

    def list_page(self, *, limit: int, cursor: str = "") -> BuildJobListPage:
        return self.repository.list_page(limit=limit, cursor=cursor)

    def get(self, job_id: str) -> dict | None:
        return self.repository.get(str(job_id))

    def append_log(self, job_id: str, message: str) -> None:
        self.repository.append_log(job_id, message)

    def mark_running(self, job_id: str, *, message: str) -> None:
        self.repository.mark_running(job_id, message=message)

    def mark_succeeded(self, job_id: str, *, result: dict) -> None:
        self.repository.mark_succeeded(job_id, result=result)

    def mark_failed(self, job_id: str, *, result: dict) -> None:
        self.repository.mark_failed(job_id, result=result)

    def corruption_summary(self) -> dict:
        return self.repository.corruption_summary()


__all__ = ["PersistentBuildJobRegistry"]
