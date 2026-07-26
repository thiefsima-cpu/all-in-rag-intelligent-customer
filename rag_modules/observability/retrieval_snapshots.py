"""Shared retrieval observability helpers."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from ..contracts import EvidenceDocument
from ..kernel.json_types import JsonObject


@dataclass
class DocumentEvidenceSnapshot:
    doc_id: str = ""
    entity_id: str = ""
    entity_name: str = ""
    source: str = ""
    score: float = 0.0
    evidence_type: str = ""
    matched_terms: list[str] = field(default_factory=list)
    has_graph_evidence: bool = False
    graph_relationships: int = 0
    constraint_evidence: JsonObject = field(default_factory=dict)

    def to_dict(self) -> JsonObject:
        return {
            "doc_id": self.doc_id,
            "entity_id": self.entity_id,
            "entity_name": self.entity_name,
            "source": self.source,
            "score": self.score,
            "evidence_type": self.evidence_type,
            "matched_terms": list(self.matched_terms),
            "has_graph_evidence": self.has_graph_evidence,
            "graph_relationships": self.graph_relationships,
            "constraint_evidence": dict(self.constraint_evidence),
        }


def summarize_document(document: EvidenceDocument) -> DocumentEvidenceSnapshot:
    graph_evidence = document.graph_evidence
    relationships = graph_evidence.get("relationships")
    return DocumentEvidenceSnapshot(
        doc_id=document.doc_id,
        entity_id=document.entity_id or document.node_id,
        entity_name=document.entity_name,
        source=document.source or document.search_method or document.search_type,
        score=document.score,
        evidence_type=document.evidence_type,
        matched_terms=list(document.matched_terms),
        has_graph_evidence=bool(graph_evidence),
        graph_relationships=len(relationships) if isinstance(relationships, list) else 0,
        constraint_evidence=dict(document.constraint_evidence),
    )


def summarize_documents(documents: Sequence[EvidenceDocument], limit: int = 10) -> list[JsonObject]:
    return [summarize_document(document).to_dict() for document in documents[:limit]]
