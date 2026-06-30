"""Trace event contracts."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

from .generation_models import GenerationSnapshot
from .graph_models import GraphRetrievalSnapshot
from .json_types import JsonObject, coerce_json_float, coerce_json_int, coerce_json_object
from .policy_models import PolicySnapshot
from .route_models import RouteSnapshot


@dataclass
class QueryDiagnostics:
    retrieval_bucket: str = ""
    generation_bucket: str = ""
    overall_bucket: str = ""
    retrieval_degraded: bool = False
    degraded_sources: list[str] = field(default_factory=list)
    degraded_candidates: list[JsonObject] = field(default_factory=list)
    circuit_breaker_triggered: bool = False
    answer_impacted: bool = False
    failure_reasons: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: Mapping[str, object] | None) -> "QueryDiagnostics":
        payload = dict(data or {})
        raw_candidates = payload.get("degraded_candidates")
        return cls(
            retrieval_bucket=str(payload.get("retrieval_bucket") or ""),
            generation_bucket=str(payload.get("generation_bucket") or ""),
            overall_bucket=str(payload.get("overall_bucket") or ""),
            retrieval_degraded=bool(payload.get("retrieval_degraded", False)),
            degraded_sources=_string_list(payload.get("degraded_sources")),
            degraded_candidates=(
                [coerce_json_object(item) for item in raw_candidates]
                if isinstance(raw_candidates, list)
                else []
            ),
            circuit_breaker_triggered=bool(payload.get("circuit_breaker_triggered", False)),
            answer_impacted=bool(payload.get("answer_impacted", False)),
            failure_reasons=_string_list(payload.get("failure_reasons")),
        )

    def to_dict(self) -> JsonObject:
        return {
            "retrieval_bucket": self.retrieval_bucket,
            "generation_bucket": self.generation_bucket,
            "overall_bucket": self.overall_bucket,
            "retrieval_degraded": bool(self.retrieval_degraded),
            "degraded_sources": [
                str(item).strip() for item in (self.degraded_sources or []) if str(item).strip()
            ],
            "degraded_candidates": [
                dict(item) for item in (self.degraded_candidates or []) if isinstance(item, dict)
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
    def from_dict(cls, data: Mapping[str, object] | None) -> "ModelSuiteSnapshot":
        payload = dict(data or {})
        return cls(
            llm=str(payload.get("llm") or ""),
            embedding=str(payload.get("embedding") or ""),
            rerank=str(payload.get("rerank") or ""),
        )

    def to_dict(self) -> JsonObject:
        return {
            "llm": self.llm,
            "embedding": self.embedding,
            "rerank": self.rerank,
        }


@dataclass
class RetrievalTraceSnapshot:
    doc_count: int = 0
    evidence: list[JsonObject] = field(default_factory=list)
    route_trace: RouteSnapshot = field(default_factory=RouteSnapshot)
    graph_trace: GraphRetrievalSnapshot | None = None
    failure_reasons: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.doc_count = max(0, int(self.doc_count or 0))
        self.evidence = [
            coerce_json_object(item) for item in (self.evidence or []) if isinstance(item, Mapping)
        ]
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
    def from_dict(cls, data: Mapping[str, object] | None) -> "RetrievalTraceSnapshot":
        payload = dict(data or {})
        graph_trace_payload = payload.get("graph_trace")
        raw_evidence = payload.get("evidence")
        return cls(
            doc_count=coerce_json_int(payload.get("doc_count")),
            evidence=(
                [coerce_json_object(item) for item in raw_evidence]
                if isinstance(raw_evidence, list)
                else []
            ),
            route_trace=RouteSnapshot.from_dict(_mapping_or_none(payload.get("route_trace"))),
            graph_trace=(
                GraphRetrievalSnapshot.from_dict(graph_trace_payload)
                if isinstance(graph_trace_payload, Mapping)
                else None
            ),
            failure_reasons=_string_list(payload.get("failure_reasons")),
        )

    def to_dict(self) -> JsonObject:
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
    def from_dict(cls, data: Mapping[str, object] | None) -> "AnswerTraceSnapshot":
        payload = dict(data or {})
        return cls(
            chars=coerce_json_int(payload.get("chars")),
            preview=str(payload.get("preview") or ""),
        )

    def to_dict(self) -> JsonObject:
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
    policy: PolicySnapshot = field(default_factory=PolicySnapshot)
    plan: JsonObject = field(default_factory=dict)
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
        if isinstance(self.policy, dict):
            self.policy = PolicySnapshot.from_dict(self.policy)
        elif not isinstance(self.policy, PolicySnapshot):
            self.policy = PolicySnapshot()
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
        self.plan = coerce_json_object(self.plan)
        self.error = str(self.error or "")

    @classmethod
    def from_dict(cls, data: Mapping[str, object] | None) -> "QueryTraceEvent":
        payload = dict(data or {})
        return cls(
            query_id=str(payload.get("query_id") or ""),
            timestamp=coerce_json_int(payload.get("timestamp")),
            query=str(payload.get("query") or ""),
            strategy=(str(payload["strategy"]) if payload.get("strategy") is not None else None),
            latency_ms=coerce_json_float(payload.get("latency_ms")),
            policy=PolicySnapshot.from_dict(_mapping_or_none(payload.get("policy"))),
            plan=coerce_json_object(payload.get("plan")),
            models=ModelSuiteSnapshot.from_dict(_mapping_or_none(payload.get("models"))),
            retrieval=RetrievalTraceSnapshot.from_dict(_mapping_or_none(payload.get("retrieval"))),
            generation=GenerationSnapshot.from_dict(_mapping_or_none(payload.get("generation"))),
            diagnostics=QueryDiagnostics.from_dict(_mapping_or_none(payload.get("diagnostics"))),
            answer=AnswerTraceSnapshot.from_dict(_mapping_or_none(payload.get("answer"))),
            error=str(payload.get("error") or ""),
        )

    def to_dict(self) -> JsonObject:
        return {
            "query_id": self.query_id,
            "timestamp": self.timestamp,
            "query": self.query,
            "strategy": self.strategy,
            "latency_ms": self.latency_ms,
            "policy": self.policy.to_dict(),
            "plan": dict(self.plan or {}),
            "models": self.models.to_dict(),
            "retrieval": self.retrieval.to_dict(),
            "generation": self.generation.to_dict(),
            "diagnostics": self.diagnostics.to_dict(),
            "answer": self.answer.to_dict(),
            "error": self.error,
        }


def _mapping_or_none(value: object) -> Mapping[str, object] | None:
    return value if isinstance(value, Mapping) else None


def _list_or_empty(value: object) -> list[object]:
    return list(value) if isinstance(value, list) else []


def _string_list(value: object) -> list[str]:
    return [str(item).strip() for item in _list_or_empty(value) if str(item).strip()]
