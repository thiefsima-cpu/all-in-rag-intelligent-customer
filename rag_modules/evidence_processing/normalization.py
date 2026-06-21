"""Evidence document normalization."""

from __future__ import annotations

from typing import List, Optional

from ..retrieval.contracts import EvidenceDocument
from .extraction import extract_evidence_units
from .helpers import (
    document_content,
    document_metadata,
    first_value,
    infer_evidence_type,
    stable_hash,
)
from .models import PageDocumentLike


def normalize_evidence_document(
    doc: PageDocumentLike | EvidenceDocument,
    route_strategy: Optional[str] = None,
) -> EvidenceDocument:
    content = document_content(doc)
    metadata = document_metadata(doc)
    recipe_ids = metadata.get("recipe_node_ids") or []
    recipe_id = str(first_value(metadata, ["node_id", "parent_id"], ""))
    if recipe_ids:
        recipe_id = str(recipe_ids[0])

    recipe_name = str(first_value(metadata, ["recipe_name", "name"], ""))
    source = str(
        first_value(metadata, ["search_source", "search_method", "search_type"], "unknown")
    )
    score = float(
        first_value(
            metadata,
            ["final_score", "relevance_score", "constraint_score", "score"],
            0.0,
        )
        or 0.0
    )
    doc_id = str(first_value(metadata, ["doc_id"], ""))
    if not doc_id:
        base = recipe_id or recipe_name or content[:200]
        doc_id = f"{infer_evidence_type(metadata)}::{stable_hash(str(base))}"

    graph_evidence = metadata.get("graph_evidence") or {}
    if metadata.get("merged_graph_evidence"):
        graph_evidence = {
            "primary": graph_evidence,
            "merged": metadata.get("merged_graph_evidence"),
        }
    recipe_graph_evidence = metadata.get("recipe_graph_evidence") or {}
    evidence_units = extract_evidence_units(doc, metadata)

    constraint_evidence = {
        "score": metadata.get("constraint_score"),
        "reasons": metadata.get("constraint_reasons") or [],
    }
    constraint_evidence = {
        key: value for key, value in constraint_evidence.items() if value not in (None, "", [], {})
    }

    matched_terms: List[str] = []
    for key in ("matched_keyword", "matched_terms", "matched_ingredients", "matched_steps"):
        value = metadata.get(key)
        if isinstance(value, list):
            matched_terms.extend(str(item) for item in value if item)
        elif value:
            matched_terms.append(str(value))

    evidence = EvidenceDocument(
        content=content,
        node_id=str(first_value(metadata, ["node_id", "parent_id", "recipe_id"], "")),
        doc_id=doc_id,
        recipe_id=recipe_id,
        recipe_name=recipe_name,
        source=source,
        score=score,
        evidence_type=infer_evidence_type(metadata),
        search_type=str(metadata.get("search_type") or ""),
        search_method=str(metadata.get("search_method") or metadata.get("search_source") or source),
        retrieval_level=str(metadata.get("retrieval_level") or ""),
        node_type=str(metadata.get("node_type") or metadata.get("entity_type") or ""),
        matched_terms=list(dict.fromkeys(matched_terms)),
        graph_evidence=dict(graph_evidence or {}),
        recipe_graph_evidence=dict(recipe_graph_evidence or {}),
        constraint_evidence=dict(constraint_evidence or {}),
        evidence_units=list(evidence_units),
        route_strategy=route_strategy or str(metadata.get("route_strategy") or ""),
        metadata=dict(metadata or {}),
    )
    next_metadata = dict(metadata or {})
    next_metadata.update(evidence.to_metadata())
    return evidence.copy_with(metadata=next_metadata)


def normalize_document_evidence(
    doc: PageDocumentLike | EvidenceDocument,
    route_strategy: Optional[str] = None,
) -> EvidenceDocument:
    return normalize_evidence_document(doc, route_strategy=route_strategy)


def evidence_from_document(doc: PageDocumentLike | EvidenceDocument) -> EvidenceDocument:
    return normalize_evidence_document(doc)


__all__ = [
    "evidence_from_document",
    "normalize_document_evidence",
    "normalize_evidence_document",
]
