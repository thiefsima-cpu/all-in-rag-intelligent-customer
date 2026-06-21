"""
Neo4j execution layer for GraphRAG retrieval.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from neo4j import Driver

from ..semantic_schema import SEMANTIC_NODE_LABELS_SET, SEMANTIC_RELATION_TYPES
from .retrieval_plan import GraphRetrievalPlan

logger = logging.getLogger(__name__)


class GraphQueryExecutor:
    """Execute graph retrieval plans and return raw records."""

    def __init__(self, driver: Optional[Driver], database: str = "neo4j"):
        self.driver = driver
        self.database = database

    def multi_hop_paths(self, plan: GraphRetrievalPlan) -> List[Any]:
        if not self.driver:
            return []
        target_filter = self._target_filter_clause(plan)
        max_depth = max(1, min(int(plan.max_depth or 2), 4))
        query = f"""
        MATCH (source)
        WHERE ($source_node_ids <> [] AND source.nodeId IN $source_node_ids)
           OR ($source_node_ids = [] AND ANY(term IN $source_terms WHERE
                source.name CONTAINS term OR source.nodeId = term
           ))
        MATCH path = (source)-[*1..{max_depth}]-(target)
        WHERE source <> target
          {target_filter}
          AND ALL(n IN nodes(path) WHERE n.nodeId IS NULL OR n.nodeId >= '200000000' OR n.createdFrom = 'semantic_schema')
        WITH path, source, target,
             length(path) AS path_len,
             relationships(path) AS rels,
             nodes(path) AS path_nodes
        WITH path, source, target, path_len, rels, path_nodes,
              (1.0 / path_len)
             + CASE
                 WHEN (REDUCE(s = 0.0, n IN path_nodes | s + COUNT {{ (n)--() }}) / 100.0 / size(path_nodes)) > 0.5
                 THEN 0.5
                 ELSE (REDUCE(s = 0.0, n IN path_nodes | s + COUNT {{ (n)--() }}) / 100.0 / size(path_nodes))
               END
              + (CASE WHEN ANY(n IN path_nodes WHERE n:Recipe) THEN 5.0 ELSE 0.0 END)
              + (CASE WHEN target:Recipe THEN 2.0 ELSE 0.0 END)
              + (CASE WHEN source:Recipe THEN 1.0 ELSE 0.0 END)
              + (CASE WHEN ANY(label IN labels(source) WHERE label IN $semantic_node_labels) THEN 1.5 ELSE 0.0 END)
              + (CASE WHEN ANY(label IN labels(target) WHERE label IN $semantic_node_labels) THEN 0.8 ELSE 0.0 END)
              + (CASE WHEN ANY(r IN rels WHERE type(r) IN $relation_types) THEN 1.0 ELSE 0.0 END)
              + (CASE WHEN ANY(r IN rels WHERE type(r) IN $semantic_relation_types) THEN 2.0 ELSE 0.0 END)
             + (CASE WHEN $source_node_ids <> [] THEN 0.4 ELSE 0.0 END)
             AS relevance
        ORDER BY relevance DESC
        LIMIT $limit
        RETURN path, source, target, path_len, rels, path_nodes, relevance
        """
        return self._run_path_query(query, self._params(plan))

    def entity_relation_paths(self, plan: GraphRetrievalPlan) -> List[Any]:
        if not self.driver:
            return []
        target_filter = self._target_filter_clause(plan)
        max_depth = max(1, min(int(plan.max_depth or 2), 3))
        query = f"""
        MATCH (source)
        WHERE ($source_node_ids <> [] AND source.nodeId IN $source_node_ids)
           OR ($source_node_ids = [] AND ANY(term IN $source_terms WHERE
                source.name CONTAINS term OR source.nodeId = term
           ))
        MATCH path = (source)-[*1..{max_depth}]-(target)
        WHERE source <> target
          {target_filter}
          AND ALL(n IN nodes(path) WHERE n.nodeId IS NULL OR n.nodeId >= '200000000' OR n.createdFrom = 'semantic_schema')
        WITH path, source, target,
             length(path) AS path_len,
             relationships(path) AS rels,
             nodes(path) AS path_nodes
        WITH path, source, target, path_len, rels, path_nodes,
             (1.0 / path_len)
             + (CASE WHEN source:Recipe THEN 1.0 ELSE 0.0 END)
             + (CASE WHEN target:Recipe THEN 0.8 ELSE 0.0 END)
              + (CASE WHEN ANY(n IN path_nodes WHERE n:Recipe) THEN 0.8 ELSE 0.0 END)
              + (CASE WHEN ANY(r IN rels WHERE type(r) IN $relation_types) THEN 0.8 ELSE 0.0 END)
              + (CASE WHEN ANY(r IN rels WHERE type(r) IN $semantic_relation_types) THEN 1.2 ELSE 0.0 END)
              + (CASE WHEN ANY(n IN path_nodes WHERE ANY(label IN labels(n) WHERE label IN $semantic_node_labels)) THEN 0.6 ELSE 0.0 END)
              AS relevance
        ORDER BY relevance DESC
        LIMIT $limit
        RETURN path, source, target, path_len, rels, path_nodes, relevance
        """
        return self._run_path_query(query, self._params(plan))

    def shortest_paths(self, plan: GraphRetrievalPlan) -> List[Any]:
        if not self.driver:
            return []
        if not (plan.source_node_ids or plan.source_terms) or not (
            plan.target_node_ids or plan.target_terms
        ):
            return self.entity_relation_paths(plan)
        max_depth = max(1, min(int(plan.max_depth or 3), 4))
        query = f"""
        MATCH (source), (target)
        WHERE (
             ($source_node_ids <> [] AND source.nodeId IN $source_node_ids)
             OR ($source_node_ids = [] AND ANY(term IN $source_terms WHERE source.name CONTAINS term OR source.nodeId = term))
        )
        AND (
             ($target_node_ids <> [] AND target.nodeId IN $target_node_ids)
             OR ($target_node_ids = [] AND ANY(term IN $target_terms WHERE target.name CONTAINS term OR target.nodeId = term))
        )
        AND source <> target
        MATCH path = shortestPath((source)-[*1..{max_depth}]-(target))
        WITH path, source, target,
             length(path) AS path_len,
             relationships(path) AS rels,
             nodes(path) AS path_nodes
        WITH path, source, target, path_len, rels, path_nodes,
             (1.0 / path_len)
              + (CASE WHEN ANY(n IN path_nodes WHERE n:Recipe) THEN 0.8 ELSE 0.0 END)
              + (CASE WHEN ANY(r IN rels WHERE type(r) IN $semantic_relation_types) THEN 1.0 ELSE 0.0 END)
              + (CASE WHEN ANY(n IN path_nodes WHERE ANY(label IN labels(n) WHERE label IN $semantic_node_labels)) THEN 0.5 ELSE 0.0 END)
              AS relevance
        ORDER BY relevance DESC
        LIMIT $limit
        RETURN path, source, target, path_len, rels, path_nodes, relevance
        """
        return self._run_path_query(query, self._params(plan))

    def subgraphs(self, plan: GraphRetrievalPlan) -> List[Any]:
        if not self.driver:
            return []
        driver = self.driver
        max_depth = max(1, min(int(plan.max_depth or 2), 3))
        query = f"""
        MATCH (source)
        WHERE ($source_node_ids <> [] AND source.nodeId IN $source_node_ids)
           OR ($source_node_ids = [] AND ANY(term IN $source_terms WHERE
                source.name CONTAINS term OR source.nodeId = term
           ))
        MATCH (source)-[r*1..{max_depth}]-(neighbor)
        WITH source, collect(DISTINCT neighbor) AS neighbors,
             collect(DISTINCT r) AS relationships
        WITH source, neighbors, relationships,
             size(neighbors) AS node_count,
             size(relationships) AS rel_count
        RETURN
            source,
            neighbors[0..$max_nodes] AS nodes,
            [rel_list IN relationships[0..$max_nodes] | [rel IN rel_list | {{
                type: type(rel),
                startNodeId: startNode(rel).nodeId,
                endNodeId: endNode(rel).nodeId
            }}]] AS rels,
            {{
                node_count: node_count,
                relationship_count: rel_count,
                density: CASE WHEN node_count > 1 THEN toFloat(rel_count) / (node_count * (node_count - 1) / 2) ELSE 0.0 END
            }} AS metrics
        """
        params = self._params(plan)
        params["max_nodes"] = plan.max_nodes
        try:
            with driver.session(database=self.database) as session:
                return list(session.run(query, params))
        except Exception as exc:
            logger.error("Subgraph query failed: %s", exc)
            return []

    @staticmethod
    def _target_filter_clause(plan: GraphRetrievalPlan) -> str:
        if not (plan.target_node_ids or plan.target_terms):
            return ""
        return """
          AND (
            ($target_node_ids <> [] AND target.nodeId IN $target_node_ids)
            OR ($target_node_ids = [] AND ANY(kw IN $target_terms WHERE
                (target.name IS NOT NULL AND (toString(target.name) CONTAINS kw OR kw CONTAINS toString(target.name))) OR
                (target.category IS NOT NULL AND (toString(target.category) CONTAINS kw OR kw CONTAINS toString(target.category)))
            ))
          )
        """

    @staticmethod
    def _params(plan: GraphRetrievalPlan) -> Dict[str, Any]:
        return {
            "source_node_ids": plan.source_node_ids,
            "source_terms": plan.source_terms,
            "target_node_ids": plan.target_node_ids,
            "target_terms": plan.target_terms,
            "relation_types": plan.relation_types,
            "semantic_relation_types": SEMANTIC_RELATION_TYPES,
            "semantic_node_labels": list(SEMANTIC_NODE_LABELS_SET),
            "limit": plan.max_nodes,
        }

    def _run_path_query(self, query: str, params: Dict[str, Any]) -> List[Any]:
        if self.driver is None:
            return []
        driver = self.driver
        try:
            with driver.session(database=self.database) as session:
                return list(session.run(query, params))
        except Exception as exc:
            logger.error("Graph path query failed: %s", exc)
            return []
