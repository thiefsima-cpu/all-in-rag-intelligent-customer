"""Domain-neutral Neo4j fallback adapter for dual-level retrieval."""

from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import replace
from typing import TypedDict, cast

from ...contracts import EvidenceDocument
from ...domains import DEFAULT_DOMAIN_NAME
from ...kernel.json_types import coerce_json_object
from ...safe_logging import log_failure
from ..ports import Neo4jDriverPort

logger = logging.getLogger(__name__)


class _EntityRecord(TypedDict):
    node_id: object
    name: object
    description: object
    labels: object
    score: object


class _NameRecord(TypedDict):
    name: object


_ENTITY_QUERY = """
UNWIND $keywords AS keyword
MATCH (node)
WHERE ($allowed_labels = [] OR any(label IN labels(node) WHERE label IN $allowed_labels))
  AND (
    node.domain = $domain_name
    OR ($allow_domainless_graph_records AND node.domain IS NULL)
  )
  AND any(field IN $lookup_fields
          WHERE node[field] IS NOT NULL AND toString(node[field]) CONTAINS keyword)
WITH node, max(CASE
    WHEN node.nodeId = keyword THEN 1.0
    WHEN coalesce(node.name, node.title) = keyword THEN 0.95
    ELSE 0.7
END) AS score
RETURN
    node.nodeId AS node_id,
    coalesce(node.name, node.title, node.nodeId) AS name,
    coalesce(node.description, node.content, '') AS description,
    labels(node) AS labels,
    score
ORDER BY score DESC
LIMIT $limit
"""


def _coerce_float(value: object, default: float = 0.0) -> float:
    try:
        return float(str(value))
    except (TypeError, ValueError):
        return default


def _string_list(value: object) -> list[str]:
    if not isinstance(value, Iterable) or isinstance(value, (str, bytes, bytearray)):
        return []
    return [str(item) for item in value if item]


def _entity_document(record: _EntityRecord, domain_name: str) -> EvidenceDocument:
    content_parts: list[str] = []
    if record["name"]:
        content_parts.append(f"entity: {record['name']}")
    if record["description"]:
        content_parts.append(f"description: {record['description']}")
    labels = _string_list(record.get("labels"))
    entity_type = labels[0] if labels else "Entity"
    return EvidenceDocument(
        content="\n".join(content_parts),
        entity_id=str(record["node_id"]),
        entity_name=str(record["name"] or ""),
        entity_type=entity_type,
        node_id=str(record["node_id"]),
        score=_coerce_float(record.get("score")) * 0.7,
        search_type="graph_entity_fallback",
        search_method="neo4j_fallback",
        retrieval_level="entity",
        source="neo4j_fallback",
        metadata=coerce_json_object(
            {
                "domain": domain_name,
                "name": record["name"],
                "labels": labels,
                "source": "neo4j_fallback",
            }
        ),
    )


class Neo4jFallbackRetriever:
    """Run direct ontology-scoped fallback queries when graph indexes are sparse."""

    def __init__(
        self,
        *,
        driver: Neo4jDriverPort | None,
        database: str,
        domain_name: str = DEFAULT_DOMAIN_NAME,
        allowed_labels: tuple[str, ...] = (),
        lookup_fields: tuple[str, ...] = ("nodeId", "name", "title", "content", "description"),
        allow_domainless_graph_records: bool = False,
    ) -> None:
        self.driver = driver
        self.database = database
        self.domain_name = str(domain_name or DEFAULT_DOMAIN_NAME)
        self.allowed_labels = tuple(allowed_labels)
        self.lookup_fields = tuple(lookup_fields)
        self.allow_domainless_graph_records = bool(allow_domainless_graph_records)

    def entity_search(self, keywords: list[str], limit: int) -> list[EvidenceDocument]:
        if not keywords or limit <= 0 or self.driver is None:
            return []
        try:
            with self.driver.session(database=self.database) as session:
                records = cast(
                    Iterable[_EntityRecord],
                    session.run(_ENTITY_QUERY, self._query_params(keywords, limit)),
                )
                return [_entity_document(record, self.domain_name) for record in records]
        except Exception as exc:
            log_failure(
                logger,
                logging.ERROR,
                "retrieval_operation_failed",
                code="RETRIEVAL_FAILED",
                error=exc,
            )
            return []

    def topic_search(self, keywords: list[str], limit: int) -> list[EvidenceDocument]:
        return [
            replace(
                document,
                search_type="graph_topic_fallback",
                retrieval_level="topic",
            )
            for document in self.entity_search(keywords, limit)
        ]

    def node_neighbors(self, node_id: str, max_neighbors: int = 3) -> list[str]:
        if not node_id or self.driver is None:
            return []
        query = """
        MATCH (n {nodeId: $node_id})-[r]-(neighbor)
        WHERE (neighbor.domain = $domain_name
               OR ($allow_domainless_graph_records AND neighbor.domain IS NULL))
          AND ($allowed_labels = []
               OR any(label IN labels(neighbor) WHERE label IN $allowed_labels))
        RETURN coalesce(neighbor.name, neighbor.title, neighbor.nodeId) AS name
        LIMIT $limit
        """
        try:
            with self.driver.session(database=self.database) as session:
                records = cast(
                    Iterable[_NameRecord],
                    session.run(
                        query,
                        {
                            "node_id": node_id,
                            "limit": max_neighbors,
                            "domain_name": self.domain_name,
                            "allowed_labels": list(self.allowed_labels),
                            "allow_domainless_graph_records": self.allow_domainless_graph_records,
                        },
                    ),
                )
                return [str(record["name"]) for record in records if record["name"]]
        except Exception as exc:
            log_failure(
                logger,
                logging.ERROR,
                "retrieval_operation_failed",
                code="RETRIEVAL_FAILED",
                error=exc,
            )
            return []

    def _query_params(self, keywords: list[str], limit: int) -> dict[str, object]:
        return {
            "keywords": keywords,
            "limit": limit,
            "domain_name": self.domain_name,
            "allowed_labels": list(self.allowed_labels),
            "lookup_fields": list(self.lookup_fields),
            "allow_domainless_graph_records": self.allow_domainless_graph_records,
        }
