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

    def test_reasoning_builds_causal_compositional_comparative_chains(self) -> None:
        strategy = GraphReasoningStrategy()
        causal = next(iter(strategy.causal_relation_types))
        nodes = [
            GraphNodeSnapshot(node_id="r1", name="A", labels=("Recipe",)),
            GraphNodeSnapshot(node_id="r2", name="B", labels=("Recipe",)),
            GraphNodeSnapshot(node_id="t1", name="Fry", labels=("Technique",)),
            GraphNodeSnapshot(node_id="f1", name="Spicy", labels=("Flavor",)),
        ]
        subgraph = KnowledgeSubgraph(
            central_nodes=nodes[:2],
            connected_nodes=nodes[2:],
            relationships=[
                GraphRelationshipSnapshot(
                    relation_type=causal,
                    start_node_id="r1",
                    end_node_id="f1",
                )
            ],
        )

        outcome = strategy.reason(subgraph, "compare spicy")

        self.assertTrue({"causal", "compositional", "comparative"}.issubset(outcome.patterns))
        self.assertTrue(outcome.validated_chains)
        self.assertEqual(outcome.summary["central_node_count"], 2)
        self.assertEqual(outcome.to_trace_details()["validated_chain_count"], 4)

    def test_reasoning_uses_connectivity_when_no_named_pattern_matches(self) -> None:
        strategy = GraphReasoningStrategy()
        subgraph = KnowledgeSubgraph(
            central_nodes=[GraphNodeSnapshot(node_id="r1", name="Recipe")],
            connected_nodes=[GraphNodeSnapshot(node_id="i1", name="Ingredient")],
            relationships=[
                GraphRelationshipSnapshot(
                    relation_type="UNCLASSIFIED",
                    start_node_id="r1",
                    end_node_id="i1",
                )
            ],
        )

        outcome = strategy.reason(subgraph, "")

        self.assertEqual(outcome.patterns, ["connectivity"])
        self.assertIn("nearby nodes", outcome.validated_chains[0])

    def test_reasoning_validation_deduplicates_ranks_and_limits_four(self) -> None:
        strategy = GraphReasoningStrategy()
        result = strategy.validate_reasoning_chains(
            ["", "plain", "query semantic", "plain", "longer chain", "four", "five"],
            "query",
            KnowledgeSubgraph(
                connected_nodes=[GraphNodeSnapshot(name="semantic", labels=("Flavor",))]
            ),
        )

        self.assertEqual(result[0], "query semantic")
        self.assertEqual(len(result), 4)

    def test_reasoning_comparison_without_two_recipes_returns_no_chain(self) -> None:
        strategy = GraphReasoningStrategy()
        subgraph = KnowledgeSubgraph(
            central_nodes=[GraphNodeSnapshot(node_id="r1", name="Only", labels=("Recipe",))]
        )

        self.assertEqual(strategy.build_reasoning_chains("comparative", subgraph, "compare"), [])
        self.assertEqual(
            strategy.build_reasoning_chains("connectivity", KnowledgeSubgraph(), ""), []
        )


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

    def test_evidence_builder_handles_empty_paths_and_relationship_defaults(self) -> None:
        builder = GraphEvidenceBuilder()
        self.assertTrue(builder.build_path_description(GraphPath()))

        path = GraphPath(
            nodes=[
                GraphNodeSnapshot(node_id="r1", name="Recipe", labels=("Recipe",)),
                GraphNodeSnapshot(node_id="i1", name="Pepper", labels=("Ingredient",)),
            ],
            relationships=[GraphRelationshipSnapshot(start_node_id="r1", end_node_id="i1")],
        )

        self.assertIn("RELATED", builder.build_path_description(path))

    def test_relationship_lines_deduplicate_and_respect_limit(self) -> None:
        builder = GraphEvidenceBuilder()
        relation = GraphRelationshipSnapshot(
            relation_type="USES",
            start_node_id="r1",
            end_node_id="i1",
        )
        subgraph = KnowledgeSubgraph(
            central_nodes=[GraphNodeSnapshot(node_id="r1", name="Recipe")],
            connected_nodes=[GraphNodeSnapshot(node_id="i1", name="Pepper")],
            relationships=[relation, relation],
        )

        self.assertEqual(
            builder.relationship_lines(subgraph, limit=1),
            ["Recipe -[USES]-> Pepper"],
        )

    def test_subgraph_description_and_evidence_use_fallback_identity(self) -> None:
        builder = GraphEvidenceBuilder()
        subgraph = KnowledgeSubgraph(graph_metrics={"density": 0.25})

        [document] = builder.subgraph_to_evidence(subgraph, ["chain"], "query")

        self.assertEqual(document.node_id, "")
        self.assertEqual(document.score, 0.25)
        self.assertEqual(document.domain_graph_evidence["reasoning_chains"], ["chain"])

    def test_subgraph_description_includes_nodes_and_deduplicated_relationships(self) -> None:
        builder = GraphEvidenceBuilder()
        subgraph = KnowledgeSubgraph(
            central_nodes=[GraphNodeSnapshot(node_id="r1", name="Recipe")],
            connected_nodes=[
                GraphNodeSnapshot(node_id="i1", name="Pepper", labels=("Ingredient",))
            ],
            relationships=[
                GraphRelationshipSnapshot(
                    relation_type="USES", start_node_id="r1", end_node_id="i1"
                )
            ],
        )

        description = builder.build_subgraph_description(subgraph)

        self.assertIn("Pepper", description)
        self.assertIn("USES", description)


if __name__ == "__main__":
    unittest.main()


def test_postprocessor_handles_empty_paths_failures_and_malformed_subgraph_values() -> None:
    processor = GraphRetrievalPostProcessor()

    empty_path = processor.parse_neo4j_path({"path_nodes": []})
    assert empty_path is not None
    assert empty_path.nodes == []

    class BrokenRecord(dict[str, object]):
        def get(self, key: str, default: object = None) -> object:
            raise RuntimeError("unavailable")

    assert processor.parse_neo4j_path(BrokenRecord()) is None
    assert processor.build_knowledge_subgraph({}).central_nodes == []

    subgraph = processor.build_knowledge_subgraph(
        {
            "source": {"nodeId": "r1", "name": "Recipe", "labels": "Recipe"},
            "nodes": [None, {"nodeId": "i1", "name": "Pepper"}],
            "rels": [[{"type": "USES", "startNodeId": "r1", "endNodeId": "i1"}]],
            "metrics": {"density": "0.5", "invalid": "bad"},
        }
    )

    assert subgraph.central_nodes[0].labels == ("Recipe",)
    assert subgraph.connected_nodes[1].node_id == "i1"
    assert subgraph.relationships[0].relation_type == "USES"
    assert subgraph.graph_metrics == {"density": 0.5, "invalid": 0.0}


def test_postprocessor_merges_duplicate_subgraphs_and_ranks_evidence() -> None:
    processor = GraphRetrievalPostProcessor()
    first = KnowledgeSubgraph(
        central_nodes=[GraphNodeSnapshot(node_id="r1", name="Recipe")],
        connected_nodes=[GraphNodeSnapshot(node_id="i1", name="Pepper")],
        relationships=[
            GraphRelationshipSnapshot(relation_type="USES", start_node_id="r1", end_node_id="i1")
        ],
        graph_metrics={"density": 0.2},
    )
    second = KnowledgeSubgraph(
        central_nodes=[GraphNodeSnapshot(node_id="r1", name="Recipe")],
        connected_nodes=[GraphNodeSnapshot(node_id="i2", name="Tofu")],
        graph_metrics={"density": 0.8},
    )

    merged = processor.merge_subgraphs([first, second])

    assert {node.node_id for node in merged.connected_nodes} == {"i1", "i2"}
    assert merged.graph_metrics["density"] == 1 / 3
    assert merged.graph_metrics["source_subgraph_count"] == 2.0
