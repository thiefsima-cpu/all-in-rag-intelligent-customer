"""Trace assembly for the question-answer application use case."""

from __future__ import annotations

from ...contracts import QuerySemanticRuntimeSettings
from ...contracts.runtime import (
    GenerationSnapshot,
    GraphRetrievalSnapshot,
    QueryTraceEvent,
    RouteSnapshot,
    RuntimeErrorDetail,
)
from ..ports import QueryTracerPort
from .answer_models import AnswerPipelineState, AnswerTraceBundle


class AnswerTraceAssembler:
    """Capture route/graph/generation snapshots and persist query traces."""

    def __init__(
        self,
        *,
        query_tracer: QueryTracerPort | None,
        semantic_settings: QuerySemanticRuntimeSettings,
        query_router: object | None = None,
        generation_service: object | None = None,
    ) -> None:
        del query_router, generation_service
        self.query_tracer = query_tracer
        self.semantic_settings = semantic_settings

    def record(
        self,
        *,
        state: AnswerPipelineState,
        latency_ms: float,
        answer: str | None = None,
        error: RuntimeErrorDetail | None = None,
    ) -> AnswerTraceBundle:
        route_trace = self._state_route_snapshot(state)
        graph_trace = self._state_graph_snapshot(state)
        generation_trace = self._state_generation_snapshot(state)
        trace_event = QueryTraceEvent()
        if self.query_tracer is not None:
            trace_event = self.query_tracer.record(
                query=state.question,
                analysis=state.analysis,
                documents=state.answer_context,
                latency_ms=latency_ms,
                answer=answer,
                error=error,
                route_trace=route_trace,
                graph_trace=graph_trace,
                generation_trace=generation_trace,
            )
        return AnswerTraceBundle(
            route_trace=route_trace,
            graph_trace=graph_trace,
            generation_trace=generation_trace,
            trace_event=trace_event,
        )

    def _state_route_snapshot(self, state: AnswerPipelineState) -> RouteSnapshot:
        return state.route_trace.copy(semantic_settings=self.semantic_settings)

    @staticmethod
    def _state_generation_snapshot(state: AnswerPipelineState) -> GenerationSnapshot:
        return state.generation_trace.copy()

    def _state_graph_snapshot(self, state: AnswerPipelineState) -> GraphRetrievalSnapshot:
        return state.graph_trace.copy(semantic_settings=self.semantic_settings)


__all__ = ["AnswerTraceAssembler"]
