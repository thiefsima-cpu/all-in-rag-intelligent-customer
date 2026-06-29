"""Pydantic models for build API responses."""

from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from ...runtime.json_types import JsonObject
from .error_models import ErrorCode


class BuildJobType(str, Enum):
    build = "build"
    rebuild = "rebuild"


class BuildJobStatus(str, Enum):
    queued = "queued"
    running = "running"
    succeeded = "succeeded"
    failed = "failed"


class ArtifactManifestResponseModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stage: str = ""
    health: str = ""
    updated_at: str = ""
    collection_name: str = ""
    manifest_path: str = ""
    documents_path: str = ""
    chunks_path: str = ""
    total_documents: int = 0
    total_chunks: int = 0
    vector_rows: int = 0
    cache_hit: bool = False
    last_error: str = ""
    build_metadata: JsonObject = Field(default_factory=dict)
    manifest_version: int = 0
    index_version: str = ""
    collection_base_name: str = ""
    collection_slot: str = ""
    previous_collection_name: str = ""
    published_at: str = ""


class ArtifactRegistryResponseModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    active: ArtifactManifestResponseModel
    candidate: Optional[ArtifactManifestResponseModel] = None
    versions: list[int] = Field(default_factory=list)


class BuildJobResultModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: str = ""
    diagnostics: Optional[JsonObject] = None
    stats: Optional[JsonObject] = None


class BuildJobFailureModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: ErrorCode
    message: str
    request_id: str


class BuildJobPayloadModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_id: str
    request_id: str
    job_type: BuildJobType
    status: BuildJobStatus
    created_at: str
    started_at: str = ""
    finished_at: str = ""
    message: str = ""
    error: Optional[BuildJobFailureModel] = None
    logs: list[str] = Field(default_factory=list)
    result: Optional[BuildJobResultModel] = None


class BuildJobResponseModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job: BuildJobPayloadModel


class BuildJobListResponseModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    jobs: list[BuildJobPayloadModel] = Field(default_factory=list)
    next_cursor: str = ""


__all__ = [
    "ArtifactManifestResponseModel",
    "ArtifactRegistryResponseModel",
    "BuildJobFailureModel",
    "BuildJobListResponseModel",
    "BuildJobPayloadModel",
    "BuildJobResponseModel",
    "BuildJobResultModel",
    "BuildJobStatus",
    "BuildJobType",
]
