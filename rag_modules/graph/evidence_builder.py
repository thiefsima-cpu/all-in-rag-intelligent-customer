"""Build evidence documents from graph traversal results."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Protocol, Sequence

from ..contracts import EvidenceDocument
from ..domain.shared.semantic_schema import SEMANTIC_NODE_LABELS_SET, SEMANTIC_RELATION_TYPES


class GraphPathLike(Protocol):
    nodes: List[Dict[str, Any]]
    relationships: List[Dict[str, Any]]
    path_length: int
    relevance_score: float
    path_type: str


class KnowledgeSubgraphLike(Protocol):
    central_nodes: List[Dict[str, Any]]
    connected_nodes: List[Dict[str, Any]]
    relationships: List[Dict[str, Any]]
    graph_metrics: Dict[str, float]


def node_labels(node: Dict[str, Any]) -> List[str]:
    labels = node.get("labels") or node.get("originalLabels") or []
    if isinstance(labels, str):
        return [labels]
    return list(labels)


def node_name(node: Dict[str, Any]) -> str:
    return str(node.get("name") or node.get("title") or node.get("nodeId") or "未知节点")


def recipe_graph_evidence(
    recipe_ids: List[str],
    recipe_names: List[str],
    matched_ingredients: List[str],
    matched_steps: List[str],
    semantic_nodes: List[str],
    relationships: List[Any],
    reasoning_chains: Optional[List[str]] = None,
) -> Dict[str, Any]:
    return {
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
            rel
            for rel in relationships
            if isinstance(rel, dict) and (rel.get("type") or "") in SEMANTIC_RELATION_TYPES
        ],
        "semantic_nodes": semantic_nodes,
        "relationship_count": len(relationships or []),
        "reasoning_chains": reasoning_chains or [],
    }


class GraphEvidenceBuilder:
    """Convert graph paths and subgraphs into evidence documents."""

    semantic_node_labels = SEMANTIC_NODE_LABELS_SET

    def paths_to_evidence(
        self, paths: Sequence[GraphPathLike], query: str
    ) -> List[EvidenceDocument]:
        evidence_docs: List[EvidenceDocument] = []
        for path in paths:
            path_desc = self.build_path_description(path)
            recipe_nodes = [node for node in path.nodes if "Recipe" in node.get("labels", [])]
            semantic_names = [
                str(node.get("name"))
                for node in path.nodes
                if any(label in self.semantic_node_labels for label in node.get("labels", []))
                and node.get("name")
            ]
            recipe_node_ids = [str(node.get("id")) for node in recipe_nodes if node.get("id")]
            recipe_names = [str(node.get("name")) for node in recipe_nodes if node.get("name")]
            ingredient_names = [
                str(node.get("name"))
                for node in path.nodes
                if "Ingredient" in node.get("labels", []) and node.get("name")
            ]
            step_names = [
                str(node.get("name"))
                for node in path.nodes
                if "CookingStep" in node.get("labels", []) and node.get("name")
            ]
            recipe_name = (
                recipe_names[0]
                if recipe_names
                else (
                    str(path.nodes[0].get("name") or "图路径结果") if path.nodes else "图路径结果"
                )
            )
            graph_evidence = {
                "nodes": path.nodes,
                "relationships": path.relationships,
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
        reasoning_chains: List[str],
        query: str,
    ) -> List[EvidenceDocument]:
        subgraph_desc = self.build_subgraph_description(subgraph)
        nodes = subgraph.central_nodes + subgraph.connected_nodes
        recipe_nodes = [
            node
            for node in nodes
            if "Recipe" in node_labels(node) or node.get("originalLabels") == "Recipe"
        ]
        recipe_node_ids = [str(node.get("nodeId")) for node in recipe_nodes if node.get("nodeId")]
        recipe_names = [str(node.get("name")) for node in recipe_nodes if node.get("name")]
        ingredient_names = [
            str(node.get("name"))
            for node in nodes
            if "Ingredient" in node_labels(node) and node.get("name")
        ]
        step_names = [
            str(node.get("name"))
            for node in nodes
            if "CookingStep" in node_labels(node) and node.get("name")
        ]
        semantic_names = [
            str(node.get("name"))
            for node in nodes
            if any(label in self.semantic_node_labels for label in node_labels(node))
            and node.get("name")
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
            else (
                subgraph.central_nodes[0].get("name", "知识子图")
                if subgraph.central_nodes
                else "知识子图"
            )
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
    ) -> List[EvidenceDocument]:
        return self.paths_to_evidence(paths, query)

    def subgraph_to_documents(
        self,
        subgraph: KnowledgeSubgraphLike,
        reasoning_chains: List[str],
        query: str,
    ) -> List[EvidenceDocument]:
        return self.subgraph_to_evidence(subgraph, reasoning_chains, query)

    def build_path_description(self, path: GraphPathLike) -> str:
        if not path.nodes:
            return "空路径"

        desc_parts: List[str] = []
        for index, node in enumerate(path.nodes):
            desc_parts.append(str(node.get("name") or f"节点{index}"))
            if index < len(path.relationships):
                rel_type = str(path.relationships[index].get("type") or "相关")
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
            f"关于 {center_label} 的知识网络，包含 {node_count} 个相关节点和 {rel_count} 个关系。",
        ]
        if connected_preview:
            parts.append("相关节点: " + "，".join(connected_preview))
        if relationship_preview:
            parts.append("关系证据:\n" + "\n".join(relationship_preview))
        return "\n".join(parts)

    def summarize_subgraph_evidence(self, subgraph: KnowledgeSubgraphLike) -> Dict[str, Any]:
        return {
            "central_nodes": [
                {
                    "nodeId": node.get("nodeId"),
                    "name": node_name(node),
                    "labels": node_labels(node),
                }
                for node in subgraph.central_nodes
            ],
            "connected_nodes": [
                {
                    "nodeId": node.get("nodeId"),
                    "name": node_name(node),
                    "labels": node_labels(node),
                    "category": node.get("category"),
                }
                for node in subgraph.connected_nodes[:30]
            ],
            "relationships": self.relationship_lines(subgraph, limit=50),
            "semantic_relationship_count": sum(
                1
                for rel in subgraph.relationships
                if (rel.get("type") or "") in SEMANTIC_RELATION_TYPES
            ),
            "metrics": subgraph.graph_metrics,
        }

    def relationship_lines(self, subgraph: KnowledgeSubgraphLike, limit: int = 30) -> List[str]:
        nodes_by_id = {
            str(node.get("nodeId")): node
            for node in (subgraph.central_nodes + subgraph.connected_nodes)
            if node.get("nodeId") is not None
        }
        lines: List[str] = []
        seen = set()
        for rel in subgraph.relationships:
            start_id = str(rel.get("startNodeId") or "")
            end_id = str(rel.get("endNodeId") or "")
            rel_type = rel.get("type") or "RELATED"
            start_name = node_name(nodes_by_id.get(start_id, {}))
            end_name = node_name(nodes_by_id.get(end_id, {}))
            line = f"{start_name} -[{rel_type}]-> {end_name}"
            if line in seen:
                continue
            seen.add(line)
            lines.append(line)
            if len(lines) >= limit:
                break
        return lines
