"""Result construction for the question-answer workflow."""

from __future__ import annotations

from .answer_models import AnswerPipelineState, AnswerTraceBundle, QuestionAnswerResult


class QuestionAnswerResultFactory:
    """Create stable question-answer responses from pipeline state."""

    def from_pipeline_state(
        self,
        state: AnswerPipelineState,
        *,
        latency_ms: float,
        trace_bundle: AnswerTraceBundle,
    ) -> QuestionAnswerResult:
        return QuestionAnswerResult(
            answer=state.answer,
            analysis=state.analysis,
            retrieval_outcome=state.retrieval_outcome,
            answer_context=state.answer_context,
            route_resolution=state.route_resolution,
            latency_ms=latency_ms,
            route_trace=trace_bundle.route_trace,
            graph_trace=trace_bundle.graph_trace,
            generation_trace=trace_bundle.generation_trace,
            trace_event=trace_bundle.trace_event,
        )

    def from_error(
        self,
        state: AnswerPipelineState,
        *,
        latency_ms: float,
        trace_bundle: AnswerTraceBundle,
        error: Exception,
    ) -> QuestionAnswerResult:
        del error
        return QuestionAnswerResult(
            answer="The answer could not be generated.",
            analysis=None,
            retrieval_outcome=state.retrieval_outcome,
            answer_context=state.answer_context,
            route_resolution=state.route_resolution,
            latency_ms=latency_ms,
            route_trace=trace_bundle.route_trace,
            graph_trace=trace_bundle.graph_trace,
            generation_trace=trace_bundle.generation_trace,
            trace_event=trace_bundle.trace_event,
        )


__all__ = ["QuestionAnswerResultFactory"]
