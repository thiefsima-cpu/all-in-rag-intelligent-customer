from __future__ import annotations

from rag_modules.contracts import EvidenceDocument
from rag_modules.kernel.documents import TextDocument
from rag_modules.retrieval.parent_doc_enricher import ParentDocumentEnricher
from tests.configuration_test_helpers import build_test_config


def _enricher(*documents: TextDocument) -> ParentDocumentEnricher:
    config = build_test_config({"retrieval": {"parent_doc_top_n": 1, "parent_doc_max_chars": 5}})
    return ParentDocumentEnricher(config, documents)


def test_rebuild_indexes_only_documents_with_node_ids() -> None:
    enricher = _enricher()
    parent = TextDocument(content="parent", metadata={"node_id": 7})

    mapping = enricher.rebuild([TextDocument(content="ignored", metadata={}), parent])

    assert mapping == {"7": parent}


def test_attach_respects_top_n_missing_parent_and_truncation() -> None:
    enricher = _enricher(
        TextDocument(
            content="123456",
            metadata={"node_id": "recipe-1", "recipe_name": "Mapo tofu"},
        )
    )
    docs = [
        TextDocument(content="chunk", metadata={"parent_id": "recipe-1"}),
        TextDocument(content="second", metadata={"node_id": "recipe-1"}),
        TextDocument(content="missing", metadata={"node_id": "unknown"}),
    ]

    result = enricher.attach(docs)

    assert result[0].content == "12345... (truncated parent document)"
    assert result[0].metadata == docs[0].metadata
    assert result[1] is docs[1]
    assert result[2] is docs[2]


def test_attach_returns_originals_when_parent_map_is_empty() -> None:
    docs = [TextDocument(content="chunk")]
    evidence = [EvidenceDocument(content="chunk")]
    enricher = _enricher()

    assert enricher.attach(docs) is docs
    assert enricher.attach_evidence(evidence) is evidence


def test_attach_evidence_fills_parent_identity_without_overwriting_child_values() -> None:
    enricher = _enricher(
        TextDocument(
            content="short",
            metadata={"node_id": "recipe-1", "recipe_name": "Parent recipe"},
        )
    )
    inherited = EvidenceDocument(content="chunk", metadata={"parent_id": "recipe-1"})
    explicit = EvidenceDocument(
        content="chunk",
        node_id="recipe-1",
        entity_name="Child recipe",
    )

    first, second = enricher.attach_evidence([inherited, explicit], top_n=2)

    assert first.node_id == "recipe-1"
    assert first.entity_name == "Parent recipe"
    assert first.metadata["entity_name"] == "Parent recipe"
    assert second.entity_name == "Child recipe"


def test_graph_enrichment_finds_parent_by_recipe_lists_and_preserves_graph_source() -> None:
    enricher = _enricher(
        TextDocument(
            content="parent",
            metadata={"node_id": "recipe-1", "recipe_name": "Mapo tofu"},
        )
    )
    by_id = TextDocument(
        content="graph detail",
        metadata={"recipe_node_ids": ["missing", "recipe-1"], "search_type": "path"},
    )
    by_name = TextDocument(
        content="parent",
        metadata={"recipe_names": ["Mapo tofu"], "search_source": "graph"},
    )

    first, second = enricher.enrich_graph_documents([by_id, by_name], top_n=0)

    assert "[Graph retrieval evidence]" in first.content
    assert first.metadata["search_source"] == "path"
    assert second.content == "parent"
    assert second.metadata["search_source"] == "graph"


def test_graph_evidence_inherits_parent_metadata_and_appends_context() -> None:
    enricher = _enricher(
        TextDocument(
            content="parent",
            metadata={
                "node_id": "recipe-1",
                "recipe_id": "recipe-id",
                "recipe_name": "Mapo tofu",
            },
        )
    )
    graph = EvidenceDocument(
        content="graph detail",
        search_type="graph_path",
        metadata={"recipe_names": ["Mapo tofu"]},
    )

    [result] = enricher.enrich_graph_evidence_documents([graph], top_n=0)

    assert result.node_id == "recipe-1"
    assert result.entity_id == "recipe-id"
    assert result.entity_name == "Mapo tofu"
    assert result.metadata["search_source"] == "graph_path"
    assert "[Graph retrieval evidence]" in result.content


def test_graph_enrichment_returns_originals_for_empty_input_or_missing_parent() -> None:
    empty = _enricher()
    docs = [EvidenceDocument(content="graph", metadata={"recipe_name": "unknown"})]

    assert empty.enrich_graph_evidence_documents(docs) is docs
    populated = _enricher(TextDocument(content="parent", metadata={"node_id": "recipe-1"}))
    assert populated.enrich_graph_evidence_documents(docs)[0] is docs[0]


def test_find_parent_uses_direct_keys_and_recipe_name_fallbacks() -> None:
    parent = TextDocument(
        content="parent",
        metadata={"node_id": "recipe-1", "recipe_name": "Mapo tofu"},
    )
    enricher = _enricher(parent)

    assert enricher._find_parent({"recipe_id": "recipe-1"}) is parent
    assert enricher._find_parent({"recipe_name": "Mapo tofu"}) is parent
    assert enricher._find_parent({"recipe_name": "unknown"}) is None
