"""Evidence document normalization."""

from __future__ import annotations

from dataclasses import replace

from ..contracts import EvidenceDocument, JsonObject, coerce_float, coerce_json_object
from .extraction import extract_evidence_units
from .helpers import (
    document_content,
    document_metadata,
    first_value,
    infer_evidence_type,
    stable_hash,
)


def _matched_terms(metadata: JsonObject) -> list[str]:
    matched_terms: list[str] = []
    for key in (
        "matched_keyword",
        "matched_terms",
        "matched_entities",
        "matched_attributes",
    ):
        value = metadata.get(key)
        if isinstance(value, list):
            matched_terms.extend(str(item) for item in value if item)
        elif value:
            matched_terms.append(str(value))
    return list(dict.fromkeys(matched_terms))


def normalize_evidence_document(
    document: EvidenceDocument,
    route_strategy: str | None = None,
) -> EvidenceDocument:
    content = document_content(document)
    metadata = document_metadata(document)
    entity_id = str(first_value(metadata, ["entity_id", "node_id", "parent_id"], ""))
    entity_name = str(first_value(metadata, ["entity_name", "name"], ""))
    entity_type = str(first_value(metadata, ["entity_type", "node_type"], ""))
    source = str(
        first_value(metadata, ["search_source", "search_method", "search_type"], "unknown")
    )
    score = coerce_float(
        first_value(
            metadata,
            ["final_score", "relevance_score", "constraint_score", "score"],
            0.0,
        )
    )
    doc_id = str(first_value(metadata, ["doc_id"], ""))
    if not doc_id:
        base = entity_id or entity_name or content[:200]
        doc_id = f"{infer_evidence_type(metadata)}::{stable_hash(str(base))}"

    graph_evidence = metadata.get("graph_evidence") or {}
    if metadata.get("merged_graph_evidence"):
        graph_evidence = {
            "primary": graph_evidence,
            "merged": metadata.get("merged_graph_evidence"),
        }
    domain_graph_evidence = metadata.get("domain_graph_evidence") or {}
    evidence_units = extract_evidence_units(document, metadata)

    constraint_evidence = {
        "score": metadata.get("constraint_score"),
        "reasons": metadata.get("constraint_reasons") or [],
    }
    constraint_evidence = {
        key: value for key, value in constraint_evidence.items() if value not in (None, "", [], {})
    }

    evidence = EvidenceDocument(
        content=content,
        entity_id=entity_id,
        entity_name=entity_name,
        entity_type=entity_type,
        node_id=str(first_value(metadata, ["node_id", "entity_id", "parent_id"], "")),
        doc_id=doc_id,
        source=source,
        score=score,
        evidence_type=infer_evidence_type(metadata),
        search_type=str(metadata.get("search_type") or ""),
        search_method=str(metadata.get("search_method") or metadata.get("search_source") or source),
        retrieval_level=str(metadata.get("retrieval_level") or ""),
        node_type=str(metadata.get("node_type") or metadata.get("entity_type") or ""),
        matched_terms=_matched_terms(metadata),
        graph_evidence=coerce_json_object(graph_evidence),
        domain_graph_evidence=coerce_json_object(domain_graph_evidence),
        constraint_evidence=coerce_json_object(constraint_evidence),
        evidence_units=list(evidence_units),
        route_strategy=route_strategy or str(metadata.get("route_strategy") or ""),
        metadata=metadata,
    )
    next_metadata = dict(metadata or {})
    next_metadata.update(evidence.to_metadata())
    return replace(evidence, metadata=next_metadata)


def normalize_document_evidence(
    document: EvidenceDocument,
    route_strategy: str | None = None,
) -> EvidenceDocument:
    return normalize_evidence_document(document, route_strategy=route_strategy)


def evidence_from_document(document: EvidenceDocument) -> EvidenceDocument:
    return normalize_evidence_document(document)


__all__ = [
    "evidence_from_document",
    "normalize_document_evidence",
    "normalize_evidence_document",
]
