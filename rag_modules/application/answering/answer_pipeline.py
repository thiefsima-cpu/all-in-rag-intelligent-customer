"""Pipeline execution for grounded question answering."""

from __future__ import annotations

import logging
from contextlib import nullcontext

from ...contracts import EvidenceDocument, QuerySemanticRuntimeSettings, RequestControl
from ...contracts.runtime import (
    AnswerContext,
    GenerationMode,
    GenerationSnapshot,
    QueryAnalysis,
)
from ...safe_logging import log_failure
from ..ports import AnswerTelemetryPort, AnswerWorkflowCopy
from .answer_models import AnswerPipelineState, ChunkCallback, MessageCallback
from .trace_adapters import (
    ExplainableQueryRouterProtocol,
    GenerationServiceSource,
    GenerationTraceAdapter,
    QueryRouterSource,
    QueryRouterTraceAdapter,
)

logger = logging.getLogger(__name__)


class AnswerPipelineService:
    """Execute routing and answer generation over the stable runtime contracts."""

    def __init__(
        self,
        *,
        query_router: QueryRouterSource,
        generation_service: GenerationServiceSource,
        semantic_settings: QuerySemanticRuntimeSettings,
        top_k: int,
        answer_workflow_copy: AnswerWorkflowCopy,
        telemetry: AnswerTelemetryPort | None = None,
    ) -> None:
        self.query_router = query_router
        self.generation_service = generation_service
        self.router_traces = QueryRouterTraceAdapter(query_router, semantic_settings)
        self.generation_traces = GenerationTraceAdapter(generation_service)
        self.top_k = max(0, int(top_k or 0))
        self.answer_workflow_copy = answer_workflow_copy
        self.telemetry = telemetry

    def execute(self, state: AnswerPipelineState) -> AnswerPipelineState:
        control = state.request_control
        if control is not None:
            control.raise_if_cancelled()
        self._emit(
            state.message_callback,
            self.answer_workflow_copy.user_question_template.format(question=state.question),
        )
        if state.explain_routing and isinstance(
            self.query_router,
            ExplainableQueryRouterProtocol,
        ):
            self._emit(
                state.message_callback,
                self.query_router.explain_routing_decision(state.question),
            )

        self._emit(state.message_callback, self.answer_workflow_copy.query_routing_started)
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
                control=control,
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
                mode=GenerationMode.EMPTY,
                decision_reason="no_evidence",
                failure_code="no_evidence",
                total_evidence_items=0,
                selected_evidence_items=0,
            )
            state.answer = self.answer_workflow_copy.no_evidence_answer
            return state

        self._emit(state.message_callback, self._format_document_summary(state.evidence_documents))
        self._emit(state.message_callback, self.answer_workflow_copy.answer_generation_started)
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
                control=control,
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
                    state.generation_trace.mode_value or "unknown",
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
        self._emit(
            callback,
            self.answer_workflow_copy.answer_complete_template.format(
                latency_seconds=latency_ms / 1000,
            ),
        )

    def _generate_answer(
        self,
        *,
        answer_context: AnswerContext,
        stream: bool,
        chunk_callback: ChunkCallback,
        message_callback: MessageCallback,
        control: RequestControl | None,
    ) -> tuple[str, GenerationSnapshot]:
        if not stream:
            return self.generation_traces.generate_answer_with_trace_from_context(
                answer_context,
                control=control,
            )

        try:
            answer, trace = self.generation_traces.generate_answer_stream_with_trace_from_context(
                answer_context,
                chunk_callback=chunk_callback,
                control=control,
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
                self.answer_workflow_copy.streaming_interrupted_fallback,
            )
            return self.generation_traces.generate_answer_with_trace_from_context(
                answer_context,
                control=control,
            )

    def _format_strategy_summary(self, analysis: QueryAnalysis) -> str:
        strategy_icons = {
            "hybrid_traditional": self.answer_workflow_copy.strategy_icon_hybrid_traditional,
            "graph_rag": self.answer_workflow_copy.strategy_icon_graph_rag,
            "combined": self.answer_workflow_copy.strategy_icon_combined,
        }
        strategy_icon = strategy_icons.get(
            analysis.recommended_strategy.value,
            self.answer_workflow_copy.strategy_icon_default,
        )
        return self.answer_workflow_copy.strategy_summary_template.format(
            strategy_icon=strategy_icon,
            strategy=analysis.recommended_strategy.value,
            complexity=analysis.query_complexity,
            relationship_intensity=analysis.relationship_intensity,
        )

    def _format_document_summary(self, documents: list[EvidenceDocument]) -> str:
        doc_info = []
        for doc in documents:
            metadata = doc.metadata or {}
            recipe_name = (
                doc.recipe_name
                or metadata.get("recipe_name")
                or self.answer_workflow_copy.unknown_recipe_name
            )
            search_type = (
                doc.search_type
                or metadata.get("route_strategy")
                or self.answer_workflow_copy.unknown_search_type
            )
            score = metadata.get("final_score", metadata.get("relevance_score", doc.score))
            try:
                score_text = f"{float(score):.3f}"
            except (TypeError, ValueError):
                score_text = str(score)
            doc_info.append(f"{recipe_name}({search_type}, {score_text})")
        summary = self.answer_workflow_copy.document_summary_template.format(
            document_count=len(documents),
            document_summaries=", ".join(doc_info[:3]),
        )
        if len(doc_info) > 3:
            summary += self.answer_workflow_copy.document_summary_total_template.format(
                document_count=len(documents),
            )
        return summary

    @staticmethod
    def _emit(callback: MessageCallback, message: str) -> None:
        if callback:
            callback(message)


__all__ = ["AnswerPipelineService"]
