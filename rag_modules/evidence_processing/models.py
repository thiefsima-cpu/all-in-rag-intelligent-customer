"""Evidence data models."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Protocol

from ..contracts import EvidenceDocument


class PageDocumentLike(Protocol):
    page_content: str
    metadata: Dict[str, Any]


@dataclass
class EvidenceUnit:
    unit_id: str
    evidence_type: str
    claim: str
    source: str = "unknown"
    score: float = 0.0
    entity_id: str = ""
    entity_name: str = ""
    domain: str = ""
    relation_type: str = ""
    entities: List[str] = field(default_factory=list)
    is_graph_evidence: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        payload = {
            "unit_id": self.unit_id,
            "evidence_type": self.evidence_type,
            "claim": self.claim,
            "source": self.source,
            "score": self.score,
            "entity_id": self.entity_id,
            "entity_name": self.entity_name,
            "relation_type": self.relation_type,
            "entities": list(self.entities),
            "is_graph_evidence": self.is_graph_evidence,
            "metadata": dict(self.metadata or {}),
        }
        if self.domain == "recipe":
            payload.update({"recipe_id": self.entity_id, "recipe_name": self.entity_name})
        return payload


@dataclass
class AggregatedEvidence:
    entity_id: str
    entity_name: str
    full_document: str = ""
    documents: List[EvidenceDocument] = field(default_factory=list)
    matched_terms: List[str] = field(default_factory=list)
    graph_paths: List[Any] = field(default_factory=list)
    evidence_units: List[Dict[str, Any]] = field(default_factory=list)
    constraint_reasons: List[str] = field(default_factory=list)
    retrieval_sources: List[str] = field(default_factory=list)
    confidence: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "entity_id": self.entity_id,
            "entity_name": self.entity_name,
            "matched_terms": list(self.matched_terms),
            "graph_paths": list(self.graph_paths),
            "evidence_units": [dict(unit) for unit in self.evidence_units],
            "constraint_reasons": list(self.constraint_reasons),
            "retrieval_sources": list(self.retrieval_sources),
            "confidence": self.confidence,
            "documents": [doc.to_metadata() for doc in self.documents],
        }

    @property
    def recipe_id(self) -> str:
        return self.entity_id

    @property
    def recipe_name(self) -> str:
        return self.entity_name

    @property
    def full_recipe_doc(self) -> str:
        return self.full_document

    @full_recipe_doc.setter
    def full_recipe_doc(self, value: str) -> None:
        self.full_document = str(value or "")


RecipeEvidence = AggregatedEvidence

__all__ = ["AggregatedEvidence", "EvidenceUnit", "PageDocumentLike", "RecipeEvidence"]
