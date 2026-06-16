"""Transform raw graph execution output into ranked evidence documents."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from ..evidence_processing import extract_evidence_units
from .evidence_builder import GraphEvidenceBuilder
from .path_ranker import GraphDocumentRanker
from .retrieval_types import GraphPath, KnowledgeSubgraph
from ..retrieval.contracts import EvidenceDocument

logger = logging.getLogger(__name__)


class GraphRetrievalPostProcessor:
    """Materialize graph results and keep evidence-contract post-processing together."""

    def __init__(
        self,
        evidence_builder: Optional[GraphEvidenceBuilder] = None,
        ranker: Optional[GraphDocumentRanker] = None,
    ):
        self.evidence_builder = evidence_builder or GraphEvidenceBuilder()
        self.ranker = ranker

    def parse_neo4j_path(self, record: Any, path_type: str = "multi_hop") -> Optional[GraphPath]:
        try:
            path_nodes: List[Dict[str, Any]] = []
            for node in record["path_nodes"]:
                properties = dict(node)
                path_nodes.append(
                    {
                        "id": properties.get("nodeId", ""),
                        "name": properties.get("name", ""),
                        "labels": list(getattr(node, "labels", [])),
                        "properties": properties,
                    }
                )

            relationships: List[Dict[str, Any]] = []
            for rel in record["rels"]:
                relationships.append({"type": rel.type, "properties": dict(rel)})

            return GraphPath(
                nodes=path_nodes,
                relationships=relationships,
                path_length=int(record["path_len"]),
                relevance_score=float(record["relevance"]),
                path_type=path_type,
            )
        except Exception as exc:
            logger.error("Path parsing failed: %s", exc)
            return None

    def build_knowledge_subgraph(self, record: Any) -> KnowledgeSubgraph:
        try:
            source_node = record["source"]
            central_nodes = [{**dict(source_node), "labels": list(getattr(source_node, "labels", []))}]
            connected_nodes = [
                {**dict(node), "labels": list(getattr(node, "labels", []))}
                for node in record["nodes"]
            ]

            relationships: List[Dict[str, Any]] = []
            for item in record["rels"]:
                if isinstance(item, list):
                    relationships.extend(dict(rel) for rel in item)
                else:
                    relationships.append(dict(item))

            return KnowledgeSubgraph(
                central_nodes=central_nodes,
                connected_nodes=connected_nodes,
                relationships=relationships,
                graph_metrics=dict(record["metrics"] or {}),
                reasoning_chains=[],
            )
        except Exception as exc:
            logger.error("Subgraph materialization failed: %s", exc)
            return self.empty_subgraph()

    def merge_subgraphs(self, subgraphs: List[KnowledgeSubgraph]) -> KnowledgeSubgraph:
        central_nodes: List[Dict[str, Any]] = []
        connected_nodes: List[Dict[str, Any]] = []
        relationships: List[Dict[str, Any]] = []
        seen_nodes = set()
        seen_relationships = set()
        total_node_count = 0
        total_relationship_count = 0

        for subgraph in subgraphs:
            total_node_count += int(subgraph.graph_metrics.get("node_count", 0) or 0)
            total_relationship_count += int(subgraph.graph_metrics.get("relationship_count", 0) or 0)
            for node in subgraph.central_nodes:
                node_key = str(node.get("nodeId") or node.get("name") or id(node))
                if node_key not in seen_nodes:
                    seen_nodes.add(node_key)
                    central_nodes.append(node)
            for node in subgraph.connected_nodes:
                node_key = str(node.get("nodeId") or node.get("name") or id(node))
                if node_key not in seen_nodes:
                    seen_nodes.add(node_key)
                    connected_nodes.append(node)
            for rel in subgraph.relationships:
                rel_key = (
                    str(rel.get("startNodeId") or ""),
                    str(rel.get("type") or ""),
                    str(rel.get("endNodeId") or ""),
                )
                if rel_key not in seen_relationships:
                    seen_relationships.add(rel_key)
                    relationships.append(rel)

        node_count = len(central_nodes) + len(connected_nodes)
        relationship_count = len(relationships)
        density = float(relationship_count) / (node_count * (node_count - 1) / 2) if node_count > 1 else 0.0
        return KnowledgeSubgraph(
            central_nodes=central_nodes,
            connected_nodes=connected_nodes,
            relationships=relationships,
            graph_metrics={
                "node_count": node_count,
                "relationship_count": relationship_count,
                "density": density,
                "source_subgraph_count": len(subgraphs),
                "raw_node_count": total_node_count,
                "raw_relationship_count": total_relationship_count,
            },
            reasoning_chains=[],
        )

    def paths_to_evidence_documents(self, paths: List[GraphPath], query: str) -> List[EvidenceDocument]:
        return self.evidence_builder.paths_to_evidence(paths, query)

    def subgraph_to_evidence_documents(
        self,
        subgraph: KnowledgeSubgraph,
        reasoning_chains: List[str],
        query: str,
    ) -> List[EvidenceDocument]:
        return self.evidence_builder.subgraph_to_evidence(subgraph, reasoning_chains, query)

    def build_path_description(self, path: GraphPath) -> str:
        return self.evidence_builder.build_path_description(path)

    def build_subgraph_description(self, subgraph: KnowledgeSubgraph) -> str:
        return self.evidence_builder.build_subgraph_description(subgraph)

    def summarize_subgraph_evidence(self, subgraph: KnowledgeSubgraph) -> Dict[str, Any]:
        return self.evidence_builder.summarize_subgraph_evidence(subgraph)

    def relationship_lines(self, subgraph: KnowledgeSubgraph, limit: int = 30) -> List[str]:
        return self.evidence_builder.relationship_lines(subgraph, limit=limit)

    def rank_by_graph_relevance(self, documents: List[EvidenceDocument], query: str) -> List[EvidenceDocument]:
        if not self.ranker:
            return list(documents or [])
        return self.ranker.rank(documents, query)

    def dedupe_graph_documents(self, documents: List[EvidenceDocument]) -> List[EvidenceDocument]:
        if not self.ranker:
            return list(documents or [])
        return self.ranker.dedupe(documents)

    def to_ranked_evidence_documents(
        self,
        documents: List[EvidenceDocument],
        query: str,
    ) -> List[EvidenceDocument]:
        if not documents:
            return []
        attached_docs = self.attach_evidence_units(documents)
        ranked_docs = self.rank_by_graph_relevance(attached_docs, query)
        return self.dedupe_graph_documents(ranked_docs)

    @staticmethod
    def attach_evidence_units(documents: List[EvidenceDocument]) -> List[EvidenceDocument]:
        enriched: List[EvidenceDocument] = []
        for doc in documents:
            metadata = dict(doc.metadata or {})
            metadata["evidence_units"] = extract_evidence_units(doc, metadata)
            enriched.append(doc.copy_with(evidence_units=metadata["evidence_units"], metadata=metadata))
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


