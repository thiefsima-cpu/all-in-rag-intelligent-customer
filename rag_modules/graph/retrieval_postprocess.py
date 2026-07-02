"""Transform raw graph execution output into ranked evidence documents."""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence

from ..contracts import EvidenceDocument
from ..evidence_processing import extract_evidence_units
from ..runtime.json_types import (
    JsonObject,
    coerce_json_float,
    coerce_json_int,
    coerce_json_object,
)
from ..safe_logging import log_failure
from .evidence_builder import GraphEvidenceBuilder
from .path_ranker import GraphDocumentRanker
from .retrieval_types import (
    GraphNodeSnapshot,
    GraphPath,
    GraphRelationshipSnapshot,
    KnowledgeSubgraph,
)

logger = logging.getLogger(__name__)


class GraphRetrievalPostProcessor:
    """Materialize graph results and keep evidence-contract post-processing together."""

    def __init__(
        self,
        evidence_builder: GraphEvidenceBuilder | None = None,
        ranker: GraphDocumentRanker | None = None,
    ) -> None:
        self.evidence_builder = evidence_builder or GraphEvidenceBuilder()
        self.ranker = ranker

    def parse_neo4j_path(
        self, record: Mapping[str, object], path_type: str = "multi_hop"
    ) -> GraphPath | None:
        try:
            path_nodes = [_node_snapshot(node) for node in _sequence(record.get("path_nodes"))]
            relationships = [_relationship_snapshot(rel) for rel in _sequence(record.get("rels"))]

            return GraphPath(
                nodes=path_nodes,
                relationships=relationships,
                path_length=coerce_json_int(record.get("path_len"), 0),
                relevance_score=coerce_json_float(record.get("relevance"), 0.0),
                path_type=path_type,
            )
        except Exception as exc:
            log_failure(
                logger,
                logging.ERROR,
                "graph_operation_failed",
                code="GRAPH_OPERATION_FAILED",
                error=exc,
            )
            return None

    def build_knowledge_subgraph(self, record: Mapping[str, object]) -> KnowledgeSubgraph:
        try:
            central_nodes = [_node_snapshot(record["source"])]
            connected_nodes = [_node_snapshot(node) for node in _sequence(record.get("nodes"))]

            relationships: list[GraphRelationshipSnapshot] = []
            for item in _sequence(record.get("rels")):
                if isinstance(item, Sequence) and not isinstance(item, (str, bytes, bytearray)):
                    relationships.extend(_relationship_snapshot(rel) for rel in item)
                else:
                    relationships.append(_relationship_snapshot(item))

            return KnowledgeSubgraph(
                central_nodes=central_nodes,
                connected_nodes=connected_nodes,
                relationships=relationships,
                graph_metrics=_float_metrics(record.get("metrics")),
                reasoning_chains=[],
            )
        except Exception as exc:
            log_failure(
                logger,
                logging.ERROR,
                "graph_operation_failed",
                code="GRAPH_OPERATION_FAILED",
                error=exc,
            )
            return self.empty_subgraph()

    def merge_subgraphs(self, subgraphs: list[KnowledgeSubgraph]) -> KnowledgeSubgraph:
        central_nodes: list[GraphNodeSnapshot] = []
        connected_nodes: list[GraphNodeSnapshot] = []
        relationships: list[GraphRelationshipSnapshot] = []
        seen_nodes: set[str] = set()
        seen_relationships: set[tuple[str, str, str]] = set()
        total_node_count = 0
        total_relationship_count = 0

        for subgraph in subgraphs:
            total_node_count += int(subgraph.graph_metrics.get("node_count", 0) or 0)
            total_relationship_count += int(
                subgraph.graph_metrics.get("relationship_count", 0) or 0
            )
            for node in subgraph.central_nodes:
                node_key = node.node_id or node.name or str(id(node))
                if node_key not in seen_nodes:
                    seen_nodes.add(node_key)
                    central_nodes.append(node)
            for node in subgraph.connected_nodes:
                node_key = node.node_id or node.name or str(id(node))
                if node_key not in seen_nodes:
                    seen_nodes.add(node_key)
                    connected_nodes.append(node)
            for rel in subgraph.relationships:
                rel_key = (rel.start_node_id, rel.relation_type, rel.end_node_id)
                if rel_key not in seen_relationships:
                    seen_relationships.add(rel_key)
                    relationships.append(rel)

        node_count = len(central_nodes) + len(connected_nodes)
        relationship_count = len(relationships)
        density = (
            float(relationship_count) / (node_count * (node_count - 1) / 2)
            if node_count > 1
            else 0.0
        )
        return KnowledgeSubgraph(
            central_nodes=central_nodes,
            connected_nodes=connected_nodes,
            relationships=relationships,
            graph_metrics={
                "node_count": float(node_count),
                "relationship_count": float(relationship_count),
                "density": density,
                "source_subgraph_count": float(len(subgraphs)),
                "raw_node_count": float(total_node_count),
                "raw_relationship_count": float(total_relationship_count),
            },
            reasoning_chains=[],
        )

    def paths_to_evidence_documents(
        self, paths: list[GraphPath], query: str
    ) -> list[EvidenceDocument]:
        return self.evidence_builder.paths_to_evidence(paths, query)

    def subgraph_to_evidence_documents(
        self,
        subgraph: KnowledgeSubgraph,
        reasoning_chains: list[str],
        query: str,
    ) -> list[EvidenceDocument]:
        return self.evidence_builder.subgraph_to_evidence(subgraph, reasoning_chains, query)

    def build_path_description(self, path: GraphPath) -> str:
        return self.evidence_builder.build_path_description(path)

    def build_subgraph_description(self, subgraph: KnowledgeSubgraph) -> str:
        return self.evidence_builder.build_subgraph_description(subgraph)

    def summarize_subgraph_evidence(self, subgraph: KnowledgeSubgraph) -> JsonObject:
        return self.evidence_builder.summarize_subgraph_evidence(subgraph)

    def relationship_lines(self, subgraph: KnowledgeSubgraph, limit: int = 30) -> list[str]:
        return self.evidence_builder.relationship_lines(subgraph, limit=limit)

    def rank_by_graph_relevance(
        self, documents: list[EvidenceDocument], query: str
    ) -> list[EvidenceDocument]:
        if not self.ranker:
            return list(documents or [])
        return self.ranker.rank(documents, query)

    def dedupe_graph_documents(self, documents: list[EvidenceDocument]) -> list[EvidenceDocument]:
        if not self.ranker:
            return list(documents or [])
        return self.ranker.dedupe(documents)

    def to_ranked_evidence_documents(
        self,
        documents: list[EvidenceDocument],
        query: str,
    ) -> list[EvidenceDocument]:
        if not documents:
            return []
        attached_docs = self.attach_evidence_units(documents)
        ranked_docs = self.rank_by_graph_relevance(attached_docs, query)
        return self.dedupe_graph_documents(ranked_docs)

    @staticmethod
    def attach_evidence_units(documents: list[EvidenceDocument]) -> list[EvidenceDocument]:
        enriched: list[EvidenceDocument] = []
        for doc in documents:
            metadata = dict(doc.metadata or {})
            metadata["evidence_units"] = extract_evidence_units(doc, metadata)
            enriched.append(
                doc.copy_with(evidence_units=metadata["evidence_units"], metadata=metadata)
            )
        return enriched

    @staticmethod
    def empty_subgraph() -> KnowledgeSubgraph:
        return KnowledgeSubgraph(
            central_nodes=[],
            connected_nodes=[],
            relationships=[],
            graph_metrics={},
            reasoning_chains=[],
        )


def _sequence(value: object) -> list[object]:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return list(value)
    return []


def _mapping_payload(value: object) -> JsonObject:
    if isinstance(value, Mapping):
        return coerce_json_object(value)
    return {}


def _labels(value: object) -> tuple[str, ...]:
    if isinstance(value, str):
        return (value,)
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return tuple(str(item) for item in value if str(item).strip())
    return ()


def _node_snapshot(node: object) -> GraphNodeSnapshot:
    properties = _mapping_payload(node)
    labels = _labels(getattr(node, "labels", properties.get("labels") or ()))
    node_id = str(properties.get("nodeId") or properties.get("id") or "")
    return GraphNodeSnapshot(
        node_id=node_id,
        name=str(properties.get("name") or properties.get("title") or node_id),
        labels=labels,
        category=str(properties.get("category") or ""),
        properties=properties,
    )


def _relationship_snapshot(rel: object) -> GraphRelationshipSnapshot:
    properties = _mapping_payload(rel)
    relation_type = str(getattr(rel, "type", properties.get("type") or ""))
    start_node_id = str(properties.get("startNodeId") or _node_id(getattr(rel, "start_node", None)))
    end_node_id = str(properties.get("endNodeId") or _node_id(getattr(rel, "end_node", None)))
    return GraphRelationshipSnapshot(
        relation_type=relation_type,
        start_node_id=start_node_id,
        end_node_id=end_node_id,
        properties=properties,
    )


def _node_id(node: object) -> str:
    properties = _mapping_payload(node)
    return str(properties.get("nodeId") or properties.get("id") or "")


def _float_metrics(value: object) -> dict[str, float]:
    return {
        str(key): coerce_json_float(item, 0.0) for key, item in coerce_json_object(value).items()
    }
