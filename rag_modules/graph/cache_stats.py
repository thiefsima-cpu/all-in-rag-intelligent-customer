"""Persistent graph warmup statistics for GraphRAG retrieval."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List

from ..artifacts import ArtifactManifestStore

GRAPH_CACHE_STATS_SCHEMA_VERSION = "graph-cache-stats-v1"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class GraphCacheStats:
    schema_version: str = GRAPH_CACHE_STATS_SCHEMA_VERSION
    updated_at: str = field(default_factory=_utc_now_iso)
    graph_signature: str = ""
    entity_count: int = 0
    relation_type_count: int = 0
    entities: List[Dict[str, Any]] = field(default_factory=list)
    relation_frequencies: Dict[str, int] = field(default_factory=dict)
    page_size: int = 500
    source: str = "unknown"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "updated_at": self.updated_at,
            "graph_signature": self.graph_signature,
            "entity_count": self.entity_count,
            "relation_type_count": self.relation_type_count,
            "entities": list(self.entities or []),
            "relation_frequencies": dict(self.relation_frequencies or {}),
            "page_size": self.page_size,
            "source": self.source,
        }

    @classmethod
    def from_dict(cls, payload: Dict[str, Any] | None) -> "GraphCacheStats":
        payload = dict(payload or {})
        return cls(
            schema_version=str(payload.get("schema_version") or GRAPH_CACHE_STATS_SCHEMA_VERSION),
            updated_at=str(payload.get("updated_at") or _utc_now_iso()),
            graph_signature=str(payload.get("graph_signature") or ""),
            entity_count=int(payload.get("entity_count") or 0),
            relation_type_count=int(payload.get("relation_type_count") or 0),
            entities=[
                dict(item)
                for item in (payload.get("entities") or [])
                if isinstance(item, dict)
            ],
            relation_frequencies={
                str(key): int(value)
                for key, value in dict(payload.get("relation_frequencies") or {}).items()
            },
            page_size=max(1, int(payload.get("page_size") or 500)),
            source=str(payload.get("source") or "unknown"),
        )


class GraphCacheStatsStore:
    """Persist and load graph warmup statistics."""

    def __init__(self, config):
        storage = config.storage
        index_cache_dir = str(storage.index_cache_dir)
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
                payload = json.load(file)
            return GraphCacheStats.from_dict(payload)
        except Exception:
            return None

    def save(self, stats: GraphCacheStats) -> GraphCacheStats:
        with open(self.path, "w", encoding="utf-8") as file:
            json.dump(stats.to_dict(), file, ensure_ascii=False, indent=2)
        return stats


