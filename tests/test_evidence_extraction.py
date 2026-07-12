from __future__ import annotations

from rag_modules.evidence_processing.extraction import extract_evidence_units
from rag_modules.evidence_processing.models import EvidenceUnit
from rag_modules.kernel.documents import TextDocument


def test_extracts_explicit_primary_and_merged_graph_units_with_deduplication() -> None:
    explicit = EvidenceUnit(
        unit_id="explicit",
        evidence_type="text",
        claim="explicit claim",
        source="vector",
    )
    metadata = {
        "search_source": "graph",
        "final_score": 0.9,
        "recipe_node_ids": ["r1"],
        "recipe_names": ["Mapo tofu"],
        "matched_terms": ["tofu", "tofu"],
        "evidence_units": [
            explicit,
            {"claim": "dict claim", "entities": ["tofu", ""], "metadata": {"rank": 1}},
            {"ignored": True},
        ],
        "graph_evidence": {
            "primary": {
                "description": "graph summary",
                "nodes": [
                    {"id": "r1", "name": "Mapo tofu"},
                    {"nodeId": "i1", "title": "Pepper"},
                    {"name": "missing id"},
                ],
                "relationships": [
                    "Mapo tofu -[USES]-> Pepper",
                    {"type": "USES", "startNodeId": "r1", "endNodeId": "i1"},
                    {"relation_type": "RELATED", "source_name": "Tofu"},
                    None,
                    "",
                ],
            },
            "merged": [
                {"relationships": [{"source_id": "r1", "target_id": "i1"}]},
                "invalid",
            ],
        },
    }

    units = extract_evidence_units(TextDocument(content="fallback", metadata=metadata))
    claims = [unit["claim"] for unit in units]

    assert "explicit claim" in claims
    assert "dict claim" in claims
    assert "graph summary" in claims
    assert "Mapo tofu -[USES]-> Pepper" in claims
    assert len({unit["unit_id"] for unit in units}) == len(units)


def test_extracts_direct_graph_payload_and_metadata_recipe_fallbacks() -> None:
    metadata = {
        "search_method": "neo4j",
        "score": 0.4,
        "recipe_id": "r2",
        "recipe_name": "Soup",
        "graph_evidence": {
            "connected_nodes": [{"id": "a"}, {"id": "b", "name": "Broth"}],
            "relationships": [{"relation_type": "RELATED", "startNodeId": "a", "endNodeId": "b"}],
        },
    }

    [unit] = extract_evidence_units(TextDocument(content="ignored", metadata=metadata))

    assert unit["claim"] == "a -[RELATED]-> Broth"
    assert unit["recipe_id"] == "r2"
    assert unit["source"] == "neo4j"


def test_falls_back_to_trimmed_document_claim_and_handles_empty_content() -> None:
    long_content = "x" * 300
    [unit] = extract_evidence_units(
        TextDocument(
            content=long_content,
            metadata={"node_id": "r3", "recipe_name": "Soup", "search_type": "vector"},
        )
    )

    assert len(unit["claim"]) == 260
    assert unit["entities"] == ["Soup"]
    assert unit["is_graph_evidence"] is False
    assert extract_evidence_units(TextDocument(content="", metadata={})) == []
