"""
Deterministic graph reasoning over retrieved subgraphs.

The retrieval layer already materializes graph structure. This strategy turns
that structure into compact reasoning chains without coupling the logic to the
retrieval facade.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Sequence

from ..domain.shared.semantic_schema import SEMANTIC_NODE_LABELS_SET
from ..query_policy import get_query_policy
from .retrieval_types import KnowledgeSubgraph


def _node_labels(node: Dict[str, Any]) -> List[str]:
    labels = node.get("labels") or node.get("originalLabels") or []
    if isinstance(labels, str):
        return [labels]
    return [str(label) for label in labels if str(label).strip()]


def _node_name(node: Dict[str, Any]) -> str:
    return str(node.get("name") or node.get("title") or node.get("nodeId") or "unknown_node")


@dataclass
class GraphReasoningOutcome:
    patterns: List[str] = field(default_factory=list)
    candidate_chains: List[str] = field(default_factory=list)
    validated_chains: List[str] = field(default_factory=list)
    summary: Dict[str, Any] = field(default_factory=dict)

    def to_trace_details(self) -> Dict[str, Any]:
        return {
            "patterns": list(self.patterns or []),
            "candidate_chain_count": len(self.candidate_chains or []),
            "validated_chain_count": len(self.validated_chains or []),
            "validated_chains": list(self.validated_chains or []),
            "summary": dict(self.summary or {}),
        }


class GraphReasoningStrategy:
    """Produce compact reasoning chains from a knowledge subgraph."""

    def __init__(self) -> None:
        reasoning_policy = get_query_policy().graph.reasoning
        self.causal_relation_types = set(reasoning_policy.causal_relation_types)
        self.compositional_relation_types = set(reasoning_policy.compositional_relation_types)
        self.comparison_markers = tuple(
            marker.lower() for marker in reasoning_policy.comparison_markers
        )

    def reason(self, subgraph: KnowledgeSubgraph, query: str) -> GraphReasoningOutcome:
        patterns = self.identify_reasoning_patterns(subgraph, query)
        candidate_chains: List[str] = []
        for pattern in patterns:
            candidate_chains.extend(self.build_reasoning_chains(pattern, subgraph, query))
        validated_chains = self.validate_reasoning_chains(candidate_chains, query, subgraph)
        return GraphReasoningOutcome(
            patterns=patterns,
            candidate_chains=candidate_chains,
            validated_chains=validated_chains,
            summary=self._build_summary(subgraph, patterns, validated_chains),
        )

    def identify_reasoning_patterns(self, subgraph: KnowledgeSubgraph, query: str) -> List[str]:
        relation_types = {
            str(rel.get("type") or "").strip()
            for rel in (subgraph.relationships or [])
            if str(rel.get("type") or "").strip()
        }
        patterns: List[str] = []
        if relation_types & self.causal_relation_types:
            patterns.append("causal")
        if (
            relation_types & self.compositional_relation_types
            or self._semantic_node_count(subgraph) > 0
        ):
            patterns.append("compositional")
        if self._supports_comparison(subgraph, query):
            patterns.append("comparative")
        if subgraph.relationships and not patterns:
            patterns.append("connectivity")
        return patterns

    def build_reasoning_chains(
        self,
        pattern: str,
        subgraph: KnowledgeSubgraph,
        query: str,
    ) -> List[str]:
        if pattern == "causal":
            return self._causal_chains(subgraph)
        if pattern == "compositional":
            return self._compositional_chains(subgraph)
        if pattern == "comparative":
            return self._comparative_chains(subgraph)
        return self._connectivity_chains(subgraph)

    def validate_reasoning_chains(
        self,
        chains: Sequence[str],
        query: str,
        subgraph: KnowledgeSubgraph,
    ) -> List[str]:
        deduped = list(dict.fromkeys(str(chain).strip() for chain in chains if str(chain).strip()))
        ranked = sorted(
            deduped,
            key=lambda chain: (
                self._query_overlap(chain, query),
                self._semantic_hit_count(chain, subgraph),
                len(chain),
            ),
            reverse=True,
        )
        return ranked[:4]

    def _causal_chains(self, subgraph: KnowledgeSubgraph) -> List[str]:
        node_index = self._node_index(subgraph)
        chains: List[str] = []
        for rel in subgraph.relationships or []:
            rel_type = str(rel.get("type") or "").strip()
            if rel_type not in self.causal_relation_types:
                continue
            start_name = node_index.get(str(rel.get("startNodeId") or ""), {})
            end_name = node_index.get(str(rel.get("endNodeId") or ""), {})
            if start_name or end_name:
                chains.append(f"{_node_name(start_name)} --{rel_type}--> {_node_name(end_name)}")
        return chains[:4]

    def _compositional_chains(self, subgraph: KnowledgeSubgraph) -> List[str]:
        central_names = self._names(subgraph.central_nodes)
        technique_names = self._names_by_label(subgraph, "Technique")
        flavor_names = self._names_by_label(subgraph, "Flavor")
        time_profiles = self._names_by_label(subgraph, "TimeProfile")
        difficulty_levels = self._names_by_label(subgraph, "DifficultyLevel")
        effect_names = self._names_by_semantic_label(subgraph)

        chains: List[str] = []
        subject = ", ".join(central_names[:3]) or "the target recipes"
        if technique_names:
            chains.append(f"{subject} connect to techniques: {', '.join(technique_names[:4])}.")
        if flavor_names:
            chains.append(f"{subject} connect to flavor nodes: {', '.join(flavor_names[:4])}.")
        if effect_names:
            chains.append(
                f"{subject} connect to semantic effect nodes: {', '.join(effect_names[:4])}."
            )
        if time_profiles or difficulty_levels:
            descriptors = ", ".join((time_profiles + difficulty_levels)[:4])
            chains.append(f"{subject} expose preparation constraints through: {descriptors}.")
        return chains

    def _comparative_chains(self, subgraph: KnowledgeSubgraph) -> List[str]:
        recipe_names = self._names_by_label(subgraph, "Recipe")
        if len(recipe_names) < 2:
            recipe_names = self._names(subgraph.central_nodes)
        technique_names = self._names_by_label(subgraph, "Technique")
        flavor_names = self._names_by_label(subgraph, "Flavor")
        effect_names = self._names_by_semantic_label(subgraph)

        if len(recipe_names) < 2:
            return []

        shared_features: List[str] = []
        if technique_names:
            shared_features.append("techniques " + ", ".join(technique_names[:3]))
        if flavor_names:
            shared_features.append("flavors " + ", ".join(flavor_names[:3]))
        if effect_names:
            shared_features.append("effects " + ", ".join(effect_names[:3]))

        if not shared_features:
            return [
                f"{recipe_names[0]} and {recipe_names[1]} appear in the same local graph neighborhood."
            ]

        return [
            f"{recipe_names[0]} and {recipe_names[1]} intersect through {'; '.join(shared_features[:2])}."
        ]

    def _connectivity_chains(self, subgraph: KnowledgeSubgraph) -> List[str]:
        central_names = self._names(subgraph.central_nodes)
        if not central_names:
            return []
        return [
            f"{', '.join(central_names[:3])} connect to {len(subgraph.connected_nodes)} nearby nodes through {len(subgraph.relationships)} relations."
        ]

    def _build_summary(
        self,
        subgraph: KnowledgeSubgraph,
        patterns: List[str],
        validated_chains: List[str],
    ) -> Dict[str, Any]:
        return {
            "pattern_count": len(patterns or []),
            "validated_chain_count": len(validated_chains or []),
            "central_node_count": len(subgraph.central_nodes or []),
            "connected_node_count": len(subgraph.connected_nodes or []),
            "relationship_count": len(subgraph.relationships or []),
            "semantic_node_count": self._semantic_node_count(subgraph),
        }

    @staticmethod
    def _node_index(subgraph: KnowledgeSubgraph) -> Dict[str, Dict[str, Any]]:
        index: Dict[str, Dict[str, Any]] = {}
        for node in (subgraph.central_nodes or []) + (subgraph.connected_nodes or []):
            node_id = str(node.get("nodeId") or "")
            if node_id:
                index[node_id] = node
        return index

    @staticmethod
    def _names(nodes: Iterable[Dict[str, Any]]) -> List[str]:
        return list(dict.fromkeys(_node_name(node) for node in nodes if _node_name(node)))

    def _names_by_label(self, subgraph: KnowledgeSubgraph, label: str) -> List[str]:
        nodes = [
            node
            for node in (subgraph.central_nodes or []) + (subgraph.connected_nodes or [])
            if label in _node_labels(node)
        ]
        return self._names(nodes)

    def _names_by_semantic_label(self, subgraph: KnowledgeSubgraph) -> List[str]:
        nodes = [
            node
            for node in (subgraph.central_nodes or []) + (subgraph.connected_nodes or [])
            if any(label in SEMANTIC_NODE_LABELS_SET for label in _node_labels(node))
        ]
        return self._names(nodes)

    def _semantic_node_count(self, subgraph: KnowledgeSubgraph) -> int:
        return len(self._names_by_semantic_label(subgraph))

    def _supports_comparison(self, subgraph: KnowledgeSubgraph, query: str) -> bool:
        recipe_names = self._names_by_label(subgraph, "Recipe")
        normalized_query = (query or "").lower()
        return (
            len(recipe_names) >= 2
            or len(subgraph.central_nodes or []) >= 2
            or any(term in normalized_query for term in self.comparison_markers)
        )

    @staticmethod
    def _query_overlap(text: str, query: str) -> int:
        if not query:
            return 0
        query_terms = [term for term in set(query.replace(",", " ").split()) if term.strip()]
        if query_terms:
            return sum(1 for term in query_terms if term in text)
        return sum(1 for char in set(query) if char.strip() and char in text)

    def _semantic_hit_count(self, text: str, subgraph: KnowledgeSubgraph) -> int:
        semantic_terms = set(self._names_by_semantic_label(subgraph))
        return sum(1 for term in semantic_terms if term and term in text)
