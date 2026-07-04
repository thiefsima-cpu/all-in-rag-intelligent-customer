"""Stats diagnostics DTOs."""

from __future__ import annotations

from dataclasses import dataclass, field

from ..kernel.json_types import (
    JsonObject,
    JsonValue,
    coerce_json_float,
    coerce_json_int,
    coerce_json_object,
)
from .diagnostics_payloads import (
    coerce_json_bool,
    extra_payload,
    int_map,
    optional_json_float,
    put_if_present_or_meaningful,
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
_DATA_STATS_KEYS = frozenset(
    {
        "total_recipes",
        "total_ingredients",
        "total_cooking_steps",
        "total_documents",
        "total_chunks",
        "categories",
        "cuisines",
        "difficulties",
        "avg_content_length",
        "avg_chunk_size",
    }
)
_RETRIEVAL_RUNTIME_PROFILE_KEYS = frozenset(
    {
        "planner",
        "semantics",
        "candidates",
        "candidate_sources",
        "postprocess",
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
            enabled=coerce_json_bool(data.get("enabled"), False),
            path=str(data.get("path") or ""),
            sink_type=str(data.get("sink_type") or ""),
            dropped_events=coerce_json_int(data.get("dropped_events"), 0),
            queued_events=coerce_json_int(data.get("queued_events"), 0),
            emitted_events=coerce_json_int(data.get("emitted_events"), 0),
            failed_events=coerce_json_int(data.get("failed_events"), 0),
            async_enabled=coerce_json_bool(data.get("async_enabled"), False),
            written_events=coerce_json_int(data.get("written_events"), 0),
            closed=coerce_json_bool(data.get("closed"), False),
            max_queue_size=coerce_json_int(data.get("max_queue_size"), 0),
            extra=extra_payload(data, _TRACE_STATS_KEYS),
            present_keys=frozenset(data),
        )

    def to_dict(self) -> JsonObject:
        payload = dict(self.extra)
        put_if_present_or_meaningful(payload, self.present_keys, "enabled", self.enabled)
        put_if_present_or_meaningful(payload, self.present_keys, "path", self.path)
        put_if_present_or_meaningful(payload, self.present_keys, "sink_type", self.sink_type)
        put_if_present_or_meaningful(
            payload, self.present_keys, "dropped_events", self.dropped_events
        )
        put_if_present_or_meaningful(
            payload, self.present_keys, "queued_events", self.queued_events
        )
        put_if_present_or_meaningful(
            payload, self.present_keys, "emitted_events", self.emitted_events
        )
        put_if_present_or_meaningful(
            payload, self.present_keys, "failed_events", self.failed_events
        )
        put_if_present_or_meaningful(
            payload, self.present_keys, "async_enabled", self.async_enabled
        )
        put_if_present_or_meaningful(
            payload, self.present_keys, "written_events", self.written_events
        )
        put_if_present_or_meaningful(payload, self.present_keys, "closed", self.closed)
        put_if_present_or_meaningful(
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
    extra: JsonObject = field(default_factory=dict)
    present_keys: frozenset[str] = field(default_factory=frozenset)

    @classmethod
    def from_payload(cls, payload: object) -> "DataStatsDiagnostics":
        data = coerce_json_object(payload)
        return cls(
            total_recipes=coerce_json_int(data.get("total_recipes"), 0),
            total_ingredients=coerce_json_int(data.get("total_ingredients"), 0),
            total_cooking_steps=coerce_json_int(data.get("total_cooking_steps"), 0),
            total_documents=coerce_json_int(data.get("total_documents"), 0),
            total_chunks=coerce_json_int(data.get("total_chunks"), 0),
            categories=int_map(data.get("categories")),
            cuisines=int_map(data.get("cuisines")),
            difficulties=int_map(data.get("difficulties")),
            avg_content_length=coerce_json_float(data.get("avg_content_length"), 0.0),
            avg_chunk_size=coerce_json_float(data.get("avg_chunk_size"), 0.0),
            extra=extra_payload(data, _DATA_STATS_KEYS),
            present_keys=frozenset(data),
        )

    def to_dict(self) -> JsonObject:
        payload = dict(self.extra)
        put_if_present_or_meaningful(
            payload, self.present_keys, "total_recipes", self.total_recipes
        )
        put_if_present_or_meaningful(
            payload, self.present_keys, "total_ingredients", self.total_ingredients
        )
        put_if_present_or_meaningful(
            payload, self.present_keys, "total_cooking_steps", self.total_cooking_steps
        )
        put_if_present_or_meaningful(
            payload, self.present_keys, "total_documents", self.total_documents
        )
        put_if_present_or_meaningful(payload, self.present_keys, "total_chunks", self.total_chunks)
        put_if_present_or_meaningful(
            payload, self.present_keys, "categories", coerce_json_object(self.categories)
        )
        put_if_present_or_meaningful(
            payload, self.present_keys, "cuisines", coerce_json_object(self.cuisines)
        )
        put_if_present_or_meaningful(
            payload,
            self.present_keys,
            "difficulties",
            coerce_json_object(self.difficulties),
        )
        put_if_present_or_meaningful(
            payload, self.present_keys, "avg_content_length", self.avg_content_length
        )
        put_if_present_or_meaningful(
            payload, self.present_keys, "avg_chunk_size", self.avg_chunk_size
        )
        return payload


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
            extra=extra_payload(data, _INDEX_STATS_KEYS),
            present_keys=frozenset(data),
        )

    def to_dict(self) -> JsonObject:
        payload = dict(self.extra)
        put_if_present_or_meaningful(
            payload, self.present_keys, "collection_name", self.collection_name
        )
        put_if_present_or_meaningful(
            payload, self.present_keys, "active_collection_name", self.active_collection_name
        )
        put_if_present_or_meaningful(
            payload, self.present_keys, "collection_slot", self.collection_slot
        )
        put_if_present_or_meaningful(payload, self.present_keys, "row_count", self.row_count)
        put_if_present_or_meaningful(
            payload,
            self.present_keys,
            "index_building_progress",
            self.index_building_progress,
        )
        put_if_present_or_meaningful(payload, self.present_keys, "stats", self.stats)
        put_if_present_or_meaningful(payload, self.present_keys, "error", self.error)
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
            traditional_ratio=optional_json_float(data, "traditional_ratio"),
            graph_rag_ratio=optional_json_float(data, "graph_rag_ratio"),
            combined_ratio=optional_json_float(data, "combined_ratio"),
            extra=extra_payload(data, _ROUTE_STATS_KEYS),
            present_keys=frozenset(data),
        )

    def to_dict(self) -> JsonObject:
        payload = dict(self.extra)
        put_if_present_or_meaningful(
            payload, self.present_keys, "traditional_count", self.traditional_count
        )
        put_if_present_or_meaningful(
            payload, self.present_keys, "graph_rag_count", self.graph_rag_count
        )
        put_if_present_or_meaningful(
            payload, self.present_keys, "combined_count", self.combined_count
        )
        put_if_present_or_meaningful(
            payload, self.present_keys, "total_queries", self.total_queries
        )
        put_if_present_or_meaningful(
            payload, self.present_keys, "traditional_ratio", self.traditional_ratio
        )
        put_if_present_or_meaningful(
            payload, self.present_keys, "graph_rag_ratio", self.graph_rag_ratio
        )
        put_if_present_or_meaningful(
            payload, self.present_keys, "combined_ratio", self.combined_ratio
        )
        return payload


@dataclass(slots=True)
class RuntimeProfileSectionDiagnostics:
    values: JsonObject = field(default_factory=dict)

    @classmethod
    def from_payload(cls, payload: object) -> "RuntimeProfileSectionDiagnostics":
        return cls(values=coerce_json_object(payload))

    def __getitem__(self, key: str) -> JsonValue:
        return self.values[key]

    def get(self, key: str, default: JsonValue = None) -> JsonValue:
        return self.values.get(key, default)

    def to_dict(self) -> JsonObject:
        return dict(self.values)


@dataclass(slots=True)
class RetrievalRuntimeProfileDiagnostics:
    planner: RuntimeProfileSectionDiagnostics = field(
        default_factory=RuntimeProfileSectionDiagnostics
    )
    semantics: RuntimeProfileSectionDiagnostics = field(
        default_factory=RuntimeProfileSectionDiagnostics
    )
    candidates: RuntimeProfileSectionDiagnostics = field(
        default_factory=RuntimeProfileSectionDiagnostics
    )
    candidate_sources: RuntimeProfileSectionDiagnostics = field(
        default_factory=RuntimeProfileSectionDiagnostics
    )
    postprocess: RuntimeProfileSectionDiagnostics = field(
        default_factory=RuntimeProfileSectionDiagnostics
    )
    extra: JsonObject = field(default_factory=dict)
    present_keys: frozenset[str] = field(default_factory=frozenset)

    @classmethod
    def from_payload(cls, payload: object) -> "RetrievalRuntimeProfileDiagnostics":
        data = coerce_json_object(payload)
        return cls(
            planner=RuntimeProfileSectionDiagnostics.from_payload(data.get("planner")),
            semantics=RuntimeProfileSectionDiagnostics.from_payload(data.get("semantics")),
            candidates=RuntimeProfileSectionDiagnostics.from_payload(data.get("candidates")),
            candidate_sources=RuntimeProfileSectionDiagnostics.from_payload(
                data.get("candidate_sources")
            ),
            postprocess=RuntimeProfileSectionDiagnostics.from_payload(data.get("postprocess")),
            extra=extra_payload(data, _RETRIEVAL_RUNTIME_PROFILE_KEYS),
            present_keys=frozenset(data),
        )

    def to_dict(self) -> JsonObject:
        payload = dict(self.extra)
        put_if_present_or_meaningful(
            payload,
            self.present_keys,
            "planner",
            self.planner.to_dict(),
        )
        put_if_present_or_meaningful(
            payload,
            self.present_keys,
            "semantics",
            self.semantics.to_dict(),
        )
        put_if_present_or_meaningful(
            payload,
            self.present_keys,
            "candidates",
            self.candidates.to_dict(),
        )
        put_if_present_or_meaningful(
            payload,
            self.present_keys,
            "candidate_sources",
            self.candidate_sources.to_dict(),
        )
        put_if_present_or_meaningful(
            payload,
            self.present_keys,
            "postprocess",
            self.postprocess.to_dict(),
        )
        return payload


__all__ = [
    "DataStatsDiagnostics",
    "IndexStatsDiagnostics",
    "ModelDiagnostics",
    "RetrievalRuntimeProfileDiagnostics",
    "RouteStatsDiagnostics",
    "RuntimeProfileSectionDiagnostics",
    "TraceStatsDiagnostics",
]
