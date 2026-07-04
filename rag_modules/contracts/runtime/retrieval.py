"""Retrieval outcome contracts."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any, Dict, List

from ...kernel.json_types import JsonObject, coerce_json_object
from .. import EvidenceDocument
from .errors import CANDIDATE_SOURCE_ERROR_CIRCUIT_OPEN
from .routing import RouteSnapshot


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
        candidates: Any,
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
            _candidate_error_code(item) == CANDIDATE_SOURCE_ERROR_CIRCUIT_OPEN
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


__all__ = ["HybridRetrievalOutcome", "RetrievalOutcome"]


def _mapping_or_none(value: object) -> Mapping[str, object] | None:
    return value if isinstance(value, Mapping) else None


def _candidate_error_code(candidate: Dict[str, Any]) -> str:
    error = candidate.get("error")
    if isinstance(error, dict):
        return str(error.get("code") or "").strip()
    return ""
