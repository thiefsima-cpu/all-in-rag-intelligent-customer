"""Trace assembly for the question-answer workflow."""

from __future__ import annotations

from ...runtime import (
    GenerationSnapshot,
    GraphRetrievalSnapshot,
    QueryTraceEvent,
    RouteSnapshot,
)
from ...runtime.snapshot_utils import (
    clone_generation_snapshot,
    clone_graph_snapshot,
    clone_route_snapshot,
)
from ...runtime_contracts import QueryTracerPort
from .answer_models import AnswerPipelineState, AnswerTraceBundle


class AnswerTraceAssembler:
    """Capture route/graph/generation snapshots and persist query traces."""

    def __init__(
        self,
        *,
        query_tracer: QueryTracerPort | None,
        query_router: object | None = None,
        generation_service: object | None = None,
    ) -> None:
        del query_router, generation_service
        self.query_tracer = query_tracer

    def record(
        self,
        *,
        state: AnswerPipelineState,
        latency_ms: float,
        answer: str | None = None,
        error: str | None = None,
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

    @staticmethod
    def _state_route_snapshot(state: AnswerPipelineState) -> RouteSnapshot:
        route_trace = getattr(state, "route_trace", RouteSnapshot())
        return clone_route_snapshot(route_trace)

    @staticmethod
    def _state_generation_snapshot(state: AnswerPipelineState) -> GenerationSnapshot:
        generation_trace = getattr(state, "generation_trace", GenerationSnapshot())
        return clone_generation_snapshot(generation_trace)

    @staticmethod
    def _state_graph_snapshot(state: AnswerPipelineState) -> GraphRetrievalSnapshot:
        graph_trace = getattr(state, "graph_trace", GraphRetrievalSnapshot())
        return clone_graph_snapshot(graph_trace)


__all__ = ["AnswerTraceAssembler"]
