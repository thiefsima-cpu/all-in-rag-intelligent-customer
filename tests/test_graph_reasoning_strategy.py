from __future__ import annotations

import unittest

from rag_modules.graph.evidence_builder import GraphEvidenceBuilder
from rag_modules.graph.reasoning_strategy import GraphReasoningStrategy
from rag_modules.graph.retrieval_postprocess import GraphRetrievalPostProcessor
from rag_modules.graph.retrieval_types import (
    GraphNodeSnapshot,
    GraphPath,
    GraphRelationshipSnapshot,
    KnowledgeSubgraph,
)
from rag_modules.query_policy import get_query_policy


class GraphReasoningStrategyTests(unittest.TestCase):
    def test_reasoning_patterns_use_policy_relation_groups(self) -> None:
        policy = get_query_policy().graph.reasoning
        causal_relation = policy.causal_relation_types[0]
        compositional_relation = policy.compositional_relation_types[0]
        subgraph = KnowledgeSubgraph(
            central_nodes=[GraphNodeSnapshot(node_id="r1", name="mapo tofu", labels=("Recipe",))],
            connected_nodes=[
                GraphNodeSnapshot(node_id="e1", name="umami", labels=("SemanticEffect",)),
                GraphNodeSnapshot(node_id="f1", name="spicy", labels=("Flavor",)),
            ],
            relationships=[
                GraphRelationshipSnapshot(
                    relation_type=causal_relation,
                    start_node_id="r1",
                    end_node_id="e1",
                ),
                GraphRelationshipSnapshot(
                    relation_type=compositional_relation,
                    start_node_id="r1",
                    end_node_id="f1",
                ),
            ],
        )

        patterns = GraphReasoningStrategy().identify_reasoning_patterns(subgraph, "why")

        self.assertIn("causal", patterns)
        self.assertIn("compositional", patterns)

    def test_comparison_markers_are_policy_driven(self) -> None:
        subgraph = KnowledgeSubgraph(
            central_nodes=[GraphNodeSnapshot(node_id="r1", name="mapo tofu", labels=("Recipe",))],
            connected_nodes=[],
            relationships=[],
        )

        patterns = GraphReasoningStrategy().identify_reasoning_patterns(
            subgraph,
            "is this the same preparation?",
        )

        self.assertIn("comparative", patterns)


class _FakeNeo4jNode(dict):
    def __init__(self, node_id: str, name: str, labels: tuple[str, ...]) -> None:
        super().__init__({"nodeId": node_id, "name": name})
        self.labels = labels


class _FakeNeo4jRelationship(dict):
    type = "RELATED_TO"

    def __init__(self, start_node: _FakeNeo4jNode, end_node: _FakeNeo4jNode) -> None:
        super().__init__({"weight": 0.8})
        self.start_node = start_node
        self.end_node = end_node


class GraphRetrievalDtoBoundaryTests(unittest.TestCase):
    def test_parse_neo4j_path_preserves_relationship_type_and_endpoints(self) -> None:
        start_node = _FakeNeo4jNode("r1", "mapo tofu", ("Recipe",))
        end_node = _FakeNeo4jNode("i1", "pepper", ("Ingredient",))
        relationship = _FakeNeo4jRelationship(start_node, end_node)

        path = GraphRetrievalPostProcessor().parse_neo4j_path(
            {
                "path_nodes": [start_node, end_node],
                "rels": [relationship],
                "path_len": 1,
                "relevance": 0.9,
            }
        )

        self.assertIsNotNone(path)
        assert path is not None
        self.assertEqual(path.relationships[0].relation_type, "RELATED_TO")
        self.assertEqual(path.relationships[0].start_node_id, "r1")
        self.assertEqual(path.relationships[0].end_node_id, "i1")

    def test_snapshot_factories_preserve_top_level_extra_fields(self) -> None:
        node = GraphNodeSnapshot.from_mapping(
            {
                "nodeId": "r1",
                "name": "mapo tofu",
                "labels": ["Recipe"],
                "category": "main",
                "score": 0.75,
            }
        )
        relationship = GraphRelationshipSnapshot.from_mapping(
            {
                "type": "RELATED_TO",
                "startNodeId": "r1",
                "endNodeId": "i1",
                "weight": 0.8,
            }
        )

        self.assertEqual(node.properties["score"], 0.75)
        self.assertEqual(node.to_dict()["score"], 0.75)
        self.assertEqual(relationship.properties["weight"], 0.8)
        self.assertEqual(relationship.to_dict()["weight"], 0.8)

    def test_path_evidence_uses_legacy_graph_evidence_shape(self) -> None:
        path = GraphPath(
            nodes=[
                GraphNodeSnapshot(
                    node_id="r1",
                    name="mapo tofu",
                    labels=("Recipe",),
                    properties={"nodeId": "r1", "name": "mapo tofu", "source": "graph"},
                ),
                GraphNodeSnapshot(
                    node_id="i1",
                    name="pepper",
                    labels=("Ingredient",),
                    properties={"nodeId": "i1", "name": "pepper"},
                ),
            ],
            relationships=[
                GraphRelationshipSnapshot(
                    relation_type="RELATED_TO",
                    start_node_id="r1",
                    end_node_id="i1",
                    properties={"weight": 0.8},
                )
            ],
            path_length=1,
            relevance_score=0.9,
            path_type="multi_hop",
        )

        [document] = GraphEvidenceBuilder().paths_to_evidence([path], "why")
        graph_evidence = document.metadata["graph_evidence"]

        self.assertEqual(
            graph_evidence["nodes"][0],
            {
                "id": "r1",
                "name": "mapo tofu",
                "labels": ["Recipe"],
                "properties": {"nodeId": "r1", "name": "mapo tofu", "source": "graph"},
            },
        )
        self.assertEqual(
            graph_evidence["relationships"][0],
            {
                "type": "RELATED_TO",
                "properties": {
                    "weight": 0.8,
                    "startNodeId": "r1",
                    "endNodeId": "i1",
                },
            },
        )


if __name__ == "__main__":
    unittest.main()
