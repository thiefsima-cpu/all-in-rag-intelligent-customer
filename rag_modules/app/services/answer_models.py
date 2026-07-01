"""Contracts for the question-answer workflow."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional, Protocol

from ...contracts import EvidenceDocument
from ...runtime import (
    AnswerContext,
    GenerationSnapshot,
    GraphRetrievalSnapshot,
    QueryAnalysis,
    QueryDiagnostics,
    QueryTraceEvent,
    RetrievalOutcome,
    RouteResolution,
    RouteSnapshot,
    RuntimeErrorDetail,
)
from ...runtime.json_types import JsonObject

MessageCallback = Optional[Callable[[str], None]]
ChunkCallback = Optional[Callable[[str], None]]


@dataclass
class QuestionAnswerResult:
    answer: str
    analysis: Optional[QueryAnalysis]
    retrieval_outcome: RetrievalOutcome = field(default_factory=RetrievalOutcome)
    answer_context: AnswerContext = field(default_factory=AnswerContext)
    route_resolution: RouteResolution = field(default_factory=RouteResolution)
    latency_ms: float = 0.0
    route_trace: RouteSnapshot = field(default_factory=RouteSnapshot)
    graph_trace: GraphRetrievalSnapshot = field(default_factory=GraphRetrievalSnapshot)
    generation_trace: GenerationSnapshot = field(default_factory=GenerationSnapshot)
    trace_event: QueryTraceEvent = field(default_factory=QueryTraceEvent)

    @property
    def evidence_documents(self) -> list[EvidenceDocument]:
        return list(self.retrieval_outcome.evidence_documents or [])

    @property
    def strategy(self) -> str:
        if self.analysis is not None:
            return self.analysis.strategy_name
        return str(self.route_trace.strategy or self.retrieval_outcome.strategy or "")

    @property
    def doc_count(self) -> int:
        return len(self.evidence_documents)

    @property
    def error(self) -> RuntimeErrorDetail:
        return self.trace_event.error

    @property
    def status(self) -> str:
        if self.error:
            return "failed"
        if self.generation_trace.status:
            return self.generation_trace.status
        return "degraded" if self.generation_trace.fallback_used else "success"

    def to_response(self) -> "QuestionAnswerResponse":
        return QuestionAnswerResponse.from_result(self)

    def to_dict(self) -> JsonObject:
        return self.to_response().to_dict()


@dataclass
class QuestionAnswerSummary:
    answer: str
    status: str = "success"
    strategy: str = ""
    latency_ms: float = 0.0
    doc_count: int = 0
    has_evidence: bool = False
    fallback_used: bool = False
    failure_code: str = ""
    provider_latency_ms: float = 0.0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    estimated_cost_usd: float = 0.0
    token_usage_source: str = ""
    error: RuntimeErrorDetail = field(default_factory=RuntimeErrorDetail)

    def to_dict(self) -> JsonObject:
        return {
            "answer": self.answer,
            "status": self.status,
            "strategy": self.strategy,
            "latency_ms": self.latency_ms,
            "doc_count": self.doc_count,
            "has_evidence": self.has_evidence,
            "fallback_used": self.fallback_used,
            "failure_code": self.failure_code,
            "provider_latency_ms": self.provider_latency_ms,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "estimated_cost_usd": self.estimated_cost_usd,
            "token_usage_source": self.token_usage_source,
            "error": self.error.to_dict(),
        }


@dataclass
class QuestionAnswerGrounding:
    retrieval_outcome: RetrievalOutcome = field(default_factory=RetrievalOutcome)
    answer_context: AnswerContext = field(default_factory=AnswerContext)
    route_resolution: RouteResolution = field(default_factory=RouteResolution)
    evidence_documents: list[EvidenceDocument] = field(default_factory=list)

    def to_dict(self) -> JsonObject:
        return {
            "retrieval_outcome": self.retrieval_outcome.to_dict(),
            "answer_context": self.answer_context.to_dict(),
            "route_resolution": self.route_resolution.to_dict(),
            "evidence_documents": [item.to_dict() for item in self.evidence_documents],
        }


@dataclass
class QuestionAnswerDiagnostics:
    analysis: QueryAnalysis | None = None
    diagnostics: QueryDiagnostics = field(default_factory=QueryDiagnostics)

    def to_dict(self) -> JsonObject:
        return {
            "analysis": self.analysis.to_dict() if self.analysis else {},
            "diagnostics": self.diagnostics.to_dict(),
        }


@dataclass
class QuestionAnswerTraces:
    route_trace: RouteSnapshot = field(default_factory=RouteSnapshot)
    graph_trace: GraphRetrievalSnapshot = field(default_factory=GraphRetrievalSnapshot)
    generation_trace: GenerationSnapshot = field(default_factory=GenerationSnapshot)
    trace_event: QueryTraceEvent = field(default_factory=QueryTraceEvent)

    def to_dict(self) -> JsonObject:
        return {
            "route_trace": self.route_trace.to_dict(),
            "graph_trace": self.graph_trace.to_dict(),
            "generation_trace": self.generation_trace.to_dict(),
            "trace_event": self.trace_event.to_dict(),
        }


@dataclass
class QuestionAnswerResponse:
    summary: QuestionAnswerSummary = field(default_factory=lambda: QuestionAnswerSummary(answer=""))
    grounding: QuestionAnswerGrounding = field(default_factory=QuestionAnswerGrounding)
    diagnostics: QuestionAnswerDiagnostics = field(default_factory=QuestionAnswerDiagnostics)
    traces: QuestionAnswerTraces = field(default_factory=QuestionAnswerTraces)

    @classmethod
    def from_result(cls, result: QuestionAnswerResult) -> "QuestionAnswerResponse":
        return cls(
            summary=QuestionAnswerSummary(
                answer=result.answer,
                status=result.status,
                strategy=result.strategy,
                latency_ms=float(result.latency_ms or 0.0),
                doc_count=result.doc_count,
                has_evidence=bool(result.evidence_documents),
                fallback_used=bool(result.generation_trace.fallback_used),
                failure_code=str(result.generation_trace.failure_code or ""),
                provider_latency_ms=float(result.generation_trace.provider_latency_ms or 0.0),
                prompt_tokens=int(result.generation_trace.prompt_tokens or 0),
                completion_tokens=int(result.generation_trace.completion_tokens or 0),
                total_tokens=int(result.generation_trace.total_tokens or 0),
                estimated_cost_usd=float(result.generation_trace.estimated_cost_usd or 0.0),
                token_usage_source=str(result.generation_trace.token_usage_source or ""),
                error=result.error,
            ),
            grounding=QuestionAnswerGrounding(
                retrieval_outcome=result.retrieval_outcome,
                answer_context=result.answer_context,
                route_resolution=result.route_resolution,
                evidence_documents=result.evidence_documents,
            ),
            diagnostics=QuestionAnswerDiagnostics(
                analysis=result.analysis,
                diagnostics=result.trace_event.diagnostics,
            ),
            traces=QuestionAnswerTraces(
                route_trace=result.route_trace,
                graph_trace=result.graph_trace,
                generation_trace=result.generation_trace,
                trace_event=result.trace_event,
            ),
        )

    @property
    def answer(self) -> str:
        return self.summary.answer

    @property
    def strategy(self) -> str:
        return self.summary.strategy

    @property
    def status(self) -> str:
        return self.summary.status

    @property
    def latency_ms(self) -> float:
        return self.summary.latency_ms

    @property
    def doc_count(self) -> int:
        return self.summary.doc_count

    @property
    def has_evidence(self) -> bool:
        return self.summary.has_evidence

    @property
    def fallback_used(self) -> bool:
        return self.summary.fallback_used

    @property
    def failure_code(self) -> str:
        return self.summary.failure_code

    @property
    def error(self) -> RuntimeErrorDetail:
        return self.summary.error

    @property
    def analysis(self) -> QueryAnalysis | None:
        return self.diagnostics.analysis

    @property
    def diagnostic_payload(self) -> QueryDiagnostics:
        return self.diagnostics.diagnostics

    @property
    def retrieval_outcome(self) -> RetrievalOutcome:
        return self.grounding.retrieval_outcome

    @property
    def answer_context(self) -> AnswerContext:
        return self.grounding.answer_context

    @property
    def route_resolution(self) -> RouteResolution:
        return self.grounding.route_resolution

    @property
    def evidence_documents(self) -> list[EvidenceDocument]:
        return list(self.grounding.evidence_documents)

    @property
    def route_trace(self) -> RouteSnapshot:
        return self.traces.route_trace

    @property
    def graph_trace(self) -> GraphRetrievalSnapshot:
        return self.traces.graph_trace

    @property
    def generation_trace(self) -> GenerationSnapshot:
        return self.traces.generation_trace

    @property
    def trace_event(self) -> QueryTraceEvent:
        return self.traces.trace_event

    def to_dict(self) -> JsonObject:
        return {
            "summary": self.summary.to_dict(),
            "grounding": self.grounding.to_dict(),
            "diagnostics": self.diagnostics.to_dict(),
            "traces": self.traces.to_dict(),
        }


@dataclass
class AnswerPipelineState:
    question: str
    stream: bool = False
    explain_routing: bool = False
    message_callback: MessageCallback = None
    chunk_callback: ChunkCallback = None
    retrieval_outcome: RetrievalOutcome = field(default_factory=RetrievalOutcome)
    analysis: Optional[QueryAnalysis] = None
    answer_context: AnswerContext = field(default_factory=AnswerContext)
    route_resolution: RouteResolution = field(default_factory=RouteResolution)
    route_trace: RouteSnapshot = field(default_factory=RouteSnapshot)
    graph_trace: GraphRetrievalSnapshot = field(default_factory=GraphRetrievalSnapshot)
    generation_trace: GenerationSnapshot = field(default_factory=GenerationSnapshot)
    trace_event: QueryTraceEvent = field(default_factory=QueryTraceEvent)
    answer: str = ""

    def __post_init__(self) -> None:
        self.question = str(self.question or self.answer_context.question or "")
        if not self.answer_context.question:
            self.answer_context = AnswerContext(question=self.question)

    @property
    def evidence_documents(self) -> list[EvidenceDocument]:
        if self.answer_context.evidence_documents:
            return list(self.answer_context.evidence_documents)
        return list(self.retrieval_outcome.evidence_documents or [])

    @property
    def has_evidence(self) -> bool:
        return bool(self.evidence_documents)


@dataclass
class AnswerTraceBundle:
    route_trace: RouteSnapshot = field(default_factory=RouteSnapshot)
    graph_trace: GraphRetrievalSnapshot = field(default_factory=GraphRetrievalSnapshot)
    generation_trace: GenerationSnapshot = field(default_factory=GenerationSnapshot)
    trace_event: QueryTraceEvent = field(default_factory=QueryTraceEvent)


class QuestionAnswerer(Protocol):
    def answer_question(
        self,
        question: str,
        *,
        stream: bool = False,
        explain_routing: bool = False,
        message_callback: MessageCallback = None,
        chunk_callback: ChunkCallback = None,
    ) -> QuestionAnswerResult: ...

    def answer_question_response(
        self,
        question: str,
        *,
        stream: bool = False,
        explain_routing: bool = False,
        message_callback: MessageCallback = None,
        chunk_callback: ChunkCallback = None,
    ) -> "QuestionAnswerResponse": ...


__all__ = [
    "AnswerPipelineState",
    "AnswerTraceBundle",
    "ChunkCallback",
    "MessageCallback",
    "QuestionAnswerDiagnostics",
    "QuestionAnswerer",
    "QuestionAnswerGrounding",
    "QuestionAnswerResponse",
    "QuestionAnswerResult",
    "QuestionAnswerSummary",
    "QuestionAnswerTraces",
]
