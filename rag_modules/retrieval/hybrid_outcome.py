"""Hybrid retrieval result contract."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List

from ..contracts import EvidenceDocument
from .candidate_generator import CANDIDATE_SOURCE_ERROR_CIRCUIT_OPEN, CandidateSet


def _unique_strings(values: List[Any]) -> List[str]:
    normalized: List[str] = []
    for value in values or []:
        text = str(value or "").strip()
        if text and text not in normalized:
            normalized.append(text)
    return normalized


@dataclass
class HybridRetrievalOutcome:
    """Documents plus source-level observability emitted by hybrid retrieval."""

    documents: List[EvidenceDocument] = field(default_factory=list)
    candidate_counts: Dict[str, int] = field(default_factory=dict)
    degraded_candidates: List[Dict[str, Any]] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.documents = [
            doc if isinstance(doc, EvidenceDocument) else EvidenceDocument.from_dict(doc)
            for doc in (self.documents or [])
        ]
        self.candidate_counts = {
            str(key): max(0, int(value or 0))
            for key, value in dict(self.candidate_counts or {}).items()
        }
        self.degraded_candidates = [
            dict(item) for item in (self.degraded_candidates or []) if isinstance(item, dict)
        ]
        self.metadata = dict(self.metadata or {})

    @classmethod
    def from_candidate_set(
        cls,
        *,
        documents: List[EvidenceDocument],
        candidates: CandidateSet,
        metadata: Dict[str, Any] | None = None,
    ) -> "HybridRetrievalOutcome":
        return cls(
            documents=list(documents or []),
            candidate_counts=dict(candidates.stats or {}),
            degraded_candidates=candidates.degraded_details,
            metadata=dict(metadata or {}),
        )

    @classmethod
    def from_dict(cls, data: Dict[str, Any] | None) -> "HybridRetrievalOutcome":
        payload = dict(data or {})
        return cls(
            documents=payload.get("documents") or [],
            candidate_counts=payload.get("candidate_counts") or {},
            degraded_candidates=payload.get("degraded_candidates") or [],
            metadata=payload.get("metadata") or {},
        )

    @property
    def degraded_sources(self) -> List[str]:
        return _unique_strings([item.get("source") for item in self.degraded_candidates])

    @property
    def retrieval_degraded(self) -> bool:
        return bool(self.degraded_candidates)

    @property
    def circuit_breaker_triggered(self) -> bool:
        return any(
            item.get("error_code") == CANDIDATE_SOURCE_ERROR_CIRCUIT_OPEN
            or item.get("reason") == "circuit_open"
            or item.get("circuit_state") == "open"
            for item in self.degraded_candidates
        )

    @property
    def answer_impacted(self) -> bool:
        return self.retrieval_degraded and not self.documents

    def to_stage_details(self) -> Dict[str, Any]:
        return {
            "candidate_counts": dict(self.candidate_counts or {}),
            "degraded_sources": self.degraded_sources,
            "degraded_candidates": [dict(item) for item in self.degraded_candidates],
            "retrieval_degraded": self.retrieval_degraded,
            "circuit_breaker_triggered": self.circuit_breaker_triggered,
            "answer_impacted": self.answer_impacted,
        }

    def to_dict(self) -> Dict[str, Any]:
        return {
            "documents": [doc.to_dict() for doc in self.documents],
            **self.to_stage_details(),
            "metadata": dict(self.metadata or {}),
        }


__all__ = ["HybridRetrievalOutcome"]
