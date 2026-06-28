"""Pipeline execution for grounded question answering."""

from __future__ import annotations

import logging
from contextlib import nullcontext
from typing import List

from ...retrieval.contracts import EvidenceDocument
from ...runtime import (
    AnswerContext,
    GenerationSnapshot,
    QueryAnalysis,
)
from ...safe_logging import log_failure
from .answer_models import AnswerPipelineState, ChunkCallback, MessageCallback
from .trace_adapters import GenerationTraceAdapter, QueryRouterTraceAdapter

logger = logging.getLogger(__name__)

NO_EVIDENCE_ANSWER = (
    "Sorry, I could not find enough relevant retrieval evidence to answer that question."
)


class AnswerPipelineService:
    """Execute routing and answer generation over the stable runtime contracts."""

    def __init__(
        self,
        *,
        query_router,
        generation_service,
        top_k: int,
        telemetry=None,
    ) -> None:
        self.query_router = query_router
        self.generation_service = generation_service
        self.router_traces = QueryRouterTraceAdapter(query_router)
        self.generation_traces = GenerationTraceAdapter(generation_service)
        self.top_k = max(0, int(top_k or 0))
        self.telemetry = telemetry

    def execute(self, state: AnswerPipelineState) -> AnswerPipelineState:
        self._emit(state.message_callback, f"\nUser question: {state.question}")
        if state.explain_routing:
            explain = getattr(self.query_router, "explain_routing_decision", None)
            if callable(explain):
                self._emit(state.message_callback, explain(state.question))

        self._emit(state.message_callback, "Running query routing...")
        retrieval_span = (
            self.telemetry.span(
                "rag.retrieval",
                attributes={"rag.top_k": self.top_k},
            )
            if self.telemetry is not None
            else nullcontext(None)
        )
        with retrieval_span as span:
            resolution, route_trace = self.router_traces.route_with_trace(
                state.question,
                self.top_k,
            )
            if span is not None:
                span.set_attribute(
                    "rag.document.count",
                    len(resolution.retrieval.evidence_documents),
                )
                if resolution.analysis is not None:
                    span.set_attribute(
                        "rag.strategy",
                        resolution.analysis.strategy_name,
                    )
        state.route_resolution = resolution
        state.retrieval_outcome = resolution.retrieval
        state.analysis = resolution.analysis
        state.answer_context = AnswerContext.from_route_resolution(resolution)
        state.route_trace = route_trace
        state.graph_trace = self.router_traces.graph_trace_for_question(
            state.route_trace,
            state.question,
        )

        if state.analysis:
            self._emit(state.message_callback, self._format_strategy_summary(state.analysis))

        if not state.has_evidence:
            state.generation_trace = GenerationSnapshot(
                status="failed",
                mode="empty",
                decision_reason="no_evidence",
                failure_code="no_evidence",
                total_evidence_items=0,
                selected_evidence_items=0,
            )
            state.answer = NO_EVIDENCE_ANSWER
            return state

        self._emit(state.message_callback, self._format_document_summary(state.evidence_documents))
        self._emit(state.message_callback, "Generating answer...")
        generation_span = (
            self.telemetry.span(
                "rag.generation",
                attributes={"gen_ai.operation.name": "chat"},
            )
            if self.telemetry is not None
            else nullcontext(None)
        )
        with generation_span as span:
            state.answer, state.generation_trace = self._generate_answer(
                answer_context=state.answer_context,
                stream=state.stream,
                chunk_callback=state.chunk_callback,
                message_callback=state.message_callback,
            )
            if span is not None:
                span.set_attribute(
                    "gen_ai.usage.input_tokens",
                    state.generation_trace.prompt_tokens,
                )
                span.set_attribute(
                    "gen_ai.usage.output_tokens",
                    state.generation_trace.completion_tokens,
                )
                span.set_attribute(
                    "rag.generation.mode",
                    state.generation_trace.mode or "unknown",
                )
        return state

    def capture_runtime_traces(self, state: AnswerPipelineState) -> AnswerPipelineState:
        if not state.route_trace.has_content():
            state.route_trace = self.router_traces.resolve_route_trace(
                state.route_resolution,
                route_trace=state.route_trace,
            )
        if not state.graph_trace.has_content():
            state.graph_trace = self.router_traces.graph_trace_for_question(
                state.route_trace,
                state.question,
            )
        return state

    def emit_completion(self, callback: MessageCallback, latency_ms: float) -> None:
        self._emit(callback, f"\nAnswer complete in {latency_ms / 1000:.2f}s")

    def _generate_answer(
        self,
        *,
        answer_context: AnswerContext,
        stream: bool,
        chunk_callback: ChunkCallback,
        message_callback: MessageCallback,
    ) -> tuple[str, GenerationSnapshot]:
        if not stream:
            return self.generation_traces.generate_answer_with_trace_from_context(answer_context)

        try:
            answer, trace = self.generation_traces.generate_answer_stream_with_trace_from_context(
                answer_context,
                chunk_callback=chunk_callback,
            )
            if chunk_callback:
                chunk_callback("\n")
            return answer, trace
        except Exception as exc:
            log_failure(
                logger,
                logging.ERROR,
                "streaming_output_failed",
                code="ANSWER_FAILED",
                error=exc,
            )
            self._emit(
                message_callback,
                "\n[WARN] Streaming output interrupted. Falling back to standard mode...",
            )
            return self.generation_traces.generate_answer_with_trace_from_context(answer_context)

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
    def _format_document_summary(documents: List[EvidenceDocument]) -> str:
        doc_info = []
        for doc in documents:
            metadata = doc.metadata or {}
            recipe_name = doc.recipe_name or metadata.get("recipe_name") or "unknown"
            search_type = doc.search_type or metadata.get("route_strategy") or "unknown"
            score = metadata.get("final_score", metadata.get("relevance_score", doc.score))
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


__all__ = ["AnswerPipelineService", "NO_EVIDENCE_ANSWER"]
