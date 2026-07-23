from __future__ import annotations

from rag_modules.contracts import EvidenceDocument
from rag_modules.graph.path_ranker import GraphDocumentRanker
from tests.configuration_test_helpers import build_test_config


def _ranker() -> GraphDocumentRanker:
    return GraphDocumentRanker(build_test_config().graph)


def test_rank_rewards_semantic_relationships_recipe_identity_and_query_overlap() -> None:
    rich = EvidenceDocument(
        content="pepper aroma",
        entity_name="Mapo tofu",
        score=0.1,
        evidence_units=[{"claim": "aroma"}],
        graph_evidence={"relationships": [{"type": "CONTRIBUTES_TO"}]},
        metadata={"recipe_node_ids": ["r1"], "relevance_score": 0.2},
    )
    plain = EvidenceDocument(content="unrelated", score=0.2)

    assert _ranker().rank([plain, rich], "pepper")[0] is rich


def test_score_uses_semantic_count_fallback_and_handles_empty_query() -> None:
    document = EvidenceDocument(
        content="graph",
        graph_evidence={"semantic_relationship_count": 2},
        metadata={"final_score": 0.5, "recipe_names": ["Mapo tofu"]},
    )

    assert _ranker()._score(document, "") > 0.5


def test_relationships_collect_only_mapping_values_from_both_shapes() -> None:
    document = EvidenceDocument(
        content="graph",
        graph_evidence={"relationships": [{"type": "A"}, "invalid"]},
        domain_graph_evidence={"semantic_relations": [{"type": "B"}, 7]},
    )

    assert _ranker()._relationships(document) == [{"type": "A"}, {"type": "B"}]


def test_query_overlap_reads_content_and_string_metadata_only() -> None:
    document = EvidenceDocument(
        content="pepper",
        metadata={"description": "aroma", "ignored": ["tofu"]},
    )

    assert _ranker()._query_overlap(document, "pepper aroma") > 0
    assert _ranker()._query_overlap(document, "") == 0


def test_dedupe_merges_duplicate_recipe_evidence_without_reordering() -> None:
    first = EvidenceDocument(
        content="first",
        score=0.2,
        metadata={"recipe_node_ids": ["r1"], "relationship_count": 1},
    )
    duplicate = EvidenceDocument(
        content="second",
        score=0.9,
        graph_evidence={"description": "path"},
        metadata={"recipe_node_ids": ["r1"], "relationship_count": 3},
    )
    by_name = EvidenceDocument(content="third", metadata={"recipe_names": ["Other"]})

    merged = _ranker().dedupe([first, duplicate, by_name])

    assert [doc.content for doc in merged] == ["first\nsecond", "third"]
    assert merged[0].score == 0.9
    assert merged[0].metadata["relationship_count"] == 3
    assert merged[0].metadata["merged_graph_evidence"] == [{"description": "path"}]


def test_dedupe_keeps_identical_duplicate_content_once() -> None:
    first = EvidenceDocument(content="same", entity_name="Recipe")
    duplicate = EvidenceDocument(content="same", entity_name="Recipe")

    [merged] = _ranker().dedupe([first, duplicate])

    assert merged.content == "same"
    assert "merged_graph_evidence" not in merged.metadata


def test_dedupe_key_prefers_recipe_id_then_name_then_document_key() -> None:
    ranker = _ranker()

    assert (
        ranker._dedupe_key(EvidenceDocument(content="x", metadata={"recipe_node_ids": ["r1"]}))
        == "recipe_id::r1"
    )
    assert (
        ranker._dedupe_key(EvidenceDocument(content="x", metadata={"recipe_names": ["Mapo tofu"]}))
        == "recipe_name::Mapo tofu"
    )
    assert ranker._dedupe_key(EvidenceDocument(content="x", node_id="n1")) == "n1"
