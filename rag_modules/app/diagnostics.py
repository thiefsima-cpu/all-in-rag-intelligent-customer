"""Startup diagnostics for build and serving entrypoints."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from ..runtime.artifacts import ArtifactManifest, artifact_health
from ..runtime.json_types import (
    JsonObject,
    JsonValue,
    coerce_json_float,
    coerce_json_int,
    coerce_json_object,
)

_TRACE_STATS_KEYS = frozenset(
    {
        "enabled",
        "path",
        "sink_type",
        "dropped_events",
        "queued_events",
        "emitted_events",
        "failed_events",
        "async_enabled",
        "written_events",
        "closed",
        "max_queue_size",
    }
)
_INDEX_STATS_KEYS = frozenset(
    {
        "collection_name",
        "active_collection_name",
        "collection_slot",
        "row_count",
        "index_building_progress",
        "stats",
        "error",
    }
)
_ROUTE_STATS_KEYS = frozenset(
    {
        "traditional_count",
        "graph_rag_count",
        "combined_count",
        "total_queries",
        "traditional_ratio",
        "graph_rag_ratio",
        "combined_ratio",
    }
)


@dataclass(slots=True)
class ModelDiagnostics:
    embedding_model: str = ""
    llm_model: str = ""
    rerank_model: str = ""

    def to_dict(self) -> JsonObject:
        return {
            "embedding_model": self.embedding_model,
            "llm_model": self.llm_model,
            "rerank_model": self.rerank_model,
        }


@dataclass(slots=True)
class TraceStatsDiagnostics:
    enabled: bool = False
    path: str = ""
    sink_type: str = ""
    dropped_events: int = 0
    queued_events: int = 0
    emitted_events: int = 0
    failed_events: int = 0
    async_enabled: bool = False
    written_events: int = 0
    closed: bool = False
    max_queue_size: int = 0
    extra: JsonObject = field(default_factory=dict)
    present_keys: frozenset[str] = field(default_factory=frozenset)

    @classmethod
    def from_payload(cls, payload: object) -> "TraceStatsDiagnostics":
        data = coerce_json_object(payload)
        return cls(
            enabled=_coerce_json_bool(data.get("enabled"), False),
            path=str(data.get("path") or ""),
            sink_type=str(data.get("sink_type") or ""),
            dropped_events=coerce_json_int(data.get("dropped_events"), 0),
            queued_events=coerce_json_int(data.get("queued_events"), 0),
            emitted_events=coerce_json_int(data.get("emitted_events"), 0),
            failed_events=coerce_json_int(data.get("failed_events"), 0),
            async_enabled=_coerce_json_bool(data.get("async_enabled"), False),
            written_events=coerce_json_int(data.get("written_events"), 0),
            closed=_coerce_json_bool(data.get("closed"), False),
            max_queue_size=coerce_json_int(data.get("max_queue_size"), 0),
            extra=_extra_payload(data, _TRACE_STATS_KEYS),
            present_keys=frozenset(data),
        )

    def to_dict(self) -> JsonObject:
        payload = dict(self.extra)
        _put_if_present_or_meaningful(payload, self.present_keys, "enabled", self.enabled)
        _put_if_present_or_meaningful(payload, self.present_keys, "path", self.path)
        _put_if_present_or_meaningful(payload, self.present_keys, "sink_type", self.sink_type)
        _put_if_present_or_meaningful(
            payload, self.present_keys, "dropped_events", self.dropped_events
        )
        _put_if_present_or_meaningful(
            payload, self.present_keys, "queued_events", self.queued_events
        )
        _put_if_present_or_meaningful(
            payload, self.present_keys, "emitted_events", self.emitted_events
        )
        _put_if_present_or_meaningful(
            payload, self.present_keys, "failed_events", self.failed_events
        )
        _put_if_present_or_meaningful(
            payload, self.present_keys, "async_enabled", self.async_enabled
        )
        _put_if_present_or_meaningful(
            payload, self.present_keys, "written_events", self.written_events
        )
        _put_if_present_or_meaningful(payload, self.present_keys, "closed", self.closed)
        _put_if_present_or_meaningful(
            payload, self.present_keys, "max_queue_size", self.max_queue_size
        )
        return payload


@dataclass(slots=True)
class DataStatsDiagnostics:
    total_recipes: int = 0
    total_ingredients: int = 0
    total_cooking_steps: int = 0
    total_documents: int = 0
    total_chunks: int = 0
    categories: dict[str, int] = field(default_factory=dict)
    cuisines: dict[str, int] = field(default_factory=dict)
    difficulties: dict[str, int] = field(default_factory=dict)
    avg_content_length: float = 0.0
    avg_chunk_size: float = 0.0

    @classmethod
    def from_payload(cls, payload: object) -> "DataStatsDiagnostics":
        data = coerce_json_object(payload)
        return cls(
            total_recipes=coerce_json_int(data.get("total_recipes"), 0),
            total_ingredients=coerce_json_int(data.get("total_ingredients"), 0),
            total_cooking_steps=coerce_json_int(data.get("total_cooking_steps"), 0),
            total_documents=coerce_json_int(data.get("total_documents"), 0),
            total_chunks=coerce_json_int(data.get("total_chunks"), 0),
            categories=_int_map(data.get("categories")),
            cuisines=_int_map(data.get("cuisines")),
            difficulties=_int_map(data.get("difficulties")),
            avg_content_length=coerce_json_float(data.get("avg_content_length"), 0.0),
            avg_chunk_size=coerce_json_float(data.get("avg_chunk_size"), 0.0),
        )

    def to_dict(self) -> JsonObject:
        return {
            "total_recipes": self.total_recipes,
            "total_ingredients": self.total_ingredients,
            "total_cooking_steps": self.total_cooking_steps,
            "total_documents": self.total_documents,
            "total_chunks": self.total_chunks,
            "categories": dict(self.categories),
            "cuisines": dict(self.cuisines),
            "difficulties": dict(self.difficulties),
            "avg_content_length": self.avg_content_length,
            "avg_chunk_size": self.avg_chunk_size,
        }


@dataclass(slots=True)
class IndexStatsDiagnostics:
    collection_name: str = ""
    active_collection_name: str = ""
    collection_slot: str = ""
    row_count: int = 0
    index_building_progress: int = 0
    stats: JsonObject = field(default_factory=dict)
    error: str = ""
    extra: JsonObject = field(default_factory=dict)
    present_keys: frozenset[str] = field(default_factory=frozenset)

    @classmethod
    def from_payload(cls, payload: object) -> "IndexStatsDiagnostics":
        data = coerce_json_object(payload)
        return cls(
            collection_name=str(data.get("collection_name") or ""),
            active_collection_name=str(data.get("active_collection_name") or ""),
            collection_slot=str(data.get("collection_slot") or ""),
            row_count=coerce_json_int(data.get("row_count"), 0),
            index_building_progress=coerce_json_int(data.get("index_building_progress"), 0),
            stats=coerce_json_object(data.get("stats")),
            error=str(data.get("error") or ""),
            extra=_extra_payload(data, _INDEX_STATS_KEYS),
            present_keys=frozenset(data),
        )

    def to_dict(self) -> JsonObject:
        payload = dict(self.extra)
        _put_if_present_or_meaningful(
            payload, self.present_keys, "collection_name", self.collection_name
        )
        _put_if_present_or_meaningful(
            payload, self.present_keys, "active_collection_name", self.active_collection_name
        )
        _put_if_present_or_meaningful(
            payload, self.present_keys, "collection_slot", self.collection_slot
        )
        _put_if_present_or_meaningful(payload, self.present_keys, "row_count", self.row_count)
        _put_if_present_or_meaningful(
            payload,
            self.present_keys,
            "index_building_progress",
            self.index_building_progress,
        )
        _put_if_present_or_meaningful(payload, self.present_keys, "stats", self.stats)
        _put_if_present_or_meaningful(payload, self.present_keys, "error", self.error)
        return payload


@dataclass(slots=True)
class RouteStatsDiagnostics:
    traditional_count: int = 0
    graph_rag_count: int = 0
    combined_count: int = 0
    total_queries: int = 0
    traditional_ratio: float | None = None
    graph_rag_ratio: float | None = None
    combined_ratio: float | None = None
    extra: JsonObject = field(default_factory=dict)
    present_keys: frozenset[str] = field(default_factory=frozenset)

    @classmethod
    def from_payload(cls, payload: object) -> "RouteStatsDiagnostics":
        data = coerce_json_object(payload)
        return cls(
            traditional_count=coerce_json_int(data.get("traditional_count"), 0),
            graph_rag_count=coerce_json_int(data.get("graph_rag_count"), 0),
            combined_count=coerce_json_int(data.get("combined_count"), 0),
            total_queries=coerce_json_int(data.get("total_queries"), 0),
            traditional_ratio=_optional_json_float(data, "traditional_ratio"),
            graph_rag_ratio=_optional_json_float(data, "graph_rag_ratio"),
            combined_ratio=_optional_json_float(data, "combined_ratio"),
            extra=_extra_payload(data, _ROUTE_STATS_KEYS),
            present_keys=frozenset(data),
        )

    def to_dict(self) -> JsonObject:
        payload = dict(self.extra)
        _put_if_present_or_meaningful(
            payload, self.present_keys, "traditional_count", self.traditional_count
        )
        _put_if_present_or_meaningful(
            payload, self.present_keys, "graph_rag_count", self.graph_rag_count
        )
        _put_if_present_or_meaningful(
            payload, self.present_keys, "combined_count", self.combined_count
        )
        _put_if_present_or_meaningful(
            payload, self.present_keys, "total_queries", self.total_queries
        )
        _put_if_present_or_meaningful(
            payload, self.present_keys, "traditional_ratio", self.traditional_ratio
        )
        _put_if_present_or_meaningful(
            payload, self.present_keys, "graph_rag_ratio", self.graph_rag_ratio
        )
        _put_if_present_or_meaningful(
            payload, self.present_keys, "combined_ratio", self.combined_ratio
        )
        return payload


@dataclass(slots=True)
class ConfigProfileDiagnostics:
    name: str = ""
    path: str = ""
    hash: str = ""

    @property
    def has_values(self) -> bool:
        return bool(self.name or self.path or self.hash)

    @classmethod
    def from_payload(cls, payload: object) -> "ConfigProfileDiagnostics":
        data = coerce_json_object(payload)
        return cls(
            name=str(data.get("name") or ""),
            path=str(data.get("path") or ""),
            hash=str(data.get("hash") or ""),
        )

    def to_dict(self) -> JsonObject:
        return {"name": self.name, "path": self.path, "hash": self.hash}


@dataclass(slots=True)
class ArtifactBuildMetadataDiagnostics:
    config_profile: ConfigProfileDiagnostics = field(default_factory=ConfigProfileDiagnostics)
    extra: JsonObject = field(default_factory=dict)
    config_profile_present: bool = False

    @classmethod
    def from_payload(cls, payload: object) -> "ArtifactBuildMetadataDiagnostics":
        data = coerce_json_object(payload)
        config_profile = ConfigProfileDiagnostics.from_payload(data.get("config_profile"))
        extra = {key: value for key, value in data.items() if key != "config_profile"}
        return cls(
            config_profile=config_profile,
            extra=extra,
            config_profile_present="config_profile" in data,
        )

    def to_dict(self) -> JsonObject:
        payload = dict(self.extra)
        if self.config_profile_present or self.config_profile.has_values:
            payload["config_profile"] = self.config_profile.to_dict()
        return payload


def _int_map(payload: object) -> dict[str, int]:
    data = coerce_json_object(payload)
    return {str(key): coerce_json_int(value, 0) for key, value in data.items()}


def _coerce_json_bool(value: object, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
    return default


def _optional_json_float(data: JsonObject, key: str) -> float | None:
    if key not in data or data[key] is None:
        return None
    return coerce_json_float(data[key], 0.0)


def _extra_payload(data: JsonObject, known_keys: frozenset[str]) -> JsonObject:
    return {key: value for key, value in data.items() if key not in known_keys}


def _put_if_present_or_meaningful(
    payload: JsonObject,
    present_keys: frozenset[str],
    key: str,
    value: JsonValue,
) -> None:
    if key in present_keys or _is_meaningful_json_value(value):
        payload[key] = value


def _is_meaningful_json_value(value: JsonValue) -> bool:
    if value is None:
        return False
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return bool(value)
    return bool(value)


@dataclass(slots=True)
class ArtifactManifestDiagnostics:
    stage: str
    health: str
    updated_at: str
    collection_name: str
    manifest_path: str
    documents_path: str
    chunks_path: str
    total_documents: int
    total_chunks: int
    vector_rows: int
    cache_hit: bool
    last_error: str
    build_metadata: ArtifactBuildMetadataDiagnostics
    manifest_version: int = 0
    index_version: str = ""
    collection_base_name: str = ""
    collection_slot: str = ""
    previous_collection_name: str = ""
    published_at: str = ""

    @classmethod
    def from_manifest(cls, manifest: ArtifactManifest | None) -> "ArtifactManifestDiagnostics":
        manifest = manifest or ArtifactManifest()
        return cls(
            stage=manifest.stage,
            health=artifact_health(manifest),
            updated_at=manifest.updated_at,
            collection_name=manifest.collection_name,
            manifest_path=manifest.manifest_path,
            documents_path=manifest.documents_path,
            chunks_path=manifest.chunks_path,
            total_documents=manifest.total_documents,
            total_chunks=manifest.total_chunks,
            vector_rows=manifest.vector_rows,
            cache_hit=manifest.cache_hit,
            last_error=manifest.last_error,
            build_metadata=ArtifactBuildMetadataDiagnostics.from_payload(manifest.build_metadata),
            manifest_version=manifest.manifest_version,
            index_version=manifest.index_version,
            collection_base_name=manifest.collection_base_name,
            collection_slot=manifest.collection_slot,
            previous_collection_name=manifest.previous_collection_name,
            published_at=manifest.published_at,
        )

    def to_dict(self) -> JsonObject:
        return {
            "stage": self.stage,
            "health": self.health,
            "updated_at": self.updated_at,
            "collection_name": self.collection_name,
            "manifest_path": self.manifest_path,
            "documents_path": self.documents_path,
            "chunks_path": self.chunks_path,
            "total_documents": self.total_documents,
            "total_chunks": self.total_chunks,
            "vector_rows": self.vector_rows,
            "cache_hit": self.cache_hit,
            "last_error": self.last_error,
            "build_metadata": self.build_metadata.to_dict(),
            "manifest_version": self.manifest_version,
            "index_version": self.index_version,
            "collection_base_name": self.collection_base_name,
            "collection_slot": self.collection_slot,
            "previous_collection_name": self.previous_collection_name,
            "published_at": self.published_at,
        }


@dataclass(slots=True)
class StartupDiagnostics:
    mode: str
    llm_model: str
    embedding_model: str
    rerank_model: str
    trace_enabled: bool
    trace_path: str
    trace_stats: TraceStatsDiagnostics
    build_initialized: bool
    serving_initialized: bool
    artifacts_ready: bool
    system_ready: bool
    retrieval_engines_initialized: bool
    manifest: ArtifactManifestDiagnostics

    def to_dict(self) -> JsonObject:
        return {
            "mode": self.mode,
            "llm_model": self.llm_model,
            "embedding_model": self.embedding_model,
            "rerank_model": self.rerank_model,
            "trace_enabled": self.trace_enabled,
            "trace_path": self.trace_path,
            "trace_stats": self.trace_stats.to_dict(),
            "build_initialized": self.build_initialized,
            "serving_initialized": self.serving_initialized,
            "artifacts_ready": self.artifacts_ready,
            "system_ready": self.system_ready,
            "retrieval_engines_initialized": self.retrieval_engines_initialized,
            "manifest": self.manifest.to_dict(),
        }

    def to_lines(self, *, title: Optional[str] = None) -> list[str]:
        heading = title or f"{self.mode.capitalize()} startup diagnostics"
        lines = [
            heading,
            "-" * len(heading),
            (
                f"Models: llm={self.llm_model}, "
                f"embedding={self.embedding_model}, rerank={self.rerank_model}"
            ),
            f"Tracing: {'enabled' if self.trace_enabled else 'disabled'} ({self.trace_path})",
            (
                "Runtime: "
                f"build_initialized={self.build_initialized}, "
                f"serving_initialized={self.serving_initialized}, "
                f"artifacts_ready={self.artifacts_ready}, "
                f"system_ready={self.system_ready}, "
                f"retrieval_engines_initialized={self.retrieval_engines_initialized}"
            ),
            (
                "Manifest: "
                f"health={self.manifest.health}, "
                f"stage={self.manifest.stage}, "
                f"version={self.manifest.manifest_version}, "
                f"slot={self.manifest.collection_slot or 'legacy'}, "
                f"cache_hit={self.manifest.cache_hit}, "
                f"documents={self.manifest.total_documents}, "
                f"chunks={self.manifest.total_chunks}, "
                f"vector_rows={self.manifest.vector_rows}"
            ),
            f"Manifest path: {self.manifest.manifest_path}",
        ]
        if self.manifest.documents_path:
            lines.append(f"Documents cache: {self.manifest.documents_path}")
        if self.manifest.chunks_path:
            lines.append(f"Chunks cache: {self.manifest.chunks_path}")
        lines.append(
            "Trace stats: "
            f"dropped={self.trace_stats.dropped_events}, "
            f"queued={self.trace_stats.queued_events}, "
            f"async_enabled={self.trace_stats.async_enabled}"
        )
        if self.manifest.last_error:
            lines.append(f"Manifest error: {self.manifest.last_error}")
        return lines


@dataclass(slots=True)
class SystemStatsDiagnostics:
    initialized: bool
    build_initialized: bool
    serving_initialized: bool
    artifacts_ready: bool
    ready: bool
    models: ModelDiagnostics
    trace_stats: TraceStatsDiagnostics
    retrieval_runtime_profile: JsonObject
    manifest: ArtifactManifestDiagnostics
    data_stats: DataStatsDiagnostics
    index_stats: IndexStatsDiagnostics
    route_stats: RouteStatsDiagnostics

    def to_dict(self) -> JsonObject:
        return {
            "initialized": self.initialized,
            "build_initialized": self.build_initialized,
            "serving_initialized": self.serving_initialized,
            "artifacts_ready": self.artifacts_ready,
            "ready": self.ready,
            "models": self.models.to_dict(),
            "trace_stats": self.trace_stats.to_dict(),
            "retrieval_runtime_profile": dict(self.retrieval_runtime_profile),
            "artifact_manifest": self.manifest.to_dict(),
            "data_stats": self.data_stats.to_dict(),
            "index_stats": self.index_stats.to_dict(),
            "route_stats": self.route_stats.to_dict(),
        }
