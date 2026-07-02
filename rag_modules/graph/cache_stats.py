"""Persistent graph warmup statistics for GraphRAG retrieval."""

from __future__ import annotations

import json
import os
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone

from ..runtime.artifacts import ArtifactManifestStore
from ..runtime.json_types import JsonObject, coerce_json_int, coerce_json_object

GRAPH_CACHE_STATS_SCHEMA_VERSION = "graph-cache-stats-v1"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(slots=True, frozen=True)
class GraphCacheEntityStats:
    name: str = ""
    label: str = ""
    node_id: str = ""
    labels: tuple[str, ...] = ()
    category: str = ""
    degree: int = 0
    extra: JsonObject = field(default_factory=dict)
    present_keys: frozenset[str] = field(
        default_factory=frozenset,
        compare=False,
        repr=False,
    )

    @classmethod
    def from_payload(cls, payload: object) -> "GraphCacheEntityStats":
        data = coerce_json_object(payload)
        labels = data.get("labels") or ()
        if isinstance(labels, str):
            label_values: tuple[str, ...] = (labels,)
        elif isinstance(labels, Sequence):
            label_values = tuple(str(label) for label in labels if str(label).strip())
        else:
            label_values = ()
        known_keys = {"name", "label", "node_id", "labels", "category", "degree"}
        return cls(
            name=str(data.get("name") or ""),
            label=str(data.get("label") or ""),
            node_id=str(data.get("node_id") or ""),
            labels=label_values,
            category=str(data.get("category") or ""),
            degree=coerce_json_int(data.get("degree"), 0),
            extra={key: value for key, value in data.items() if key not in known_keys},
            present_keys=frozenset(key for key in known_keys if key in data),
        )

    def to_dict(self) -> JsonObject:
        payload = dict(self.extra)
        if self.name or "name" in self.present_keys:
            payload["name"] = self.name
        if self.label or "label" in self.present_keys:
            payload["label"] = self.label
        if self.node_id or "node_id" in self.present_keys:
            payload["node_id"] = self.node_id
        if self.labels or "labels" in self.present_keys:
            payload["labels"] = list(self.labels)
        if self.category or "category" in self.present_keys:
            payload["category"] = self.category
        if self.degree or "degree" in self.present_keys:
            payload["degree"] = self.degree
        return payload


@dataclass
class GraphCacheStats:
    schema_version: str = GRAPH_CACHE_STATS_SCHEMA_VERSION
    updated_at: str = field(default_factory=_utc_now_iso)
    graph_signature: str = ""
    entity_count: int = 0
    relation_type_count: int = 0
    entities: list[GraphCacheEntityStats] = field(default_factory=list)
    relation_frequencies: dict[str, int] = field(default_factory=dict)
    page_size: int = 500
    source: str = "unknown"

    def to_dict(self) -> JsonObject:
        return {
            "schema_version": self.schema_version,
            "updated_at": self.updated_at,
            "graph_signature": self.graph_signature,
            "entity_count": self.entity_count,
            "relation_type_count": self.relation_type_count,
            "entities": [entity.to_dict() for entity in self.entities],
            "relation_frequencies": dict(self.relation_frequencies or {}),
            "page_size": self.page_size,
            "source": self.source,
        }

    @classmethod
    def from_dict(cls, payload: object) -> "GraphCacheStats":
        data = coerce_json_object(payload)
        return cls(
            schema_version=str(data.get("schema_version") or GRAPH_CACHE_STATS_SCHEMA_VERSION),
            updated_at=str(data.get("updated_at") or _utc_now_iso()),
            graph_signature=str(data.get("graph_signature") or ""),
            entity_count=coerce_json_int(data.get("entity_count"), 0),
            relation_type_count=coerce_json_int(data.get("relation_type_count"), 0),
            entities=_entity_stats(data.get("entities")),
            relation_frequencies={
                str(key): coerce_json_int(value, 0)
                for key, value in coerce_json_object(data.get("relation_frequencies")).items()
            },
            page_size=max(1, coerce_json_int(data.get("page_size"), 500)),
            source=str(data.get("source") or "unknown"),
        )


def _entity_stats(payload: object) -> list[GraphCacheEntityStats]:
    if isinstance(payload, Sequence) and not isinstance(payload, (str, bytes, bytearray)):
        return [GraphCacheEntityStats.from_payload(item) for item in payload]
    return []


class GraphCacheStatsStore:
    """Persist and load graph warmup statistics."""

    def __init__(self, config: object) -> None:
        storage = getattr(config, "storage")
        index_cache_dir = str(getattr(storage, "index_cache_dir"))
        manifest_store = ArtifactManifestStore(config)
        default_path = os.path.join(index_cache_dir, "graph_cache_stats.json")
        self.path = os.path.join(
            os.path.dirname(manifest_store.manifest_path) or index_cache_dir,
            os.path.basename(default_path),
        )
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        self.manifest_store = manifest_store

    def expected_graph_signature(self) -> str:
        manifest = self.manifest_store.load()
        return str(manifest.graph_signature or "")

    def load(self) -> GraphCacheStats | None:
        if not os.path.exists(self.path):
            return None
        try:
            with open(self.path, "r", encoding="utf-8") as file:
                payload: object = json.load(file)
            return GraphCacheStats.from_dict(payload)
        except Exception:
            return None

    def save(self, stats: GraphCacheStats) -> GraphCacheStats:
        with open(self.path, "w", encoding="utf-8") as file:
            json.dump(stats.to_dict(), file, ensure_ascii=False, indent=2)
        return stats
