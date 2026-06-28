"""Neo4j fallback adapter for dual-level retrieval."""

from __future__ import annotations

import logging
from collections.abc import Iterable, Mapping
from typing import Any, List, cast

from ...contracts import EvidenceDocument
from ...runtime_contracts import Neo4jDriverPort
from ...safe_logging import log_failure

logger = logging.getLogger(__name__)


class Neo4jFallbackRetriever:
    """Run direct Neo4j fallback queries when in-memory graph indexes are sparse."""

    def __init__(self, *, driver: Neo4jDriverPort | None, database: str) -> None:
        self.driver = driver
        self.database = database

    def entity_search(self, keywords: List[str], limit: int) -> List[EvidenceDocument]:
        if not keywords or limit <= 0 or self.driver is None:
            return []

        results: List[EvidenceDocument] = []
        try:
            with self.driver.session(database=self.database) as session:
                cypher_query = """
                UNWIND $keywords AS keyword
                CALL db.index.fulltext.queryNodes('recipe_fulltext_index', keyword + '*')
                YIELD node, score
                WHERE node:Recipe
                RETURN
                    node.nodeId AS node_id,
                    node.name AS name,
                    node.description AS description,
                    labels(node) AS labels,
                    score
                ORDER BY score DESC
                LIMIT $limit
                """
                records = cast(
                    Iterable[Mapping[str, Any]],
                    session.run(cypher_query, {"keywords": keywords, "limit": limit}),
                )
                for record in records:
                    content_parts = []
                    if record["name"]:
                        content_parts.append(f"菜谱: {record['name']}")
                    if record["description"]:
                        content_parts.append(f"描述: {record['description']}")
                    results.append(
                        EvidenceDocument(
                            content="\n".join(content_parts),
                            node_id=str(record["node_id"]),
                            recipe_name=str(record["name"] or ""),
                            node_type="Recipe",
                            score=float(record["score"]) * 0.7,
                            search_type="graph_entity_fallback",
                            search_method="neo4j_fallback",
                            retrieval_level="entity",
                            source="neo4j_fallback",
                            metadata={
                                "name": record["name"],
                                "labels": list(record["labels"] or []),
                                "source": "neo4j_fallback",
                            },
                        )
                    )
        except Exception as exc:
            log_failure(
                logger,
                logging.ERROR,
                "retrieval_operation_failed",
                code="RETRIEVAL_FAILED",
                error=exc,
            )
        return results

    def topic_search(self, keywords: List[str], limit: int) -> List[EvidenceDocument]:
        if not keywords or limit <= 0 or self.driver is None:
            return []

        results: List[EvidenceDocument] = []
        try:
            with self.driver.session(database=self.database) as session:
                cypher_query = """
                UNWIND $keywords AS keyword
                MATCH (r:Recipe)
                WHERE r.category CONTAINS keyword
                   OR r.cuisineType CONTAINS keyword
                   OR r.tags CONTAINS keyword
                WITH r, keyword
                OPTIONAL MATCH (r)-[:REQUIRES]->(i:Ingredient)
                WITH r, keyword, collect(i.name)[0..3] AS ingredients
                RETURN
                    r.nodeId AS node_id,
                    r.name AS name,
                    r.category AS category,
                    r.cuisineType AS cuisine_type,
                    r.difficulty AS difficulty,
                    ingredients,
                    keyword AS matched_keyword
                ORDER BY r.difficulty ASC, r.name
                LIMIT $limit
                """
                records = cast(
                    Iterable[Mapping[str, Any]],
                    session.run(cypher_query, {"keywords": keywords, "limit": limit}),
                )
                for record in records:
                    content_parts = [f"菜谱: {record['name']}"]
                    if record["category"]:
                        content_parts.append(f"分类: {record['category']}")
                    if record["cuisine_type"]:
                        content_parts.append(f"菜系: {record['cuisine_type']}")
                    if record["difficulty"]:
                        content_parts.append(f"难度: {record['difficulty']}")
                    if record["ingredients"]:
                        content_parts.append(f"主要食材: {', '.join(record['ingredients'][:3])}")
                    results.append(
                        EvidenceDocument(
                            content="\n".join(content_parts),
                            node_id=str(record["node_id"]),
                            recipe_name=str(record["name"] or ""),
                            node_type="Recipe",
                            score=0.75,
                            search_type="graph_topic_fallback",
                            search_method="neo4j_fallback",
                            retrieval_level="topic",
                            source="neo4j_fallback",
                            matched_terms=[str(record["matched_keyword"] or "")],
                            metadata={
                                "name": record["name"],
                                "category": record["category"],
                                "cuisine_type": record["cuisine_type"],
                                "difficulty": record["difficulty"],
                                "matched_keyword": record["matched_keyword"],
                                "source": "neo4j_fallback",
                            },
                        )
                    )
        except Exception as exc:
            log_failure(
                logger,
                logging.ERROR,
                "retrieval_operation_failed",
                code="RETRIEVAL_FAILED",
                error=exc,
            )
        return results

    def node_neighbors(self, node_id: str, max_neighbors: int = 3) -> List[str]:
        if not node_id or self.driver is None:
            return []
        try:
            with self.driver.session(database=self.database) as session:
                query = """
                MATCH (n {nodeId: $node_id})-[r]-(neighbor)
                RETURN neighbor.name AS name
                LIMIT $limit
                """
                records = cast(
                    Iterable[Mapping[str, Any]],
                    session.run(query, {"node_id": node_id, "limit": max_neighbors}),
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
