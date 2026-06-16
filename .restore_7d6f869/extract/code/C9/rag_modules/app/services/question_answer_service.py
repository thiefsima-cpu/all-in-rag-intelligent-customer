"""Question answering service."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Callable, List, Optional

from langchain_core.documents import Document

from ...retrieval.retrieval_contracts import EvidenceDocument, ensure_evidence_documents
from ...runtime_models import (
    AnswerContext,
    GenerationSnapshot,
    GraphRetrievalSnapshot,
    QueryAnalysis,
    QueryTraceEvent,
    RetrievalOutcome,
    RouteSnapshot,
    analysis_payload,
)

logger = logging.getLogger(__name__)

MessageCallback = Optional[Callable[[str], None]]
ChunkCallback = Optional[Callable[[str], None]]


@dataclass
class QuestionAnswerResult:
    answer: str
    analysis: Optional[QueryAnalysis]
    retrieval_outcome: RetrievalOutcome = field(default_factory=RetrievalOutcome)
    documents: List[Document] = field(default_factory=list)
    evidence_documents: List[EvidenceDocument] = field(default_factory=list)
    latency_ms: float = 0.0
    route_trace: RouteSnapshot = field(default_factory=RouteSnapshot)
    graph_trace: GraphRetrievalSnapshot = field(default_factory=GraphRetrievalSnapshot)
    generation_trace: GenerationSnapshot = field(default_factory=GenerationSnapshot)
    trace_event: QueryTraceEvent = field(default_factory=QueryTraceEvent)

    def to_dict(self) -> dict:
        return {
            "answer": self.answer,
            "analysis": analysis_payload(self.analysis),
            "retrieval_outcome": self.retrieval_outcome.to_dict(),
            "documents": self.documents,
            "evidence_documents": [doc.to_dict() for doc in self.evidence_documents],
            "latency_ms": self.latency_ms,
            "route_trace": self.route_trace.to_dict(),
            "graph_trace": self.graph_trace.to_dict(),
            "generation_trace": self.generation_trace.to_dict(),
            "trace_event": self.trace_event.to_dict(),
        }


class QuestionAnswerService:
    """Run routing, retrieval, answer generation, and trace recording."""

    def __init__(self, config, query_router, generation_module, query_tracer):
        self.config = config
        self.query_router = query_router
        self.generation_module = generation_module
        self.query_tracer = query_tracer

    def answer_question(
        self,
        question: str,
        stream: bool = False,
        explain_routing: bool = False,
        message_callback: MessageCallback = None,
        chunk_callback: ChunkCallback = None,
    ) -> QuestionAnswerResult:
        start_time = time.perf_counter()
        retrieval_outcome = RetrievalOutcome()
        documents: List[Document] = []
        evidence_documents: List[EvidenceDocument] = []
        analysis: Optional[QueryAnalysis] = None

        try:
            self._emit(message_callback, f"\nUser question: {question}")
            if explain_routing:
                self._emit(message_callback, self.query_router.explain_routing_decision(question))

            self._emit(message_callback, "Running query routing...")
            retrieval_outcome, analysis = self.query_router.route_query(question, self.config.top_k)
            documents = retrieval_outcome.documents
            evidence_documents = retrieval_outcome.evidence_documents or ensure_evidence_documents(documents)
            if analysis:
                self._emit(message_callback, self._format_strategy_summary(analysis))

            route_trace = self._route_snapshot()
            graph_trace = self._graph_snapshot(route_trace, question)
            generation_trace = self._generation_snapshot()

            if documents:
                self._emit(message_callback, self._format_document_summary(documents))
            else:
                answer = "Sorry, I could not find enough relevant retrieval evidence to answer that question."
                latency_ms = (time.perf_counter() - start_time) * 1000
                trace_event = self.query_tracer.record(
                    query=question,
                    analysis=analysis,
                    documents=retrieval_outcome,
                    latency_ms=latency_ms,
                    answer=answer,
                    route_trace=route_trace,
                    graph_trace=graph_trace,
                    generation_trace=generation_trace,
                )
                return QuestionAnswerResult(
                    answer=answer,
                    analysis=analysis,
                    retrieval_outcome=retrieval_outcome,
                    documents=documents,
                    evidence_documents=evidence_documents,
                    latency_ms=latency_ms,
                    route_trace=route_trace,
                    graph_trace=graph_trace,
                    generation_trace=generation_trace,
                    trace_event=trace_event,
                )

            self._emit(message_callback, "Generating answer...")
            answer_context = self._build_answer_context(
                question=question,
                retrieval_outcome=retrieval_outcome,
                analysis=analysis,
            )
            answer = self._generate_answer(
                answer_context=answer_context,
                stream=stream,
                chunk_callback=chunk_callback,
                message_callback=message_callback,
            )
            latency_ms = (time.perf_counter() - start_time) * 1000
            self._emit(message_callback, f"\nAnswer complete in {latency_ms / 1000:.2f}s")
            route_trace = self._route_snapshot()
            graph_trace = self._graph_snapshot(route_trace, question)
            generation_trace = self._generation_snapshot()
            trace_event = self.query_tracer.record(
                query=question,
                analysis=analysis,
                documents=answer_context,
                latency_ms=latency_ms,
                answer=answer,
                route_trace=route_trace,
                graph_trace=graph_trace,
                generation_trace=generation_trace,
            )
            return QuestionAnswerResult(
                answer=answer,
                analysis=analysis,
                retrieval_outcome=retrieval_outcome,
                documents=documents,
                evidence_documents=evidence_documents,
                latency_ms=latency_ms,
                route_trace=route_trace,
                graph_trace=graph_trace,
                generation_trace=generation_trace,
                trace_event=trace_event,
            )
        except Exception as exc:
            logger.error("Question answering failed: %s", exc)
            latency_ms = (time.perf_counter() - start_time) * 1000
            route_trace = self._route_snapshot()
            graph_trace = self._graph_snapshot(route_trace, question)
            generation_trace = self._generation_snapshot()
            trace_event = self.query_tracer.record(
                query=question,
                analysis=analysis,
                documents=retrieval_outcome,
                latency_ms=latency_ms,
                error=str(exc),
                route_trace=route_trace,
                graph_trace=graph_trace,
                generation_trace=generation_trace,
            )
            return QuestionAnswerResult(
                answer=f"Sorry, an error occurred while processing the question: {exc}",
                analysis=None,
                retrieval_outcome=retrieval_outcome,
                documents=documents,
                evidence_documents=evidence_documents,
                latency_ms=latency_ms,
                route_trace=route_trace,
                graph_trace=graph_trace,
                generation_trace=generation_trace,
                trace_event=trace_event,
            )

    def _generate_answer(
        self,
        answer_context: AnswerContext,
        stream: bool,
        chunk_callback: ChunkCallback,
        message_callback: MessageCallback,
    ) -> str:
        if not stream:
            return self.generation_module.generate_answer_from_context(answer_context)

        streamed_chunks: List[str] = []
        try:
            for chunk_text in self.generation_module.generate_answer_stream_from_context(answer_context):
                streamed_chunks.append(chunk_text)
                if chunk_callback:
                    chunk_callback(chunk_text)
            if chunk_callback:
                chunk_callback("\n")
            streamed_answer = "".join(streamed_chunks).strip()
            return streamed_answer or "Streaming output completed"
        except Exception as exc:
            logger.error("Streaming output failed: %s", exc)
            self._emit(message_callback, "\n[WARN] Streaming output interrupted. Falling back to standard mode...")
            return self.generation_module.generate_answer_from_context(answer_context)

    @staticmethod
    def _build_answer_context(
        *,
        question: str,
        retrieval_outcome: RetrievalOutcome,
        analysis: Optional[QueryAnalysis],
    ) -> AnswerContext:
        return AnswerContext(
            question=question,
            retrieval=retrieval_outcome,
            analysis=analysis,
        )

    def _route_snapshot(self) -> RouteSnapshot:
        route_trace = getattr(self.query_router, "last_trace", RouteSnapshot())
        if isinstance(route_trace, RouteSnapshot):
            return RouteSnapshot.from_dict(route_trace.to_dict())
        return RouteSnapshot.from_dict(route_trace)

    def _generation_snapshot(self) -> GenerationSnapshot:
        generation_trace = getattr(self.generation_module, "last_trace", GenerationSnapshot())
        if isinstance(generation_trace, GenerationSnapshot):
            return GenerationSnapshot.from_dict(generation_trace.to_dict())
        return GenerationSnapshot.from_dict(generation_trace)

    def _graph_snapshot(
        self,
        route_trace: RouteSnapshot,
        question: str,
    ) -> GraphRetrievalSnapshot:
        stage_names = {str(name) for name in getattr(route_trace, "stages", {}).keys()}
        if not any("graph" in name for name in stage_names):
            return GraphRetrievalSnapshot()
        graph_retrieval = getattr(self.query_router, "graph_rag_retrieval", None)
        graph_trace = getattr(graph_retrieval, "last_trace", GraphRetrievalSnapshot())
        if isinstance(graph_trace, GraphRetrievalSnapshot):
            snapshot = GraphRetrievalSnapshot.from_dict(graph_trace.to_dict())
        else:
            snapshot = GraphRetrievalSnapshot.from_dict(graph_trace)
        if snapshot.query and snapshot.query != question:
            return GraphRetrievalSnapshot()
        return snapshot

    @staticmethod
    def _format_strategy_summary(analysis: QueryAnalysis) -> str:
        strategy_icons = {
            "hybrid_traditional": "[HYBRID]",
            "graph_rag": "[GRAPH]",
            "combined": "[COMBINED]",
        }
        strategy_icon = strategy_icons.get(analysis.recommended_strategy.value, "[ROUTE]")
        return (
            f"{strategy_icon} Strategy: {analysis.recommended_strategy.value}\n"
            f"Complexity: {analysis.query_complexity:.2f}, "
            f"Relationship intensity: {analysis.relationship_intensity:.2f}"
        )

    @staticmethod
    def _format_document_summary(documents: List[Document]) -> str:
        doc_info = []
        for doc in documents:
            recipe_name = doc.metadata.get("recipe_name", "unknown")
            search_type = doc.metadata.get("search_type", doc.metadata.get("route_strategy", "unknown"))
            score = doc.metadata.get("final_score", doc.metadata.get("relevance_score", doc.metadata.get("score", 0)))
            try:
                score_text = f"{float(score):.3f}"
            except (TypeError, ValueError):
                score_text = str(score)
            doc_info.append(f"{recipe_name}({search_type}, {score_text})")
        summary = f"Found {len(documents)} relevant documents: {', '.join(doc_info[:3])}"
        if len(doc_info) > 3:
            summary += f"\n    Total results: {len(documents)}"
        return summary

    @staticmethod
    def _emit(callback: MessageCallback, message: str) -> None:
        if callback:
            callback(message)
