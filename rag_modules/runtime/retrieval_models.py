"""Retrieval outcome contracts."""

from __future__ import annotations

from dataclasses import InitVar, dataclass, field
from typing import Any, Dict, Iterable, List

from langchain_core.documents import Document

from ..retrieval.contracts import (
    EvidenceDocument,
    ensure_evidence_documents,
    to_langchain_documents,
)
from .route_models import RouteSnapshot


def _coerce_evidence_documents(
    evidence_documents: Iterable[EvidenceDocument] | None,
    legacy_documents: Iterable[Document] | None = None,
) -> List[EvidenceDocument]:
    if evidence_documents:
        return [doc for doc in evidence_documents]
    if legacy_documents:
        return ensure_evidence_documents(legacy_documents)
    return []


@dataclass
class RetrievalOutcome:
    query: str = ""
    strategy: str = ""
    evidence_documents: List[EvidenceDocument] = field(default_factory=list)
    route_trace: RouteSnapshot = field(default_factory=RouteSnapshot)
    degradation_summary: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)
    documents_input: InitVar[Iterable[Document] | None] = None

    def __post_init__(self, documents_input: Iterable[Document] | None) -> None:
        self.evidence_documents = _coerce_evidence_documents(
            self.evidence_documents,
            documents_input,
        )
        if isinstance(self.route_trace, dict):
            self.route_trace = RouteSnapshot.from_dict(self.route_trace)
        elif not isinstance(self.route_trace, RouteSnapshot):
            self.route_trace = RouteSnapshot()
        if self.degradation_summary:
            self.degradation_summary = _normalize_degradation_summary(self.degradation_summary)
        else:
            self.degradation_summary = _route_degradation_summary(self.route_trace)
        self.metadata = dict(self.metadata or {})

    @classmethod
    def from_dict(cls, data: Dict[str, Any] | None) -> "RetrievalOutcome":
        payload = dict(data or {})
        raw_evidence = payload.get("evidence_documents") or []
        return cls(
            query=str(payload.get("query") or ""),
            strategy=str(payload.get("strategy") or ""),
            evidence_documents=[
                item
                if isinstance(item, EvidenceDocument)
                else EvidenceDocument.from_dict(item)
                for item in raw_evidence
            ],
            route_trace=payload.get("route_trace") or {},
            degradation_summary=payload.get("degradation_summary") or {},
            metadata=payload.get("metadata") or {},
            documents_input=payload.get("documents") or [],
        )

    @property
    def documents(self) -> List[Document]:
        return to_langchain_documents(self.evidence_documents)

    @property
    def doc_count(self) -> int:
        return len(self.evidence_documents)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "query": self.query,
            "strategy": self.strategy,
            "doc_count": self.doc_count,
            "evidence_documents": [doc.to_dict() for doc in self.evidence_documents],
            "route_trace": self.route_trace.to_dict(),
            "degradation_summary": dict(self.degradation_summary or {}),
            "metadata": dict(self.metadata or {}),
        }


def _route_degradation_summary(route_trace: RouteSnapshot) -> Dict[str, Any]:
    diagnostics = route_trace.diagnostics
    return {
        "retrieval_degraded": diagnostics.retrieval_degraded,
        "degraded_sources": list(diagnostics.degraded_sources or []),
        "degraded_candidates": [dict(item) for item in diagnostics.degraded_candidates],
        "circuit_breaker_triggered": diagnostics.circuit_breaker_triggered,
        "answer_impacted": diagnostics.answer_impacted,
    }


def _normalize_degradation_summary(summary: Dict[str, Any]) -> Dict[str, Any]:
    payload = dict(summary or {})
    return {
        "retrieval_degraded": bool(payload.get("retrieval_degraded", False)),
        "degraded_sources": [
            str(item).strip()
            for item in (payload.get("degraded_sources") or [])
            if str(item).strip()
        ],
        "degraded_candidates": [
            dict(item)
            for item in (payload.get("degraded_candidates") or [])
            if isinstance(item, dict)
        ],
        "circuit_breaker_triggered": bool(payload.get("circuit_breaker_triggered", False)),
        "answer_impacted": bool(payload.get("answer_impacted", False)),
    }

__all__ = ["RetrievalOutcome"]
