"""Build-job persistence models."""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any, Mapping

BUILD_JOB_STORE_SCHEMA_VERSION = "graph-rag-build-jobs-v1"
BUILD_JOB_LOG_LIMIT = 200


@dataclass(slots=True)
class BuildJobRecord:
    job_id: str
    job_type: str
    status: str
    created_at: str
    started_at: str = ""
    finished_at: str = ""
    message: str = ""
    error: str = ""
    logs: list[str] = field(default_factory=list)
    result: dict | None = None

    def to_dict(self) -> dict:
        return {
            "job_id": self.job_id,
            "job_type": self.job_type,
            "status": self.status,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "message": self.message,
            "error": self.error,
            "logs": list(self.logs),
            "result": copy.deepcopy(self.result),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "BuildJobRecord":
        return cls(
            job_id=str(payload.get("job_id") or ""),
            job_type=str(payload.get("job_type") or "build"),
            status=str(payload.get("status") or "failed"),
            created_at=str(payload.get("created_at") or ""),
            started_at=str(payload.get("started_at") or ""),
            finished_at=str(payload.get("finished_at") or ""),
            message=str(payload.get("message") or ""),
            error=str(payload.get("error") or ""),
            logs=[str(item) for item in list(payload.get("logs") or [])],
            result=(
                copy.deepcopy(dict(payload["result"]))
                if isinstance(payload.get("result"), Mapping)
                else None
            ),
        )


__all__ = ["BUILD_JOB_LOG_LIMIT", "BUILD_JOB_STORE_SCHEMA_VERSION", "BuildJobRecord"]
