"""Pydantic models for API health, diagnostics, and stats responses."""

from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from ...runtime.json_types import JsonObject
from .build_models import ArtifactManifestResponseModel


class DiagnosticsMode(str, Enum):
    build = "build"
    serve = "serve"


class HealthResponseModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str = "ok"
    build_initialized: bool
    serving_initialized: bool
    artifacts_ready: bool
    system_ready: bool
    retrieval_engines_initialized: bool
    manifest_health: str


class OperationResponseModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ok: bool = True
    message: str
    diagnostics: Optional[JsonObject] = None
    stats: Optional[JsonObject] = None


class ModelSuiteResponseModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    embedding_model: str = ""
    llm_model: str = ""
    rerank_model: str = ""


class RouteStatsResponseModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    traditional_count: int = 0
    graph_rag_count: int = 0
    combined_count: int = 0
    total_queries: int = 0
    traditional_ratio: Optional[float] = None
    graph_rag_ratio: Optional[float] = None
    combined_ratio: Optional[float] = None


class StartupDiagnosticsPayloadModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: str = ""
    llm_model: str = ""
    embedding_model: str = ""
    rerank_model: str = ""
    trace_enabled: bool = False
    trace_path: str = ""
    trace_stats: JsonObject = Field(default_factory=dict)
    build_initialized: bool = False
    serving_initialized: bool = False
    artifacts_ready: bool = False
    system_ready: bool = False
    retrieval_engines_initialized: bool = False
    manifest: ArtifactManifestResponseModel = Field(default_factory=ArtifactManifestResponseModel)
    build_job_store: JsonObject = Field(default_factory=dict)


class DiagnosticsResponseModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    diagnostics: StartupDiagnosticsPayloadModel


class SystemStatsPayloadModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    initialized: bool = False
    build_initialized: bool = False
    serving_initialized: bool = False
    artifacts_ready: bool = False
    ready: bool = False
    models: ModelSuiteResponseModel = Field(default_factory=ModelSuiteResponseModel)
    trace_stats: JsonObject = Field(default_factory=dict)
    retrieval_runtime_profile: JsonObject = Field(default_factory=dict)
    artifact_manifest: ArtifactManifestResponseModel = Field(
        default_factory=ArtifactManifestResponseModel
    )
    data_stats: JsonObject = Field(default_factory=dict)
    index_stats: JsonObject = Field(default_factory=dict)
    route_stats: RouteStatsResponseModel = Field(default_factory=RouteStatsResponseModel)


class StatsResponseModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stats: SystemStatsPayloadModel


__all__ = [
    "DiagnosticsMode",
    "DiagnosticsResponseModel",
    "HealthResponseModel",
    "ModelSuiteResponseModel",
    "OperationResponseModel",
    "RouteStatsResponseModel",
    "StartupDiagnosticsPayloadModel",
    "StatsResponseModel",
    "SystemStatsPayloadModel",
]
