"""Graph cache warmup services for GraphRAG retrieval."""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Dict, List

from ..domains import DEFAULT_DOMAIN_NAME
from .cache_stats import GraphCacheEntityStats, GraphCacheStats, GraphCacheStatsStore
from .ports import Neo4jDriverPort, Neo4jRecordPort, Neo4jSessionPort

logger = logging.getLogger(__name__)


@dataclass
class GraphWarmupResult:
    stats: GraphCacheStats = field(default_factory=GraphCacheStats)
    entity_cache: Dict[str, Mapping[str, object]] = field(default_factory=dict)
    relation_cache: Dict[str, int] = field(default_factory=dict)


class GraphCacheWarmupService:
    """Load persisted graph stats or collect them with paged warmup scans."""

    def __init__(
        self,
        store: GraphCacheStatsStore,
        *,
        domain_name: str = DEFAULT_DOMAIN_NAME,
        allowed_node_labels: tuple[str, ...] = (),
        allow_domainless_graph_records: bool = False,
    ) -> None:
        self.store = store
        self.domain_name = str(domain_name or DEFAULT_DOMAIN_NAME)
        self.allowed_node_labels = tuple(allowed_node_labels)
        self.allow_domainless_graph_records = bool(allow_domainless_graph_records)

    def warm(self, driver: Neo4jDriverPort, *, database_name: str) -> GraphWarmupResult:
        stats = self._load_or_build_graph_stats(driver, database_name=database_name)
        entity_cache: Dict[str, Mapping[str, object]] = {
            item.node_id: {
                "labels": list(item.labels),
                "name": item.name,
                "category": item.category,
                "degree": item.degree,
            }
            for item in (stats.entities or [])
            if item.node_id
        }
        relation_cache = {
            str(key): int(value) for key, value in dict(stats.relation_frequencies or {}).items()
        }
        return GraphWarmupResult(
            stats=stats,
            entity_cache=entity_cache,
            relation_cache=relation_cache,
        )

    def _load_or_build_graph_stats(
        self,
        driver: Neo4jDriverPort,
        *,
        database_name: str,
    ) -> GraphCacheStats:
        expected_signature = self.store.expected_graph_signature()
        cached = self.store.load()
        if (
            cached
            and cached.entities
            and cached.domain_name == self.domain_name
            and (not expected_signature or cached.graph_signature == expected_signature)
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
        driver: Neo4jDriverPort,
        *,
        database_name: str,
        expected_signature: str = "",
        page_size: int = 500,
    ) -> GraphCacheStats:
        with driver.session(database=database_name) as session:
            entities = self._collect_entities(session, page_size=page_size)
            relation_frequencies = self._collect_relation_frequencies(session)
        entities.sort(key=lambda item: (-int(item.degree or 0), item.node_id))
        return GraphCacheStats(
            graph_signature=expected_signature,
            domain_name=self.domain_name,
            entity_count=len(entities),
            relation_type_count=len(relation_frequencies),
            entities=entities,
            relation_frequencies=relation_frequencies,
            page_size=max(1, int(page_size)),
            source="paged_warmup",
        )

    def _collect_entities(
        self,
        session: Neo4jSessionPort,
        *,
        page_size: int,
    ) -> List[GraphCacheEntityStats]:
        entities: List[GraphCacheEntityStats] = []
        domain_filter = (
            "AND (n.domain = $domain_name OR "
            "(n.domain IS NULL AND (n.createdFrom = 'semantic_schema' OR "
            "ANY(label IN labels(n) WHERE label IN $allowed_node_labels))))"
            if self.allow_domainless_graph_records
            else "AND n.domain = $domain_name"
        )
        degree_expression = (
            "COUNT { (n)--(neighbor) WHERE neighbor.domain = $domain_name OR "
            "(neighbor.domain IS NULL AND (neighbor.createdFrom = 'semantic_schema' OR "
            "ANY(label IN labels(neighbor) WHERE label IN $allowed_node_labels))) }"
            if self.allow_domainless_graph_records
            else "COUNT { (n)--(neighbor) WHERE neighbor.domain = $domain_name }"
        )
        page_cursor = ""
        while True:
            entity_query = f"""
            MATCH (n)
            WHERE n.nodeId IS NOT NULL
              {domain_filter}
              AND ($after_node_id = '' OR n.nodeId > $after_node_id)
            WITH n
            ORDER BY n.nodeId
            LIMIT $limit
            WITH collect(n) AS nodes
            UNWIND nodes AS n
            WITH n, {degree_expression} AS degree
            RETURN labels(n) AS node_labels,
                   n.nodeId AS node_id,
                   n.name AS name,
                   n.category AS category,
                   degree
            ORDER BY node_id
            """
            entity_params: dict[str, object] = {
                "after_node_id": page_cursor,
                "limit": max(1, int(page_size)),
                "domain_name": self.domain_name,
            }
            if self.allow_domainless_graph_records:
                entity_params["allowed_node_labels"] = list(self.allowed_node_labels)
            page_records: list[Neo4jRecordPort] = list(session.run(entity_query, entity_params))
            if not page_records:
                return entities
            for record in page_records:
                entities.append(
                    GraphCacheEntityStats(
                        node_id=str(record["node_id"] or ""),
                        labels=_string_tuple(record["node_labels"]),
                        name=str(record["name"] or ""),
                        category=str(record["category"] or ""),
                        degree=_int_value(record["degree"]),
                    )
                )
            page_cursor = str(page_records[-1]["node_id"] or "")

    def _collect_relation_frequencies(
        self,
        session: Neo4jSessionPort,
    ) -> dict[str, int]:
        relation_filter = (
            "WHERE (source.domain = $domain_name OR "
            "(source.domain IS NULL AND (source.createdFrom = 'semantic_schema' OR "
            "ANY(label IN labels(source) WHERE label IN $allowed_node_labels)))) "
            "AND (target.domain = $domain_name OR "
            "(target.domain IS NULL AND (target.createdFrom = 'semantic_schema' OR "
            "ANY(label IN labels(target) WHERE label IN $allowed_node_labels))))"
            if self.allow_domainless_graph_records
            else "WHERE source.domain = $domain_name AND target.domain = $domain_name"
        )
        relation_query = f"""
        MATCH (source)-[r]->(target)
        {relation_filter}
        RETURN type(r) AS rel_type, count(r) AS frequency
        ORDER BY frequency DESC
        """
        relation_params: dict[str, object] = {"domain_name": self.domain_name}
        if self.allow_domainless_graph_records:
            relation_params["allowed_node_labels"] = list(self.allowed_node_labels)
        return {
            str(record["rel_type"] or ""): _int_value(record["frequency"])
            for record in session.run(relation_query, relation_params)
        }


def _string_tuple(value: object) -> tuple[str, ...]:
    if isinstance(value, str):
        return (value,) if value.strip() else ()
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        return tuple(str(item) for item in value if str(item).strip())
    return ()


def _int_value(value: object) -> int:
    if isinstance(value, (int, float, str, bytes, bytearray)):
        try:
            return int(value)
        except (TypeError, ValueError):
            return 0
    return 0
