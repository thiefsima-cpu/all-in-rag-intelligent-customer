"""
Neo4j execution layer for GraphRAG retrieval.
"""

from __future__ import annotations

import logging

from ..contracts import RequestBudgetExceeded, RequestCancelled, RequestControl
from ..safe_logging import log_failure
from .ports import Neo4jDriverPort, Neo4jRecordPort
from .retrieval_plan import GraphRetrievalPlan

logger = logging.getLogger(__name__)


class GraphQueryExecutor:
    """Execute graph retrieval plans and return raw records."""

    def __init__(
        self,
        driver: Neo4jDriverPort | None,
        database: str = "neo4j",
        *,
        domain_name: str = "",
        primary_node_labels: tuple[str, ...] = (),
        semantic_relation_types: tuple[str, ...] = (),
        semantic_node_labels: tuple[str, ...] = (),
        allowed_node_labels: tuple[str, ...] = (),
        allow_domainless_graph_records: bool = False,
    ) -> None:
        self.driver = driver
        self.database = database
        self.domain_name = str(domain_name or "")
        self.primary_node_labels = tuple(primary_node_labels)
        self.semantic_relation_types = tuple(semantic_relation_types)
        self.semantic_node_labels = tuple(semantic_node_labels)
        self.allowed_node_labels = tuple(allowed_node_labels)
        self.allow_domainless_graph_records = bool(allow_domainless_graph_records)

    def multi_hop_paths(
        self,
        plan: GraphRetrievalPlan,
        *,
        control: RequestControl | None = None,
    ) -> list[Neo4jRecordPort]:
        if not self.driver:
            return []
        if control is not None:
            control.raise_if_cancelled()
        target_filter = self._target_filter_clause(plan)
        path_node_filter = self._path_node_filter()
        max_depth = max(1, min(int(plan.max_depth or 2), 4))
        query = f"""
        MATCH (source)
        WHERE ($source_node_ids <> [] AND source.nodeId IN $source_node_ids)
           OR ($source_node_ids = [] AND ANY(term IN $source_terms WHERE
                coalesce(source.name, source.title, source.nodeId) CONTAINS term
                OR source.nodeId = term
           ))
        MATCH path = (source)-[*1..{max_depth}]-(target)
        WHERE source <> target
          {target_filter}
          {path_node_filter}
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
              + (CASE WHEN ANY(n IN path_nodes WHERE ANY(label IN labels(n) WHERE label IN $primary_node_labels)) THEN 5.0 ELSE 0.0 END)
              + (CASE WHEN ANY(label IN labels(target) WHERE label IN $primary_node_labels) THEN 2.0 ELSE 0.0 END)
              + (CASE WHEN ANY(label IN labels(source) WHERE label IN $primary_node_labels) THEN 1.0 ELSE 0.0 END)
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
        return self._run_path_query(query, self._request_params(plan), control=control)

    def entity_relation_paths(
        self,
        plan: GraphRetrievalPlan,
        *,
        control: RequestControl | None = None,
    ) -> list[Neo4jRecordPort]:
        if not self.driver:
            return []
        if control is not None:
            control.raise_if_cancelled()
        target_filter = self._target_filter_clause(plan)
        path_node_filter = self._path_node_filter()
        max_depth = max(1, min(int(plan.max_depth or 2), 3))
        query = f"""
        MATCH (source)
        WHERE ($source_node_ids <> [] AND source.nodeId IN $source_node_ids)
           OR ($source_node_ids = [] AND ANY(term IN $source_terms WHERE
                coalesce(source.name, source.title, source.nodeId) CONTAINS term
                OR source.nodeId = term
           ))
        MATCH path = (source)-[*1..{max_depth}]-(target)
        WHERE source <> target
          {target_filter}
          {path_node_filter}
        WITH path, source, target,
             length(path) AS path_len,
             relationships(path) AS rels,
             nodes(path) AS path_nodes
        WITH path, source, target, path_len, rels, path_nodes,
             (1.0 / path_len)
             + (CASE WHEN ANY(label IN labels(source) WHERE label IN $primary_node_labels) THEN 1.0 ELSE 0.0 END)
             + (CASE WHEN ANY(label IN labels(target) WHERE label IN $primary_node_labels) THEN 0.8 ELSE 0.0 END)
              + (CASE WHEN ANY(n IN path_nodes WHERE ANY(label IN labels(n) WHERE label IN $primary_node_labels)) THEN 0.8 ELSE 0.0 END)
              + (CASE WHEN ANY(r IN rels WHERE type(r) IN $relation_types) THEN 0.8 ELSE 0.0 END)
              + (CASE WHEN ANY(r IN rels WHERE type(r) IN $semantic_relation_types) THEN 1.2 ELSE 0.0 END)
              + (CASE WHEN ANY(n IN path_nodes WHERE ANY(label IN labels(n) WHERE label IN $semantic_node_labels)) THEN 0.6 ELSE 0.0 END)
              AS relevance
        ORDER BY relevance DESC
        LIMIT $limit
        RETURN path, source, target, path_len, rels, path_nodes, relevance
        """
        return self._run_path_query(query, self._request_params(plan), control=control)

    def shortest_paths(
        self,
        plan: GraphRetrievalPlan,
        *,
        control: RequestControl | None = None,
    ) -> list[Neo4jRecordPort]:
        if not self.driver:
            return []
        if control is not None:
            control.raise_if_cancelled()
        if not (plan.source_node_ids or plan.source_terms) or not (
            plan.target_node_ids or plan.target_terms
        ):
            return self.entity_relation_paths(plan, control=control)
        path_node_filter = self._path_node_filter()
        max_depth = max(1, min(int(plan.max_depth or 3), 4))
        query = f"""
        MATCH (source), (target)
        WHERE (
             ($source_node_ids <> [] AND source.nodeId IN $source_node_ids)
             OR ($source_node_ids = [] AND ANY(term IN $source_terms WHERE coalesce(source.name, source.title, source.nodeId) CONTAINS term OR source.nodeId = term))
        )
        AND (
             ($target_node_ids <> [] AND target.nodeId IN $target_node_ids)
             OR ($target_node_ids = [] AND ANY(term IN $target_terms WHERE coalesce(target.name, target.title, target.nodeId) CONTAINS term OR target.nodeId = term))
        )
        AND source <> target
        MATCH path = shortestPath((source)-[*1..{max_depth}]-(target))
        WHERE 1 = 1
          {path_node_filter}
        WITH path, source, target,
             length(path) AS path_len,
             relationships(path) AS rels,
             nodes(path) AS path_nodes
        WITH path, source, target, path_len, rels, path_nodes,
             (1.0 / path_len)
              + (CASE WHEN ANY(n IN path_nodes WHERE ANY(label IN labels(n) WHERE label IN $primary_node_labels)) THEN 0.8 ELSE 0.0 END)
              + (CASE WHEN ANY(r IN rels WHERE type(r) IN $semantic_relation_types) THEN 1.0 ELSE 0.0 END)
              + (CASE WHEN ANY(n IN path_nodes WHERE ANY(label IN labels(n) WHERE label IN $semantic_node_labels)) THEN 0.5 ELSE 0.0 END)
              AS relevance
        ORDER BY relevance DESC
        LIMIT $limit
        RETURN path, source, target, path_len, rels, path_nodes, relevance
        """
        return self._run_path_query(query, self._request_params(plan), control=control)

    def subgraphs(
        self,
        plan: GraphRetrievalPlan,
        *,
        control: RequestControl | None = None,
    ) -> list[Neo4jRecordPort]:
        if not self.driver:
            return []
        if control is not None:
            control.raise_if_cancelled()
        driver = self.driver
        source_domain_filter = self._node_domain_filter("source")
        neighbor_domain_filter = self._node_domain_filter("neighbor")
        path_node_filter = self._path_node_filter()
        max_depth = max(1, min(int(plan.max_depth or 2), 3))
        query = f"""
        MATCH (source)
        WHERE ($source_node_ids <> [] AND source.nodeId IN $source_node_ids)
           OR ($source_node_ids = [] AND ANY(term IN $source_terms WHERE
                coalesce(source.name, source.title, source.nodeId) CONTAINS term
                OR source.nodeId = term
           ))
          {source_domain_filter}
        MATCH path = (source)-[r*1..{max_depth}]-(neighbor)
        WHERE 1 = 1
          {neighbor_domain_filter}
          {path_node_filter}
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
        params = self._request_params(plan)
        params["max_nodes"] = plan.max_nodes
        try:
            with driver.session(database=self.database) as session:
                records = session.run(query, params, **self._run_kwargs(control))
                if control is not None:
                    control.raise_if_cancelled()
                return list(records)
        except (RequestCancelled, RequestBudgetExceeded):
            raise
        except Exception as exc:
            log_failure(
                logger,
                logging.ERROR,
                "graph_operation_failed",
                code="GRAPH_OPERATION_FAILED",
                error=exc,
            )
            return []

    @staticmethod
    def _target_filter_clause(plan: GraphRetrievalPlan) -> str:
        if not (plan.target_node_ids or plan.target_terms):
            return ""
        return """
          AND (
            ($target_node_ids <> [] AND target.nodeId IN $target_node_ids)
            OR ($target_node_ids = [] AND ANY(kw IN $target_terms WHERE
                (coalesce(target.name, target.title) IS NOT NULL AND (toString(coalesce(target.name, target.title)) CONTAINS kw OR kw CONTAINS toString(coalesce(target.name, target.title)))) OR
                (target.nodeId IS NOT NULL AND (toString(target.nodeId) CONTAINS kw OR kw CONTAINS toString(target.nodeId)))
            ))
          )
        """

    @staticmethod
    def _params(plan: GraphRetrievalPlan) -> dict[str, object]:
        return {
            "source_node_ids": plan.source_node_ids,
            "source_terms": plan.source_terms,
            "target_node_ids": plan.target_node_ids,
            "target_terms": plan.target_terms,
            "relation_types": plan.relation_types,
            "semantic_relation_types": [],
            "semantic_node_labels": [],
            "limit": plan.max_nodes,
        }

    def _request_params(self, plan: GraphRetrievalPlan) -> dict[str, object]:
        params = self._params(plan)
        params.update(
            {
                "domain_name": self.domain_name,
                "primary_node_labels": list(self.primary_node_labels),
                "semantic_relation_types": self.semantic_relation_types,
                "semantic_node_labels": list(self.semantic_node_labels),
                "allowed_node_labels": list(self.allowed_node_labels),
            }
        )
        return params

    def _path_node_filter(self) -> str:
        if self.allow_domainless_graph_records:
            return (
                "AND ALL(n IN nodes(path) WHERE n.domain = $domain_name OR "
                "(n.domain IS NULL AND (n.createdFrom = 'semantic_schema' OR "
                "ANY(label IN labels(n) WHERE label IN $allowed_node_labels))))"
            )
        return "AND ALL(n IN nodes(path) WHERE n.domain = $domain_name)"

    def _node_domain_filter(self, variable: str) -> str:
        if self.allow_domainless_graph_records:
            return (
                f"AND ({variable}.domain = $domain_name OR "
                f"({variable}.domain IS NULL AND "
                f"({variable}.createdFrom = 'semantic_schema' OR "
                f"ANY(label IN labels({variable}) WHERE label IN $allowed_node_labels))))"
            )
        return f"AND {variable}.domain = $domain_name"

    def _run_path_query(
        self,
        query: str,
        params: dict[str, object],
        *,
        control: RequestControl | None = None,
    ) -> list[Neo4jRecordPort]:
        if self.driver is None:
            return []
        driver = self.driver
        try:
            with driver.session(database=self.database) as session:
                records = session.run(query, params, **self._run_kwargs(control))
                if control is not None:
                    control.raise_if_cancelled()
                return list(records)
        except (RequestCancelled, RequestBudgetExceeded):
            raise
        except Exception as exc:
            log_failure(
                logger,
                logging.ERROR,
                "graph_operation_failed",
                code="GRAPH_OPERATION_FAILED",
                error=exc,
            )
            return []

    @staticmethod
    def _run_kwargs(control: RequestControl | None) -> dict[str, object]:
        if control is None:
            return {}
        control.raise_if_cancelled()
        return {"timeout": control.remaining_seconds()}
