"""Build evidence documents from graph traversal results."""

from __future__ import annotations

from typing import Protocol, Sequence

from ..contracts import EvidenceDocument
from ..domain.shared.semantic_schema import SEMANTIC_NODE_LABELS_SET, SEMANTIC_RELATION_TYPES
from ..runtime.json_types import JsonObject, coerce_json_object
from .retrieval_types import GraphNodeSnapshot, GraphRelationshipSnapshot


class GraphPathLike(Protocol):
    nodes: list[GraphNodeSnapshot]
    relationships: list[GraphRelationshipSnapshot]
    path_length: int
    relevance_score: float
    path_type: str


class KnowledgeSubgraphLike(Protocol):
    central_nodes: list[GraphNodeSnapshot]
    connected_nodes: list[GraphNodeSnapshot]
    relationships: list[GraphRelationshipSnapshot]
    graph_metrics: dict[str, float]


def node_labels(node: GraphNodeSnapshot) -> list[str]:
    return list(node.labels)


def node_name(node: GraphNodeSnapshot) -> str:
    return node.name or node.node_id or "未知节点"


def recipe_graph_evidence(
    recipe_ids: list[str],
    recipe_names: list[str],
    matched_ingredients: list[str],
    matched_steps: list[str],
    semantic_nodes: list[str],
    relationships: Sequence[GraphRelationshipSnapshot],
    reasoning_chains: list[str] | None = None,
) -> JsonObject:
    return coerce_json_object(
        {
            "recipe_ids": recipe_ids,
            "recipe_names": recipe_names,
            "matched_entities": list(
                dict.fromkeys(
                    (matched_ingredients or []) + (matched_steps or []) + (semantic_nodes or [])
                )
            ),
            "matched_ingredients": matched_ingredients,
            "matched_steps": matched_steps,
            "semantic_relations": [
                rel.to_dict()
                for rel in relationships
                if rel.relation_type in SEMANTIC_RELATION_TYPES
            ],
            "semantic_nodes": semantic_nodes,
            "relationship_count": len(relationships or []),
            "reasoning_chains": reasoning_chains or [],
        }
    )


class GraphEvidenceBuilder:
    """Convert graph paths and subgraphs into evidence documents."""

    semantic_node_labels = SEMANTIC_NODE_LABELS_SET

    def paths_to_evidence(
        self, paths: Sequence[GraphPathLike], query: str
    ) -> list[EvidenceDocument]:
        del query
        evidence_docs: list[EvidenceDocument] = []
        for path in paths:
            path_desc = self.build_path_description(path)
            recipe_nodes = [node for node in path.nodes if node.has_label("Recipe")]
            semantic_names = [
                node.name
                for node in path.nodes
                if any(label in self.semantic_node_labels for label in node.labels) and node.name
            ]
            recipe_node_ids = [node.node_id for node in recipe_nodes if node.node_id]
            recipe_names = [node.name for node in recipe_nodes if node.name]
            ingredient_names = [
                node.name for node in path.nodes if node.has_label("Ingredient") and node.name
            ]
            step_names = [
                node.name for node in path.nodes if node.has_label("CookingStep") and node.name
            ]
            recipe_name = (
                recipe_names[0] if recipe_names else _first_node_name(path.nodes, "图路径结果")
            )
            graph_evidence = {
                "nodes": [_path_node_evidence(node) for node in path.nodes],
                "relationships": [_path_relationship_evidence(rel) for rel in path.relationships],
                "description": path_desc,
                "matched_ingredients": ingredient_names,
                "matched_steps": step_names,
                "semantic_nodes": semantic_names,
            }
            recipe_evidence = recipe_graph_evidence(
                recipe_ids=recipe_node_ids,
                recipe_names=recipe_names,
                matched_ingredients=ingredient_names,
                matched_steps=step_names,
                semantic_nodes=semantic_names,
                relationships=path.relationships,
            )
            metadata = {
                "search_type": "graph_path",
                "search_method": "graph_path",
                "source": "graph_rag",
                "path_length": path.path_length,
                "relevance_score": path.relevance_score,
                "score": path.relevance_score,
                "path_type": path.path_type,
                "node_count": len(path.nodes),
                "relationship_count": len(path.relationships),
                "recipe_node_ids": recipe_node_ids,
                "recipe_names": recipe_names,
                "matched_ingredients": ingredient_names,
                "matched_steps": step_names,
                "graph_evidence": graph_evidence,
                "recipe_graph_evidence": recipe_evidence,
                "recipe_name": recipe_name,
            }
            evidence_docs.append(
                EvidenceDocument(
                    content=path_desc,
                    node_id=recipe_node_ids[0] if recipe_node_ids else "",
                    recipe_name=recipe_name,
                    node_type="GraphPath",
                    score=float(path.relevance_score or 0.0),
                    search_type="graph_path",
                    search_method="graph_path",
                    retrieval_level="graph_path",
                    recipe_id=recipe_node_ids[0] if recipe_node_ids else "",
                    source="graph_rag",
                    matched_terms=list(
                        dict.fromkeys(ingredient_names + step_names + semantic_names)
                    ),
                    graph_evidence=graph_evidence,
                    recipe_graph_evidence=recipe_evidence,
                    metadata=metadata,
                )
            )
        return evidence_docs

    def subgraph_to_evidence(
        self,
        subgraph: KnowledgeSubgraphLike,
        reasoning_chains: list[str],
        query: str,
    ) -> list[EvidenceDocument]:
        del query
        subgraph_desc = self.build_subgraph_description(subgraph)
        nodes = subgraph.central_nodes + subgraph.connected_nodes
        recipe_nodes = [node for node in nodes if node.has_label("Recipe")]
        recipe_node_ids = [node.node_id for node in recipe_nodes if node.node_id]
        recipe_names = [node.name for node in recipe_nodes if node.name]
        ingredient_names = [
            node.name for node in nodes if node.has_label("Ingredient") and node.name
        ]
        step_names = [node.name for node in nodes if node.has_label("CookingStep") and node.name]
        semantic_names = [
            node.name
            for node in nodes
            if any(label in self.semantic_node_labels for label in node.labels) and node.name
        ]
        graph_evidence = self.summarize_subgraph_evidence(subgraph)
        recipe_evidence = recipe_graph_evidence(
            recipe_ids=recipe_node_ids,
            recipe_names=recipe_names,
            matched_ingredients=ingredient_names,
            matched_steps=step_names,
            semantic_nodes=semantic_names,
            relationships=subgraph.relationships,
            reasoning_chains=reasoning_chains,
        )
        recipe_name = (
            recipe_names[0]
            if recipe_names
            else _first_node_name(subgraph.central_nodes, "知识子图")
        )
        metadata = {
            "search_type": "knowledge_subgraph",
            "search_method": "knowledge_subgraph",
            "source": "graph_rag",
            "node_count": len(subgraph.connected_nodes),
            "relationship_count": len(subgraph.relationships),
            "graph_density": subgraph.graph_metrics.get("density", 0.0),
            "reasoning_chains": reasoning_chains,
            "recipe_node_ids": recipe_node_ids,
            "recipe_names": recipe_names,
            "graph_evidence": graph_evidence,
            "recipe_graph_evidence": recipe_evidence,
            "recipe_name": recipe_name,
            "score": float(subgraph.graph_metrics.get("density", 0.0) or 0.0),
        }
        return [
            EvidenceDocument(
                content=subgraph_desc,
                node_id=recipe_node_ids[0] if recipe_node_ids else "",
                recipe_name=str(recipe_name or ""),
                node_type="KnowledgeSubgraph",
                score=float(subgraph.graph_metrics.get("density", 0.0) or 0.0),
                search_type="knowledge_subgraph",
                search_method="knowledge_subgraph",
                retrieval_level="subgraph",
                recipe_id=recipe_node_ids[0] if recipe_node_ids else "",
                source="graph_rag",
                matched_terms=list(dict.fromkeys(ingredient_names + step_names + semantic_names)),
                graph_evidence=graph_evidence,
                recipe_graph_evidence=recipe_evidence,
                metadata=metadata,
            )
        ]

    def paths_to_documents(
        self, paths: Sequence[GraphPathLike], query: str
    ) -> list[EvidenceDocument]:
        return self.paths_to_evidence(paths, query)

    def subgraph_to_documents(
        self,
        subgraph: KnowledgeSubgraphLike,
        reasoning_chains: list[str],
        query: str,
    ) -> list[EvidenceDocument]:
        return self.subgraph_to_evidence(subgraph, reasoning_chains, query)

    def build_path_description(self, path: GraphPathLike) -> str:
        if not path.nodes:
            return "空路径"

        desc_parts: list[str] = []
        for index, node in enumerate(path.nodes):
            desc_parts.append(node_name(node) if index == 0 else node_name(node))
            if index < len(path.relationships):
                rel_type = path.relationships[index].relation_type or "RELATED"
                desc_parts.append(f" --{rel_type}--> ")
        return "".join(desc_parts)

    def build_subgraph_description(self, subgraph: KnowledgeSubgraphLike) -> str:
        central_names = [node_name(node) for node in subgraph.central_nodes]
        center_label = ", ".join(central_names) if central_names else "中心节点"
        node_count = len(subgraph.connected_nodes)
        rel_count = len(subgraph.relationships)
        connected_preview = [
            f"{node_name(node)}({','.join(node_labels(node))})"
            for node in subgraph.connected_nodes[:20]
        ]
        relationship_preview = self.relationship_lines(subgraph, limit=30)

        parts = [
            f"关于 {center_label} 的知识网络，包含 {node_count} 个相关节点和 {rel_count} 个关系。"
        ]
        if connected_preview:
            parts.append("相关节点: " + "；".join(connected_preview))
        if relationship_preview:
            parts.append("关系证据:\n" + "\n".join(relationship_preview))
        return "\n".join(parts)

    def summarize_subgraph_evidence(self, subgraph: KnowledgeSubgraphLike) -> JsonObject:
        return coerce_json_object(
            {
                "central_nodes": [
                    {
                        "nodeId": node.node_id,
                        "name": node_name(node),
                        "labels": node_labels(node),
                    }
                    for node in subgraph.central_nodes
                ],
                "connected_nodes": [
                    {
                        "nodeId": node.node_id,
                        "name": node_name(node),
                        "labels": node_labels(node),
                        "category": node.category,
                    }
                    for node in subgraph.connected_nodes[:30]
                ],
                "relationships": self.relationship_lines(subgraph, limit=50),
                "semantic_relationship_count": sum(
                    1
                    for rel in subgraph.relationships
                    if rel.relation_type in SEMANTIC_RELATION_TYPES
                ),
                "metrics": dict(subgraph.graph_metrics),
            }
        )

    def relationship_lines(self, subgraph: KnowledgeSubgraphLike, limit: int = 30) -> list[str]:
        nodes_by_id = {
            node.node_id: node
            for node in (subgraph.central_nodes + subgraph.connected_nodes)
            if node.node_id
        }
        lines: list[str] = []
        seen: set[str] = set()
        for rel in subgraph.relationships:
            start_name = node_name(nodes_by_id.get(rel.start_node_id, GraphNodeSnapshot()))
            end_name = node_name(nodes_by_id.get(rel.end_node_id, GraphNodeSnapshot()))
            rel_type = rel.relation_type or "RELATED"
            line = f"{start_name} -[{rel_type}]-> {end_name}"
            if line in seen:
                continue
            seen.add(line)
            lines.append(line)
            if len(lines) >= limit:
                break
        return lines


def _first_node_name(nodes: Sequence[GraphNodeSnapshot], fallback: str) -> str:
    if not nodes:
        return fallback
    return node_name(nodes[0])


def _path_node_evidence(node: GraphNodeSnapshot) -> JsonObject:
    return coerce_json_object(
        {
            "id": node.node_id,
            "name": node.name,
            "labels": list(node.labels),
            "properties": dict(node.properties),
        }
    )


def _path_relationship_evidence(rel: GraphRelationshipSnapshot) -> JsonObject:
    properties = dict(rel.properties)
    if rel.start_node_id:
        properties["startNodeId"] = rel.start_node_id
    if rel.end_node_id:
        properties["endNodeId"] = rel.end_node_id
    return coerce_json_object(
        {
            "type": rel.relation_type,
            "properties": properties,
        }
    )
