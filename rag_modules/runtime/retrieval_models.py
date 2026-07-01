"""Retrieval outcome contracts."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field

from ..contracts import EvidenceDocument
from .json_types import JsonObject, coerce_json_object
from .route_models import RouteSnapshot


def _coerce_evidence_documents(
    evidence_documents: Iterable[EvidenceDocument] | None,
) -> list[EvidenceDocument]:
    if evidence_documents:
        return [
            doc
            if isinstance(doc, EvidenceDocument)
            else EvidenceDocument.from_dict(coerce_json_object(doc))
            for doc in evidence_documents
        ]
    return []


@dataclass
class RetrievalOutcome:
    query: str = ""
    strategy: str = ""
    evidence_documents: list[EvidenceDocument] = field(default_factory=list)
    route_trace: RouteSnapshot = field(default_factory=RouteSnapshot)
    degradation_summary: JsonObject = field(default_factory=dict)
    metadata: JsonObject = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.evidence_documents = _coerce_evidence_documents(self.evidence_documents)
        if isinstance(self.route_trace, dict):
            self.route_trace = RouteSnapshot.from_dict(self.route_trace)
        elif not isinstance(self.route_trace, RouteSnapshot):
            self.route_trace = RouteSnapshot()
        if self.degradation_summary:
            self.degradation_summary = _normalize_degradation_summary(self.degradation_summary)
        else:
            self.degradation_summary = _route_degradation_summary(self.route_trace)
        self.metadata = coerce_json_object(self.metadata)

    @classmethod
    def from_dict(cls, data: Mapping[str, object] | None) -> "RetrievalOutcome":
        payload = dict(data or {})
        raw_evidence = payload.get("evidence_documents")
        evidence_payloads = raw_evidence if isinstance(raw_evidence, list) else []
        return cls(
            query=str(payload.get("query") or ""),
            strategy=str(payload.get("strategy") or ""),
            evidence_documents=[
                item
                if isinstance(item, EvidenceDocument)
                else EvidenceDocument.from_dict(coerce_json_object(item))
                for item in evidence_payloads
            ],
            route_trace=RouteSnapshot.from_dict(_mapping_or_none(payload.get("route_trace"))),
            degradation_summary=coerce_json_object(payload.get("degradation_summary")),
            metadata=coerce_json_object(payload.get("metadata")),
        )

    @property
    def doc_count(self) -> int:
        return len(self.evidence_documents)

    def to_dict(self) -> JsonObject:
        return {
            "query": self.query,
            "strategy": self.strategy,
            "doc_count": self.doc_count,
            "evidence_documents": [doc.to_dict() for doc in self.evidence_documents],
            "route_trace": self.route_trace.to_dict(),
            "degradation_summary": dict(self.degradation_summary or {}),
            "metadata": dict(self.metadata or {}),
        }


def _route_degradation_summary(route_trace: RouteSnapshot) -> JsonObject:
    diagnostics = route_trace.diagnostics
    return {
        "retrieval_degraded": diagnostics.retrieval_degraded,
        "degraded_sources": list(diagnostics.degraded_sources or []),
        "degraded_candidates": [dict(item) for item in diagnostics.degraded_candidates],
        "circuit_breaker_triggered": diagnostics.circuit_breaker_triggered,
        "answer_impacted": diagnostics.answer_impacted,
    }


def _normalize_degradation_summary(summary: JsonObject) -> JsonObject:
    payload = coerce_json_object(summary)
    raw_sources = payload.get("degraded_sources")
    raw_candidates = payload.get("degraded_candidates")
    return {
        "retrieval_degraded": bool(payload.get("retrieval_degraded", False)),
        "degraded_sources": [
            str(item).strip()
            for item in (raw_sources if isinstance(raw_sources, list) else [])
            if str(item).strip()
        ],
        "degraded_candidates": [
            coerce_json_object(item)
            for item in (raw_candidates if isinstance(raw_candidates, list) else [])
        ],
        "circuit_breaker_triggered": bool(payload.get("circuit_breaker_triggered", False)),
        "answer_impacted": bool(payload.get("answer_impacted", False)),
    }


__all__ = ["RetrievalOutcome"]


def _mapping_or_none(value: object) -> Mapping[str, object] | None:
    return value if isinstance(value, Mapping) else None
