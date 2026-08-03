from __future__ import annotations

from rag_modules.contracts import EvidenceDocument
from rag_modules.contracts.retrieval_documents import evidence_document_from_text_document
from rag_modules.evidence_processing.extraction import extract_evidence_units
from rag_modules.evidence_processing.models import EvidenceUnit
from rag_modules.evidence_processing.normalization import normalize_evidence_document
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
        "entity_ids": ["r1"],
        "entity_names": ["Mapo tofu"],
        "matched_terms": ["tofu", "tofu"],
        "evidence_units": [
            explicit.to_dict(),
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

    units = extract_evidence_units(
        evidence_document_from_text_document(TextDocument(content="fallback", metadata=metadata))
    )
    claims = [unit["claim"] for unit in units]

    assert "explicit claim" in claims
    assert "dict claim" in claims
    assert "graph summary" in claims
    assert "Mapo tofu -[USES]-> Pepper" in claims
    assert len({unit["unit_id"] for unit in units}) == len(units)


def test_extracts_direct_graph_payload_and_generic_entity_metadata() -> None:
    metadata = {
        "search_method": "neo4j",
        "score": 0.4,
        "entity_id": "r2",
        "entity_name": "Soup",
        "graph_evidence": {
            "connected_nodes": [{"id": "a"}, {"id": "b", "name": "Broth"}],
            "relationships": [{"relation_type": "RELATED", "startNodeId": "a", "endNodeId": "b"}],
        },
    }

    [unit] = extract_evidence_units(
        evidence_document_from_text_document(TextDocument(content="ignored", metadata=metadata))
    )

    assert unit["claim"] == "a -[RELATED]-> Broth"
    assert unit["entity_id"] == "r2"
    assert "recipe_id" not in unit
    assert "recipe_name" not in unit
    assert unit["source"] == "neo4j"


def test_falls_back_to_trimmed_document_claim_and_handles_empty_content() -> None:
    long_content = "x" * 300
    [unit] = extract_evidence_units(
        evidence_document_from_text_document(
            TextDocument(
                content=long_content,
                metadata={"node_id": "r3", "entity_name": "Soup", "search_type": "vector"},
            )
        )
    )

    assert len(unit["claim"]) == 260
    assert unit["entities"] == ["Soup"]
    assert unit["is_graph_evidence"] is False
    assert (
        extract_evidence_units(
            evidence_document_from_text_document(TextDocument(content="", metadata={}))
        )
        == []
    )


def test_evidence_unit_serializes_canonical_fields_for_recipe_domain() -> None:
    unit = EvidenceUnit(
        unit_id="unit-1",
        evidence_type="text",
        claim="canonical",
        entity_id="r1",
        entity_name="Mapo tofu",
        domain="recipe",
    )

    payload = unit.to_dict()

    assert payload["entity_id"] == "r1"
    assert payload["entity_name"] == "Mapo tofu"
    assert "recipe_id" not in payload
    assert "recipe_name" not in payload


def test_normalization_ignores_deprecated_recipe_graph_evidence() -> None:
    evidence = normalize_evidence_document(
        EvidenceDocument(
            content="legacy graph payload",
            metadata={"recipe_graph_evidence": {"legacy": True}},
        )
    )

    assert evidence.domain_graph_evidence == {}
