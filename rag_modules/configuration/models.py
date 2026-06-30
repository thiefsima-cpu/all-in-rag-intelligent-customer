"""Configuration models for GraphRAG."""

from __future__ import annotations

import os
from typing import Any, Dict, Mapping, Self, cast

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from .model_sections import (
    ApiSettings,
    ConfigSection,
    GenerationSettings,
    GraphSettings,
    ModelSettings,
    ObservabilitySettings,
    QueryPlannerSettings,
    QueryPolicySelectorSettings,
    QuerySemanticAdaptiveTraversalSettings,
    QuerySemanticExtractionSettings,
    QuerySemanticRoutingSettings,
    QuerySemanticScoringSettings,
    QuerySemanticSettings,
    QuerySemanticTraversalSettings,
    QueryUnderstandingSettings,
    RetrievalSettings,
    StorageSettings,
)
from .validation import raise_validation_error

SECTION_TYPES: Dict[str, type[ConfigSection]] = {
    "storage": StorageSettings,
    "models": ModelSettings,
    "retrieval": RetrievalSettings,
    "query_understanding": QueryUnderstandingSettings,
    "generation": GenerationSettings,
    "graph": GraphSettings,
    "observability": ObservabilitySettings,
    "api": ApiSettings,
}
SECTION_ORDER = tuple(SECTION_TYPES.keys())
SECTION_FIELD_NAMES = {
    section_name: tuple(cast(Any, section_type).model_fields)
    for section_name, section_type in SECTION_TYPES.items()
}


def default_domain_payload() -> Dict[str, Dict[str, Any]]:
    return {
        section_name: section_type().to_dict()
        for section_name, section_type in SECTION_TYPES.items()
    }


def _clear_storage_derived_paths_for_overrides(
    domain_payload: Dict[str, Dict[str, Any]],
    overrides: Mapping[str, Any],
) -> None:
    storage_overrides = overrides.get("storage")
    storage_payload = domain_payload.get("storage")
    if not isinstance(storage_overrides, Mapping) or not isinstance(storage_payload, dict):
        return

    index_cache_changed = "index_cache_dir" in storage_overrides
    artifact_manifest_changed = "artifact_manifest_path" in storage_overrides
    if index_cache_changed and not artifact_manifest_changed:
        storage_payload["artifact_manifest_path"] = ""
    if (index_cache_changed or artifact_manifest_changed) and (
        "build_job_store_path" not in storage_overrides
    ):
        storage_payload["build_job_store_path"] = ""


class GraphRAGConfig(BaseModel):
    """Root configuration with true nested domain sections."""

    model_config = ConfigDict(extra="forbid", strict=True, validate_assignment=True)

    storage: StorageSettings = Field(default_factory=StorageSettings)
    models: ModelSettings = Field(default_factory=ModelSettings)
    retrieval: RetrievalSettings = Field(default_factory=RetrievalSettings)
    query_understanding: QueryUnderstandingSettings = Field(
        default_factory=QueryUnderstandingSettings
    )
    generation: GenerationSettings = Field(default_factory=GenerationSettings)
    graph: GraphSettings = Field(default_factory=GraphSettings)
    observability: ObservabilitySettings = Field(default_factory=ObservabilitySettings)
    api: ApiSettings = Field(default_factory=ApiSettings)
    profile_name: str = ""
    profile_path: str = ""
    profile_hash: str = ""

    @model_validator(mode="after")
    def _normalize_derived_storage_fields(self) -> Self:
        configured_milvus_dimension = int(self.storage.milvus_dimension or 0)
        embedding_dimension = int(self.models.embedding_dimension)
        if configured_milvus_dimension and configured_milvus_dimension != embedding_dimension:
            message = (
                "MILVUS_DIMENSION must match EMBEDDING_DIMENSION so the vector store schema "
                "matches the active embedding model."
            )
            raise ValidationError.from_exception_data(
                self.__class__.__name__,
                [
                    {
                        "type": "value_error",
                        "loc": ("storage", "milvus_dimension"),
                        "input": configured_milvus_dimension,
                        "ctx": {"error": ValueError(message)},
                    },
                    {
                        "type": "value_error",
                        "loc": ("models", "embedding_dimension"),
                        "input": embedding_dimension,
                        "ctx": {"error": ValueError(message)},
                    },
                ],
            )

        self.storage.milvus_dimension = embedding_dimension
        if not self.storage.artifact_manifest_path:
            self.storage.artifact_manifest_path = os.path.join(
                self.storage.index_cache_dir,
                "artifact_manifest.json",
            )
        if not self.storage.build_job_store_path:
            self.storage.build_job_store_path = os.path.join(
                os.path.dirname(self.storage.artifact_manifest_path),
                "build_jobs.json",
            )
        return self

    def to_domain_dict(self) -> Dict[str, Dict[str, Any]]:
        return {
            section_name: getattr(self, section_name).to_dict() for section_name in SECTION_ORDER
        }

    def to_dict(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = self.to_domain_dict()
        if self.profile_name:
            payload["profile_name"] = self.profile_name
        if self.profile_path:
            payload["profile_path"] = self.profile_path
        if self.profile_hash:
            payload["profile_hash"] = self.profile_hash
        if payload["models"].get("api_key"):
            payload["models"]["api_key"] = "***"
        if payload["storage"].get("neo4j_password"):
            payload["storage"]["neo4j_password"] = "***"
        if payload["api"].get("access_token"):
            payload["api"]["access_token"] = "***"
        if payload["observability"].get("query_trace_fingerprint_salt"):
            payload["observability"]["query_trace_fingerprint_salt"] = "***"
        return payload

    def with_overrides(self, overrides: Mapping[str, Any]) -> "GraphRAGConfig":
        from .assembly import apply_overrides

        merged = self.to_domain_dict()
        _clear_storage_derived_paths_for_overrides(merged, overrides)
        apply_overrides(merged, overrides)
        try:
            return self.__class__.model_validate(
                {
                    **merged,
                    "profile_name": self.profile_name,
                    "profile_path": self.profile_path,
                    "profile_hash": self.profile_hash,
                }
            )
        except ValidationError as exc:
            raise_validation_error(
                exc,
                source_kind="overrides",
                source="GraphRAGConfig.with_overrides",
            )

    @classmethod
    def from_dict(cls, config_dict: Mapping[str, Any]) -> "GraphRAGConfig":
        if isinstance(config_dict, cls):
            return config_dict

        from .assembly import apply_overrides

        payload = dict(config_dict or {})
        profile_metadata = {
            key: str(payload.pop(key, ""))
            for key in ("profile_name", "profile_path", "profile_hash")
        }
        merged = default_domain_payload()
        apply_overrides(merged, payload)
        try:
            return cls.model_validate({**merged, **profile_metadata})
        except ValidationError as exc:
            raise_validation_error(
                exc,
                source_kind="overrides",
                source="GraphRAGConfig.from_dict",
            )


__all__ = [
    "ApiSettings",
    "ConfigSection",
    "GenerationSettings",
    "GraphRAGConfig",
    "GraphSettings",
    "ModelSettings",
    "ObservabilitySettings",
    "QueryPolicySelectorSettings",
    "QueryPlannerSettings",
    "QuerySemanticAdaptiveTraversalSettings",
    "QuerySemanticExtractionSettings",
    "QuerySemanticRoutingSettings",
    "QuerySemanticScoringSettings",
    "QuerySemanticSettings",
    "QuerySemanticTraversalSettings",
    "QueryUnderstandingSettings",
    "RetrievalSettings",
    "SECTION_FIELD_NAMES",
    "SECTION_ORDER",
    "SECTION_TYPES",
    "StorageSettings",
]
