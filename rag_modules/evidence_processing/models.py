"""Evidence data models."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Protocol

from ..retrieval.contracts import EvidenceDocument


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
    recipe_id: str = ""
    recipe_name: str = ""
    relation_type: str = ""
    entities: List[str] = field(default_factory=list)
    is_graph_evidence: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "unit_id": self.unit_id,
            "evidence_type": self.evidence_type,
            "claim": self.claim,
            "source": self.source,
            "score": self.score,
            "recipe_id": self.recipe_id,
            "recipe_name": self.recipe_name,
            "relation_type": self.relation_type,
            "entities": list(self.entities),
            "is_graph_evidence": self.is_graph_evidence,
            "metadata": dict(self.metadata or {}),
        }


@dataclass
class RecipeEvidence:
    recipe_id: str
    recipe_name: str
    full_recipe_doc: str = ""
    documents: List[EvidenceDocument] = field(default_factory=list)
    matched_terms: List[str] = field(default_factory=list)
    graph_paths: List[Any] = field(default_factory=list)
    evidence_units: List[Dict[str, Any]] = field(default_factory=list)
    constraint_reasons: List[str] = field(default_factory=list)
    retrieval_sources: List[str] = field(default_factory=list)
    confidence: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "recipe_id": self.recipe_id,
            "recipe_name": self.recipe_name,
            "matched_terms": list(self.matched_terms),
            "graph_paths": list(self.graph_paths),
            "evidence_units": [dict(unit) for unit in self.evidence_units],
            "constraint_reasons": list(self.constraint_reasons),
            "retrieval_sources": list(self.retrieval_sources),
            "confidence": self.confidence,
            "documents": [doc.to_metadata() for doc in self.documents],
        }


__all__ = ["EvidenceUnit", "PageDocumentLike", "RecipeEvidence"]
