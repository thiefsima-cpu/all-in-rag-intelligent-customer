"""Adapters that normalize trace-capable router and generation interfaces."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Protocol, TypeAlias, cast, runtime_checkable

from ...runtime import (
    AnswerContext,
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
from .answer_models import ChunkCallback


class QueryRouterProtocol(Protocol):
    """Router surface consumed by the answer pipeline."""

    def route(self, query: str, top_k: int = 5) -> object: ...


@runtime_checkable
class QueryRouterWithTraceProtocol(Protocol):
    """Optional router trace surface consumed when available."""

    def route_with_trace(
        self,
        query: str,
        top_k: int = 5,
    ) -> tuple[object, object | None]: ...


QueryRouterSource: TypeAlias = QueryRouterProtocol | QueryRouterWithTraceProtocol


@runtime_checkable
class ExplainableQueryRouterProtocol(Protocol):
    """Optional router explanation surface used for interactive traces."""

    def explain_routing_decision(self, query: str) -> str: ...


class GenerationServiceProtocol(Protocol):
    """Generation surface consumed by the answer pipeline."""

    def generate_answer_from_context(self, answer_context: AnswerContext) -> str: ...

    def generate_answer_stream_from_context(
        self,
        answer_context: AnswerContext,
    ) -> Iterable[object]: ...


@runtime_checkable
class GenerationTraceServiceProtocol(Protocol):
    """Optional non-streaming generation trace surface."""

    def generate_answer_with_trace_from_context(
        self,
        answer_context: AnswerContext,
    ) -> tuple[object, object]: ...


@runtime_checkable
class GenerationStreamTraceServiceProtocol(Protocol):
    """Optional streaming generation trace surface."""

    def generate_answer_stream_with_trace_from_context(
        self,
        answer_context: AnswerContext,
        *,
        chunk_callback: ChunkCallback = None,
    ) -> tuple[object, object]: ...


GenerationServiceSource: TypeAlias = (
    GenerationServiceProtocol
    | GenerationTraceServiceProtocol
    | GenerationStreamTraceServiceProtocol
)


class QueryRouterTraceAdapter:
    """Normalize router results without consulting shared request state."""

    def __init__(self, router: QueryRouterSource) -> None:
        self.router = router

    def route_with_trace(self, question: str, top_k: int) -> tuple[RouteResolution, RouteSnapshot]:
        if isinstance(self.router, QueryRouterWithTraceProtocol):
            raw_resolution, route_trace = self.router.route_with_trace(question, top_k)
        else:
            raw_resolution = cast(QueryRouterProtocol, self.router).route(question, top_k)
            route_trace = None
        if isinstance(raw_resolution, RouteResolution):
            resolution = raw_resolution
        elif isinstance(raw_resolution, Mapping):
            resolution = RouteResolution.from_dict(dict(raw_resolution))
        else:
            resolution = RouteResolution()
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
                graph_trace = details.get("graph_trace")
                if isinstance(graph_trace, dict):
                    trace_payload = dict(graph_trace)
                else:
                    trace_payload = {
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
        route_trace: object | None = None,
    ) -> RouteSnapshot:
        route_trace = route_trace or (
            resolution.metadata.get("route_trace") if resolution.metadata else None
        )
        if not self._has_route_trace(route_trace):
            route_trace = resolution.retrieval.route_trace
        return clone_route_snapshot(route_trace)

    @staticmethod
    def _has_route_trace(value: object) -> bool:
        if isinstance(value, RouteSnapshot):
            return value.has_content()
        return bool(value)


class GenerationTraceAdapter:
    """Normalize generation results without consulting shared request state."""

    def __init__(self, generation_service: GenerationServiceSource) -> None:
        self.generation_service = generation_service

    def generate_answer_with_trace_from_context(
        self,
        answer_context: AnswerContext,
    ) -> tuple[str, GenerationSnapshot]:
        if isinstance(self.generation_service, GenerationTraceServiceProtocol):
            answer, trace = self.generation_service.generate_answer_with_trace_from_context(
                answer_context
            )
            return str(answer), clone_generation_snapshot(trace)
        answer = cast(
            GenerationServiceProtocol, self.generation_service
        ).generate_answer_from_context(answer_context)
        return str(answer), GenerationSnapshot()

    def generate_answer_stream_with_trace_from_context(
        self,
        answer_context: AnswerContext,
        *,
        chunk_callback: ChunkCallback = None,
    ) -> tuple[str, GenerationSnapshot]:
        if isinstance(self.generation_service, GenerationStreamTraceServiceProtocol):
            answer, trace = self.generation_service.generate_answer_stream_with_trace_from_context(
                answer_context,
                chunk_callback=chunk_callback,
            )
            return str(answer), clone_generation_snapshot(trace)

        chunks: list[str] = []
        generation_service = cast(GenerationServiceProtocol, self.generation_service)
        for chunk_text in generation_service.generate_answer_stream_from_context(answer_context):
            chunks.append(str(chunk_text))
            if chunk_callback:
                chunk_callback(str(chunk_text))
        answer = "".join(chunks).strip() or "Streaming output completed"
        return answer, GenerationSnapshot()


__all__ = [
    "ExplainableQueryRouterProtocol",
    "GenerationServiceSource",
    "GenerationServiceProtocol",
    "GenerationTraceAdapter",
    "QueryRouterSource",
    "QueryRouterTraceAdapter",
    "QueryRouterProtocol",
]
