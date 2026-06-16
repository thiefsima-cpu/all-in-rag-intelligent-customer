"""Shared retrieval observability helpers."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List

from .retrieval.contracts import EvidenceDocument, ensure_evidence_documents


@dataclass
class DocumentEvidenceSnapshot:
    doc_id: str = ""
    recipe_id: str = ""
    recipe_name: str = ""
    source: str = ""
    score: Any = 0.0
    evidence_type: str = ""
    matched_terms: List[str] = field(default_factory=list)
    has_graph_evidence: bool = False
    graph_relationships: int = 0
    constraint_evidence: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def summarize_document(doc: EvidenceDocument) -> DocumentEvidenceSnapshot:
    graph_evidence = doc.graph_evidence or {}
    return DocumentEvidenceSnapshot(
        doc_id=str(doc.doc_id or ""),
        recipe_id=str(doc.recipe_id or doc.node_id or ""),
        recipe_name=str(doc.recipe_name or ""),
        source=str(doc.source or doc.search_method or doc.search_type or ""),
        score=doc.score,
        evidence_type=str(doc.evidence_type or ""),
        matched_terms=list(doc.matched_terms or []),
        has_graph_evidence=bool(graph_evidence),
        graph_relationships=len(graph_evidence.get("relationships") or []),
        constraint_evidence=dict(doc.constraint_evidence or {}),
    )


def summarize_documents(documents: List[EvidenceDocument], limit: int = 10) -> List[Dict[str, Any]]:
    return [summarize_document(doc).to_dict() for doc in (documents or [])[:limit]]


def summarize_any_documents(documents, limit: int = 10) -> List[Dict[str, Any]]:
    return summarize_documents(ensure_evidence_documents(documents), limit=limit)
