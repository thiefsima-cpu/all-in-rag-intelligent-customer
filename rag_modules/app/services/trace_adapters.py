"""Adapters that normalize trace-capable router and generation interfaces."""

from __future__ import annotations

from ...runtime import (
    GenerationSnapshot,
    GraphRetrievalSnapshot,
    RouteResolution,
    RouteSnapshot,
)
from ...runtime.snapshot_utils import (
    clone_generation_snapshot,
    clone_graph_snapshot,
    clone_route_snapshot,
)


class QueryRouterTraceAdapter:
    """Normalize router results without consulting shared request state."""

    def __init__(self, router) -> None:
        self.router = router

    def route_with_trace(self, question: str, top_k: int) -> tuple[RouteResolution, RouteSnapshot]:
        route_with_trace = getattr(self.router, "route_with_trace", None)
        if callable(route_with_trace):
            resolution, route_trace = route_with_trace(question, top_k)
        else:
            resolution = self.router.route(question, top_k)
            route_trace = None
        if not isinstance(resolution, RouteResolution):
            resolution = RouteResolution.from_dict(resolution or {})
        return resolution, self.resolve_route_trace(resolution, route_trace=route_trace)

    def graph_trace_for_question(
        self,
        route_trace: RouteSnapshot,
        question: str,
    ) -> GraphRetrievalSnapshot:
        stage_names = ("graph_rag", "combined")
        for stage_name in stage_names:
            stage = route_trace.stages.get(stage_name)
            if not stage:
                continue
            details = dict(stage.details or {})
            if stage_name == "graph_rag":
                trace_payload = {
                    "query": details.get("query") or question,
                    "doc_count": stage.doc_count,
                    **details,
                }
            else:
                trace_payload = details.get("graph_trace") or {
                    "query": details.get("query") or question,
                    "doc_count": details.get("graph_doc_count", stage.doc_count),
                    **details,
                }
            if not trace_payload:
                continue
            snapshot = clone_graph_snapshot(trace_payload)
            if snapshot.query and snapshot.query != question:
                continue
            if snapshot.has_content():
                return snapshot

        if route_trace.strategy not in {"graph_rag", "combined"}:
            return GraphRetrievalSnapshot()

        return GraphRetrievalSnapshot()

    def resolve_route_trace(
        self,
        resolution: RouteResolution,
        *,
        route_trace=None,
    ) -> RouteSnapshot:
        route_trace = route_trace or (
            resolution.metadata.get("route_trace") if resolution.metadata else None
        )
        if not self._has_route_trace(route_trace):
            route_trace = resolution.retrieval.route_trace
        return clone_route_snapshot(route_trace)

    @staticmethod
    def _has_route_trace(value) -> bool:
        if isinstance(value, RouteSnapshot):
            return value.has_content()
        return bool(value)


class GenerationTraceAdapter:
    """Normalize generation results without consulting shared request state."""

    def __init__(self, generation_service) -> None:
        self.generation_service = generation_service

    def generate_answer_with_trace_from_context(
        self,
        answer_context,
    ) -> tuple[str, GenerationSnapshot]:
        generate_with_trace = getattr(
            self.generation_service,
            "generate_answer_with_trace_from_context",
            None,
        )
        if callable(generate_with_trace):
            answer, trace = generate_with_trace(answer_context)
            return answer, clone_generation_snapshot(trace)
        answer = self.generation_service.generate_answer_from_context(answer_context)
        return answer, GenerationSnapshot()

    def generate_answer_stream_with_trace_from_context(
        self,
        answer_context,
        *,
        chunk_callback=None,
    ) -> tuple[str, GenerationSnapshot]:
        generate_stream_with_trace = getattr(
            self.generation_service,
            "generate_answer_stream_with_trace_from_context",
            None,
        )
        if callable(generate_stream_with_trace):
            answer, trace = generate_stream_with_trace(
                answer_context,
                chunk_callback=chunk_callback,
            )
            return answer, clone_generation_snapshot(trace)

        chunks: list[str] = []
        for chunk_text in self.generation_service.generate_answer_stream_from_context(answer_context):
            chunks.append(chunk_text)
            if chunk_callback:
                chunk_callback(chunk_text)
        answer = "".join(chunks).strip() or "Streaming output completed"
        return answer, GenerationSnapshot()


__all__ = [
    "GenerationTraceAdapter",
    "QueryRouterTraceAdapter",
]
