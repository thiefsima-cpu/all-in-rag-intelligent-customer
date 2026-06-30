from __future__ import annotations

import unittest

from rag_modules.graph.reasoning_strategy import GraphReasoningStrategy
from rag_modules.graph.retrieval_types import KnowledgeSubgraph
from rag_modules.query_policy import get_query_policy


class GraphReasoningStrategyTests(unittest.TestCase):
    def test_reasoning_patterns_use_policy_relation_groups(self) -> None:
        policy = get_query_policy().graph.reasoning
        causal_relation = policy.causal_relation_types[0]
        compositional_relation = policy.compositional_relation_types[0]
        subgraph = KnowledgeSubgraph(
            central_nodes=[{"nodeId": "r1", "name": "mapo tofu", "labels": ["Recipe"]}],
            connected_nodes=[
                {"nodeId": "e1", "name": "umami", "labels": ["SemanticEffect"]},
                {"nodeId": "f1", "name": "spicy", "labels": ["Flavor"]},
            ],
            relationships=[
                {"type": causal_relation, "startNodeId": "r1", "endNodeId": "e1"},
                {"type": compositional_relation, "startNodeId": "r1", "endNodeId": "f1"},
            ],
        )

        patterns = GraphReasoningStrategy().identify_reasoning_patterns(subgraph, "why")

        self.assertIn("causal", patterns)
        self.assertIn("compositional", patterns)

    def test_comparison_markers_are_policy_driven(self) -> None:
        subgraph = KnowledgeSubgraph(
            central_nodes=[{"nodeId": "r1", "name": "mapo tofu", "labels": ["Recipe"]}],
            connected_nodes=[],
            relationships=[],
        )

        patterns = GraphReasoningStrategy().identify_reasoning_patterns(
            subgraph,
            "is this the same preparation?",
        )

        self.assertIn("comparative", patterns)


if __name__ == "__main__":
    unittest.main()
