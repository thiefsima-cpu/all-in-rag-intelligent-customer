"""Graph cache warmup services for GraphRAG retrieval."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Dict, List

from .cache_stats import GraphCacheStats, GraphCacheStatsStore

logger = logging.getLogger(__name__)


@dataclass
class GraphWarmupResult:
    stats: GraphCacheStats = field(default_factory=GraphCacheStats)
    entity_cache: Dict[str, dict] = field(default_factory=dict)
    relation_cache: Dict[str, int] = field(default_factory=dict)


class GraphCacheWarmupService:
    """Load persisted graph stats or collect them with paged warmup scans."""

    def __init__(self, store: GraphCacheStatsStore) -> None:
        self.store = store

    def warm(self, driver, *, database_name: str) -> GraphWarmupResult:
        stats = self._load_or_build_graph_stats(driver, database_name=database_name)
        entity_cache = {
            str(item.get("node_id") or ""): {
                "labels": list(item.get("labels") or []),
                "name": item.get("name"),
                "category": item.get("category"),
                "degree": int(item.get("degree") or 0),
            }
            for item in (stats.entities or [])
            if item.get("node_id")
        }
        relation_cache = {
            str(key): int(value)
            for key, value in dict(stats.relation_frequencies or {}).items()
        }
        return GraphWarmupResult(
            stats=stats,
            entity_cache=entity_cache,
            relation_cache=relation_cache,
        )

    def _load_or_build_graph_stats(self, driver, *, database_name: str) -> GraphCacheStats:
        expected_signature = self.store.expected_graph_signature()
        cached = self.store.load()
        if cached and cached.entities and (
            not expected_signature or cached.graph_signature == expected_signature
        ):
            return cached
        built = self._collect_graph_stats(
            driver,
            database_name=database_name,
            expected_signature=expected_signature,
        )
        return self.store.save(built)

    def _collect_graph_stats(
        self,
        driver,
        *,
        database_name: str,
        expected_signature: str = "",
        page_size: int = 500,
    ) -> GraphCacheStats:
        entities: List[dict] = []
        relation_frequencies: dict[str, int] = {}
        page_cursor = ""
        with driver.session(database=database_name) as session:
            while True:
                entity_query = """
                MATCH (n)
                WHERE n.nodeId IS NOT NULL
                  AND ($after_node_id = '' OR n.nodeId > $after_node_id)
                WITH n
                ORDER BY n.nodeId
                LIMIT $limit
                WITH collect(n) AS nodes
                UNWIND nodes AS n
                WITH n, COUNT { (n)--() } AS degree
                RETURN labels(n) AS node_labels,
                       n.nodeId AS node_id,
                       n.name AS name,
                       n.category AS category,
                       degree
                ORDER BY node_id
                """
                page_records = list(
                    session.run(
                        entity_query,
                        {"after_node_id": page_cursor, "limit": max(1, int(page_size))},
                    )
                )
                if not page_records:
                    break
                for record in page_records:
                    entities.append(
                        {
                            "node_id": str(record["node_id"] or ""),
                            "labels": list(record["node_labels"] or []),
                            "name": record["name"],
                            "category": record["category"],
                            "degree": int(record["degree"] or 0),
                        }
                    )
                page_cursor = str(page_records[-1]["node_id"] or "")

            relation_query = """
            MATCH ()-[r]->()
            RETURN type(r) AS rel_type, count(r) AS frequency
            ORDER BY frequency DESC
            """
            for record in session.run(relation_query):
                relation_frequencies[str(record["rel_type"] or "")] = int(record["frequency"] or 0)

        entities.sort(key=lambda item: (-int(item.get("degree") or 0), str(item.get("node_id") or "")))
        return GraphCacheStats(
            graph_signature=expected_signature,
            entity_count=len(entities),
            relation_type_count=len(relation_frequencies),
            entities=entities,
            relation_frequencies=relation_frequencies,
            page_size=max(1, int(page_size)),
            source="paged_warmup",
        )


