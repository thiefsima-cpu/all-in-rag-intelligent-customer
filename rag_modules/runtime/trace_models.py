"""Trace event contracts."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .generation_models import GenerationSnapshot
from .graph_models import GraphRetrievalSnapshot
from .route_models import RouteSnapshot


@dataclass
class QueryDiagnostics:
    retrieval_bucket: str = ""
    generation_bucket: str = ""
    overall_bucket: str = ""
    retrieval_degraded: bool = False
    degraded_sources: List[str] = field(default_factory=list)
    degraded_candidates: List[Dict[str, Any]] = field(default_factory=list)
    circuit_breaker_triggered: bool = False
    answer_impacted: bool = False
    failure_reasons: List[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: Dict[str, Any] | None) -> "QueryDiagnostics":
        payload = dict(data or {})
        return cls(
            retrieval_bucket=payload.get("retrieval_bucket", ""),
            generation_bucket=payload.get("generation_bucket", ""),
            overall_bucket=payload.get("overall_bucket", ""),
            retrieval_degraded=payload.get("retrieval_degraded", False),
            degraded_sources=payload.get("degraded_sources") or [],
            degraded_candidates=payload.get("degraded_candidates") or [],
            circuit_breaker_triggered=payload.get("circuit_breaker_triggered", False),
            answer_impacted=payload.get("answer_impacted", False),
            failure_reasons=payload.get("failure_reasons") or [],
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "retrieval_bucket": self.retrieval_bucket,
            "generation_bucket": self.generation_bucket,
            "overall_bucket": self.overall_bucket,
            "retrieval_degraded": bool(self.retrieval_degraded),
            "degraded_sources": [
                str(item).strip()
                for item in (self.degraded_sources or [])
                if str(item).strip()
            ],
            "degraded_candidates": [
                dict(item)
                for item in (self.degraded_candidates or [])
                if isinstance(item, dict)
            ],
            "circuit_breaker_triggered": bool(self.circuit_breaker_triggered),
            "answer_impacted": bool(self.answer_impacted),
            "failure_reasons": list(self.failure_reasons or []),
        }


@dataclass
class ModelSuiteSnapshot:
    llm: str = ""
    embedding: str = ""
    rerank: str = ""

    @classmethod
    def from_dict(cls, data: Dict[str, Any] | None) -> "ModelSuiteSnapshot":
        payload = dict(data or {})
        return cls(
            llm=str(payload.get("llm") or ""),
            embedding=str(payload.get("embedding") or ""),
            rerank=str(payload.get("rerank") or ""),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "llm": self.llm,
            "embedding": self.embedding,
            "rerank": self.rerank,
        }


@dataclass
class RetrievalTraceSnapshot:
    doc_count: int = 0
    evidence: List[Dict[str, Any]] = field(default_factory=list)
    route_trace: RouteSnapshot = field(default_factory=RouteSnapshot)
    graph_trace: Optional[GraphRetrievalSnapshot] = None
    failure_reasons: List[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.doc_count = max(0, int(self.doc_count or 0))
        self.evidence = [dict(item) for item in (self.evidence or []) if isinstance(item, dict)]
        if isinstance(self.route_trace, dict):
            self.route_trace = RouteSnapshot.from_dict(self.route_trace)
        elif not isinstance(self.route_trace, RouteSnapshot):
            self.route_trace = RouteSnapshot()
        if isinstance(self.graph_trace, dict):
            self.graph_trace = GraphRetrievalSnapshot.from_dict(self.graph_trace)
        elif self.graph_trace and not isinstance(self.graph_trace, GraphRetrievalSnapshot):
            self.graph_trace = GraphRetrievalSnapshot.from_dict(dict(self.graph_trace))
        self.failure_reasons = [
            str(item).strip() for item in (self.failure_reasons or []) if str(item).strip()
        ]

    @classmethod
    def from_dict(cls, data: Dict[str, Any] | None) -> "RetrievalTraceSnapshot":
        payload = dict(data or {})
        return cls(
            doc_count=payload.get("doc_count", 0),
            evidence=payload.get("evidence") or [],
            route_trace=payload.get("route_trace") or {},
            graph_trace=payload.get("graph_trace") or {},
            failure_reasons=payload.get("failure_reasons") or [],
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "doc_count": self.doc_count,
            "evidence": [dict(item) for item in self.evidence],
            "route_trace": self.route_trace.to_dict(),
            "graph_trace": self.graph_trace.to_dict() if self.graph_trace else {},
            "failure_reasons": list(self.failure_reasons or []),
        }


@dataclass
class AnswerTraceSnapshot:
    chars: int = 0
    preview: str = ""

    def __post_init__(self) -> None:
        self.chars = max(0, int(self.chars or 0))
        self.preview = str(self.preview or "")

    @classmethod
    def from_dict(cls, data: Dict[str, Any] | None) -> "AnswerTraceSnapshot":
        payload = dict(data or {})
        return cls(
            chars=payload.get("chars", 0),
            preview=payload.get("preview", ""),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "chars": self.chars,
            "preview": self.preview,
        }


@dataclass
class QueryTraceEvent:
    query_id: str = ""
    timestamp: int = 0
    query: str = ""
    strategy: str | None = None
    latency_ms: float = 0.0
    plan: Dict[str, Any] = field(default_factory=dict)
    models: ModelSuiteSnapshot = field(default_factory=ModelSuiteSnapshot)
    retrieval: RetrievalTraceSnapshot = field(default_factory=RetrievalTraceSnapshot)
    generation: GenerationSnapshot = field(default_factory=GenerationSnapshot)
    diagnostics: QueryDiagnostics = field(default_factory=QueryDiagnostics)
    answer: AnswerTraceSnapshot = field(default_factory=AnswerTraceSnapshot)
    error: str = ""

    def __post_init__(self) -> None:
        if isinstance(self.models, dict):
            self.models = ModelSuiteSnapshot.from_dict(self.models)
        elif not isinstance(self.models, ModelSuiteSnapshot):
            self.models = ModelSuiteSnapshot()
        if isinstance(self.retrieval, dict):
            self.retrieval = RetrievalTraceSnapshot.from_dict(self.retrieval)
        elif not isinstance(self.retrieval, RetrievalTraceSnapshot):
            self.retrieval = RetrievalTraceSnapshot()
        if isinstance(self.generation, dict):
            self.generation = GenerationSnapshot.from_dict(self.generation)
        elif not isinstance(self.generation, GenerationSnapshot):
            self.generation = GenerationSnapshot()
        if isinstance(self.diagnostics, dict):
            self.diagnostics = QueryDiagnostics.from_dict(self.diagnostics)
        elif not isinstance(self.diagnostics, QueryDiagnostics):
            self.diagnostics = QueryDiagnostics()
        if isinstance(self.answer, dict):
            self.answer = AnswerTraceSnapshot.from_dict(self.answer)
        elif not isinstance(self.answer, AnswerTraceSnapshot):
            self.answer = AnswerTraceSnapshot()
        self.plan = dict(self.plan or {})
        self.error = str(self.error or "")

    @classmethod
    def from_dict(cls, data: Dict[str, Any] | None) -> "QueryTraceEvent":
        payload = dict(data or {})
        payload["models"] = ModelSuiteSnapshot.from_dict(payload.get("models"))
        payload["retrieval"] = RetrievalTraceSnapshot.from_dict(payload.get("retrieval"))
        payload["generation"] = GenerationSnapshot.from_dict(payload.get("generation"))
        payload["diagnostics"] = QueryDiagnostics.from_dict(payload.get("diagnostics"))
        payload["answer"] = AnswerTraceSnapshot.from_dict(payload.get("answer"))
        allowed = {field.name for field in cls.__dataclass_fields__.values()}
        return cls(**{key: payload[key] for key in allowed if key in payload})

    def to_dict(self) -> Dict[str, Any]:
        return {
            "query_id": self.query_id,
            "timestamp": self.timestamp,
            "query": self.query,
            "strategy": self.strategy,
            "latency_ms": self.latency_ms,
            "plan": dict(self.plan or {}),
            "models": self.models.to_dict(),
            "retrieval": self.retrieval.to_dict(),
            "generation": self.generation.to_dict(),
            "diagnostics": self.diagnostics.to_dict(),
            "answer": self.answer.to_dict(),
            "error": self.error,
        }
