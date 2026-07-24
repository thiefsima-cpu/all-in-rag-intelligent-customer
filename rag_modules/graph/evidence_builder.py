"""Build evidence documents from graph traversal results."""

from __future__ import annotations

from typing import Protocol, Sequence

from ..contracts import EvidenceDocument
from ..kernel.json_types import JsonObject, coerce_json_object
from ..kernel.semantic_schema import SEMANTIC_NODE_LABELS_SET, SEMANTIC_RELATION_TYPES
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

    semantic_node_labels: frozenset[str] = frozenset(SEMANTIC_NODE_LABELS_SET)

    def __init__(
        self,
        *,
        domain_name: str = "recipe",
        primary_labels: Sequence[str] = ("Recipe",),
        semantic_node_labels: Sequence[str] | None = None,
    ) -> None:
        self.domain_name = str(domain_name or "recipe")
        self.primary_labels = frozenset(str(label) for label in primary_labels if label)
        if semantic_node_labels is not None:
            self.semantic_node_labels = frozenset(semantic_node_labels)

    def _primary_nodes(self, nodes: Sequence[GraphNodeSnapshot]) -> list[GraphNodeSnapshot]:
        return [
            node for node in nodes if any(label in self.primary_labels for label in node.labels)
        ]

    def paths_to_evidence(
        self, paths: Sequence[GraphPathLike], query: str
    ) -> list[EvidenceDocument]:
        del query
        return [self._path_to_evidence(path) for path in paths]

    def _path_to_evidence(self, path: GraphPathLike) -> EvidenceDocument:
        path_desc = self.build_path_description(path)
        primary_nodes = self._primary_nodes(path.nodes)
        primary_ids = [node.node_id for node in primary_nodes if node.node_id]
        primary_names = [node.name for node in primary_nodes if node.name]
        semantic_names = [
            node.name
            for node in path.nodes
            if any(label in self.semantic_node_labels for label in node.labels) and node.name
        ]
        ingredient_names = [
            node.name for node in path.nodes if node.has_label("Ingredient") and node.name
        ]
        step_names = [
            node.name for node in path.nodes if node.has_label("CookingStep") and node.name
        ]
        entity_name = (
            primary_names[0] if primary_names else _first_node_name(path.nodes, "图路径结果")
        )
        graph_evidence = coerce_json_object(
            {
                "nodes": [_path_node_evidence(node) for node in path.nodes],
                "relationships": [_path_relationship_evidence(rel) for rel in path.relationships],
                "description": path_desc,
                "matched_ingredients": ingredient_names,
                "matched_steps": step_names,
                "semantic_nodes": semantic_names,
            }
        )
        recipe_evidence = self._recipe_path_evidence(
            primary_ids, primary_names, ingredient_names, step_names, semantic_names, path
        )
        domain_evidence = recipe_evidence if self.domain_name == "recipe" else graph_evidence
        metadata = self._path_metadata(
            path,
            primary_ids,
            primary_names,
            entity_name,
            ingredient_names,
            step_names,
            graph_evidence,
            domain_evidence,
        )
        return EvidenceDocument(
            content=path_desc,
            entity_id=primary_ids[0] if primary_ids else "",
            entity_name=entity_name,
            entity_type="GraphPath",
            node_id=primary_ids[0] if primary_ids else "",
            score=float(path.relevance_score or 0.0),
            search_type="graph_path",
            search_method="graph_path",
            retrieval_level="graph_path",
            source="graph_rag",
            matched_terms=list(dict.fromkeys(ingredient_names + step_names + semantic_names)),
            graph_evidence=graph_evidence,
            domain_graph_evidence=domain_evidence,
            metadata=metadata,
        )

    def _recipe_path_evidence(
        self,
        primary_ids: list[str],
        primary_names: list[str],
        ingredient_names: list[str],
        step_names: list[str],
        semantic_names: list[str],
        path: GraphPathLike,
    ) -> JsonObject:
        if self.domain_name != "recipe":
            return {}
        return recipe_graph_evidence(
            recipe_ids=primary_ids,
            recipe_names=primary_names,
            matched_ingredients=ingredient_names,
            matched_steps=step_names,
            semantic_nodes=semantic_names,
            relationships=path.relationships,
        )

    def _path_metadata(
        self,
        path: GraphPathLike,
        primary_ids: list[str],
        primary_names: list[str],
        entity_name: str,
        ingredient_names: list[str],
        step_names: list[str],
        graph_evidence: JsonObject,
        domain_evidence: JsonObject,
    ) -> JsonObject:
        metadata = coerce_json_object(
            {
                "domain": self.domain_name,
                "entity_ids": primary_ids,
                "entity_names": primary_names,
                "entity_name": entity_name,
                "search_type": "graph_path",
                "search_method": "graph_path",
                "source": "graph_rag",
                "path_length": path.path_length,
                "relevance_score": path.relevance_score,
                "score": path.relevance_score,
                "path_type": path.path_type,
                "node_count": len(path.nodes),
                "relationship_count": len(path.relationships),
                "matched_ingredients": ingredient_names,
                "matched_steps": step_names,
                "graph_evidence": graph_evidence,
                "domain_graph_evidence": domain_evidence,
            }
        )
        if self.domain_name == "recipe":
            metadata.update(
                coerce_json_object(
                    {
                        "recipe_node_ids": primary_ids,
                        "recipe_names": primary_names,
                        "recipe_name": entity_name,
                    }
                )
            )
        return metadata

    def subgraph_to_evidence(
        self,
        subgraph: KnowledgeSubgraphLike,
        reasoning_chains: list[str],
        query: str,
    ) -> list[EvidenceDocument]:
        del query
        subgraph_desc = self.build_subgraph_description(subgraph)
        nodes = subgraph.central_nodes + subgraph.connected_nodes
        primary_nodes = self._primary_nodes(nodes)
        primary_ids = [node.node_id for node in primary_nodes if node.node_id]
        primary_names = [node.name for node in primary_nodes if node.name]
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
        domain_evidence = coerce_json_object(
            {**graph_evidence, "reasoning_chains": list(reasoning_chains)}
        )
        entity_name = (
            primary_names[0]
            if primary_names
            else _first_node_name(subgraph.central_nodes, "知识子图")
        )
        domain_evidence, metadata = self._subgraph_metadata(
            subgraph,
            reasoning_chains,
            primary_ids=primary_ids,
            primary_names=primary_names,
            entity_name=entity_name,
            ingredient_names=ingredient_names,
            step_names=step_names,
            semantic_names=semantic_names,
            graph_evidence=graph_evidence,
            domain_evidence=domain_evidence,
        )
        return [
            EvidenceDocument(
                content=subgraph_desc,
                entity_id=primary_ids[0] if primary_ids else "",
                entity_name=str(entity_name or ""),
                entity_type="KnowledgeSubgraph",
                node_id=primary_ids[0] if primary_ids else "",
                score=float(subgraph.graph_metrics.get("density", 0.0) or 0.0),
                search_type="knowledge_subgraph",
                search_method="knowledge_subgraph",
                retrieval_level="subgraph",
                source="graph_rag",
                matched_terms=list(dict.fromkeys(ingredient_names + step_names + semantic_names)),
                graph_evidence=graph_evidence,
                domain_graph_evidence=domain_evidence,
                metadata=metadata,
            )
        ]

    def _subgraph_metadata(
        self,
        subgraph: KnowledgeSubgraphLike,
        reasoning_chains: list[str],
        *,
        primary_ids: list[str],
        primary_names: list[str],
        entity_name: str,
        ingredient_names: list[str],
        step_names: list[str],
        semantic_names: list[str],
        graph_evidence: JsonObject,
        domain_evidence: JsonObject,
    ) -> tuple[JsonObject, JsonObject]:
        metadata = coerce_json_object(
            {
                "domain": self.domain_name,
                "entity_ids": primary_ids,
                "entity_names": primary_names,
                "entity_name": entity_name,
                "search_type": "knowledge_subgraph",
                "search_method": "knowledge_subgraph",
                "source": "graph_rag",
                "node_count": len(subgraph.connected_nodes),
                "relationship_count": len(subgraph.relationships),
                "graph_density": subgraph.graph_metrics.get("density", 0.0),
                "reasoning_chains": reasoning_chains,
                "graph_evidence": graph_evidence,
                "domain_graph_evidence": domain_evidence,
                "score": float(subgraph.graph_metrics.get("density", 0.0) or 0.0),
            }
        )
        if self.domain_name != "recipe":
            return domain_evidence, metadata
        domain_evidence = recipe_graph_evidence(
            recipe_ids=primary_ids,
            recipe_names=primary_names,
            matched_ingredients=ingredient_names,
            matched_steps=step_names,
            semantic_nodes=semantic_names,
            relationships=subgraph.relationships,
            reasoning_chains=reasoning_chains,
        )
        metadata.update(
            coerce_json_object(
                {
                    "recipe_node_ids": primary_ids,
                    "recipe_names": primary_names,
                    "recipe_name": entity_name,
                    "domain_graph_evidence": domain_evidence,
                }
            )
        )
        return domain_evidence, metadata

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
