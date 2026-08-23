"""
Deterministic graph reasoning over retrieved subgraphs.

The retrieval layer already materializes graph structure. This strategy turns
that structure into compact reasoning chains without coupling the logic to the
retrieval facade.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field

from ..domains.contracts import DomainReasoningVocabulary
from ..kernel.json_types import JsonObject
from ..query_policy import get_query_policy
from ..query_policy.models import QueryPolicyBundle
from .retrieval_types import GraphNodeSnapshot, KnowledgeSubgraph


def _node_labels(node: GraphNodeSnapshot) -> list[str]:
    return list(node.labels)


def _node_name(node: GraphNodeSnapshot) -> str:
    return node.name or node.node_id or "unknown_node"


@dataclass
class GraphReasoningOutcome:
    patterns: list[str] = field(default_factory=list)
    candidate_chains: list[str] = field(default_factory=list)
    validated_chains: list[str] = field(default_factory=list)
    summary: JsonObject = field(default_factory=dict)

    def to_trace_details(self) -> JsonObject:
        return {
            "patterns": list(self.patterns or []),
            "candidate_chain_count": len(self.candidate_chains or []),
            "validated_chain_count": len(self.validated_chains or []),
            "validated_chains": list(self.validated_chains or []),
            "summary": dict(self.summary or {}),
        }


class GraphReasoningStrategy:
    """Produce compact reasoning chains from a knowledge subgraph."""

    def __init__(
        self,
        *,
        policy_bundle: QueryPolicyBundle | None = None,
        vocabulary: DomainReasoningVocabulary | None = None,
    ) -> None:
        self.policy_bundle = policy_bundle or get_query_policy()
        self.vocabulary = vocabulary or DomainReasoningVocabulary()
        reasoning_policy = self.policy_bundle.graph.reasoning
        self.causal_relation_types = set(reasoning_policy.causal_relation_types)
        self.compositional_relation_types = set(reasoning_policy.compositional_relation_types)
        self.comparison_markers = tuple(
            marker.lower() for marker in reasoning_policy.comparison_markers
        )

    def reason(self, subgraph: KnowledgeSubgraph, query: str) -> GraphReasoningOutcome:
        patterns = self.identify_reasoning_patterns(subgraph, query)
        candidate_chains: list[str] = []
        for pattern in patterns:
            candidate_chains.extend(self.build_reasoning_chains(pattern, subgraph, query))
        validated_chains = self.validate_reasoning_chains(candidate_chains, query, subgraph)
        return GraphReasoningOutcome(
            patterns=patterns,
            candidate_chains=candidate_chains,
            validated_chains=validated_chains,
            summary=self._build_summary(subgraph, patterns, validated_chains),
        )

    def identify_reasoning_patterns(self, subgraph: KnowledgeSubgraph, query: str) -> list[str]:
        relation_types = {
            rel.relation_type.strip()
            for rel in (subgraph.relationships or [])
            if rel.relation_type.strip()
        }
        patterns: list[str] = []
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
    ) -> list[str]:
        del query
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
    ) -> list[str]:
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

    def _causal_chains(self, subgraph: KnowledgeSubgraph) -> list[str]:
        node_index = self._node_index(subgraph)
        chains: list[str] = []
        for rel in subgraph.relationships or []:
            rel_type = rel.relation_type.strip()
            if rel_type not in self.causal_relation_types:
                continue
            start_node = node_index.get(rel.start_node_id)
            end_node = node_index.get(rel.end_node_id)
            if start_node or end_node:
                chains.append(
                    f"{_node_name(start_node or GraphNodeSnapshot())} "
                    f"--{rel_type}--> {_node_name(end_node or GraphNodeSnapshot())}"
                )
        return chains[:4]

    def _compositional_chains(self, subgraph: KnowledgeSubgraph) -> list[str]:
        central_names = self._names(subgraph.central_nodes)
        effect_names = self._names_by_semantic_label(subgraph)

        chains: list[str] = []
        subject = ", ".join(central_names[:3]) or self.vocabulary.subject_fallback
        for node_label, display_label in self.vocabulary.compositional_labels:
            names = self._names_by_label(subgraph, node_label)
            if names:
                chains.append(f"{subject} connect to {display_label}: {', '.join(names[:4])}.")
        if effect_names:
            chains.append(
                f"{subject} connect to {self.vocabulary.semantic_effect_label}: "
                f"{', '.join(effect_names[:4])}."
            )
        constraint_names = [
            name
            for node_label, _display_label in self.vocabulary.constraint_labels
            for name in self._names_by_label(subgraph, node_label)
        ]
        if constraint_names:
            chains.append(
                f"{subject} expose domain constraints through: {', '.join(constraint_names[:4])}."
            )
        return chains

    def _comparative_chains(self, subgraph: KnowledgeSubgraph) -> list[str]:
        entity_names = self._comparison_names(subgraph)
        effect_names = self._names_by_semantic_label(subgraph)

        if len(entity_names) < 2:
            return []

        shared_features: list[str] = []
        for node_label, display_label in self.vocabulary.compositional_labels:
            names = self._names_by_label(subgraph, node_label)
            if names:
                shared_features.append(f"{display_label} {', '.join(names[:3])}")
        if effect_names:
            shared_features.append(
                f"{self.vocabulary.semantic_effect_label} {', '.join(effect_names[:3])}"
            )

        if not shared_features:
            return [
                f"{entity_names[0]} and {entity_names[1]} appear in the same local graph neighborhood."
            ]

        return [
            f"{entity_names[0]} and {entity_names[1]} intersect through "
            f"{'; '.join(shared_features[:2])}."
        ]

    def _connectivity_chains(self, subgraph: KnowledgeSubgraph) -> list[str]:
        central_names = self._names(subgraph.central_nodes)
        if not central_names:
            return []
        return [
            f"{', '.join(central_names[:3])} connect to {len(subgraph.connected_nodes)} nearby nodes through {len(subgraph.relationships)} relations."
        ]

    def _build_summary(
        self,
        subgraph: KnowledgeSubgraph,
        patterns: list[str],
        validated_chains: list[str],
    ) -> JsonObject:
        return {
            "pattern_count": len(patterns or []),
            "validated_chain_count": len(validated_chains or []),
            "central_node_count": len(subgraph.central_nodes or []),
            "connected_node_count": len(subgraph.connected_nodes or []),
            "relationship_count": len(subgraph.relationships or []),
            "semantic_node_count": self._semantic_node_count(subgraph),
        }

    @staticmethod
    def _node_index(subgraph: KnowledgeSubgraph) -> dict[str, GraphNodeSnapshot]:
        index: dict[str, GraphNodeSnapshot] = {}
        for node in (subgraph.central_nodes or []) + (subgraph.connected_nodes or []):
            if node.node_id:
                index[node.node_id] = node
        return index

    @staticmethod
    def _names(nodes: Iterable[GraphNodeSnapshot]) -> list[str]:
        return list(dict.fromkeys(_node_name(node) for node in nodes if _node_name(node)))

    def _names_by_label(self, subgraph: KnowledgeSubgraph, label: str) -> list[str]:
        nodes = [
            node
            for node in (subgraph.central_nodes or []) + (subgraph.connected_nodes or [])
            if label in _node_labels(node)
        ]
        return self._names(nodes)

    def _names_by_semantic_label(self, subgraph: KnowledgeSubgraph) -> list[str]:
        semantic_labels = set(self.vocabulary.semantic_node_labels)
        nodes = [
            node
            for node in (subgraph.central_nodes or []) + (subgraph.connected_nodes or [])
            if any(label in semantic_labels for label in _node_labels(node))
        ]
        return self._names(nodes)

    def _semantic_node_count(self, subgraph: KnowledgeSubgraph) -> int:
        return len(self._names_by_semantic_label(subgraph))

    def _supports_comparison(self, subgraph: KnowledgeSubgraph, query: str) -> bool:
        entity_names = self._comparison_names(subgraph)
        normalized_query = (query or "").lower()
        return (
            len(entity_names) >= 2
            or len(subgraph.central_nodes or []) >= 2
            or any(term in normalized_query for term in self.comparison_markers)
        )

    def _comparison_names(self, subgraph: KnowledgeSubgraph) -> list[str]:
        names = [
            name
            for label in self.vocabulary.comparison_labels
            for name in self._names_by_label(subgraph, label)
        ]
        return list(dict.fromkeys(names)) or self._names(subgraph.central_nodes)

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
