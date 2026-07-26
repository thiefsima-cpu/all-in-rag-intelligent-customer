"""Application adapters for trace-capable router and generation ports."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Protocol, TypeAlias, cast, runtime_checkable

from ...contracts import QuerySemanticRuntimeSettings, RequestControl
from ...contracts.runtime import (
    AnswerContext,
    GenerationSnapshot,
    GraphRetrievalSnapshot,
    RouteResolution,
    RouteSnapshot,
)
from .answer_models import ChunkCallback


class QueryRouterProtocol(Protocol):
    """Router surface consumed by the answer pipeline."""

    def route(
        self,
        query: str,
        top_k: int = 5,
        *,
        control: RequestControl | None = None,
    ) -> object: ...


@runtime_checkable
class QueryRouterWithTraceProtocol(Protocol):
    """Optional router trace surface consumed when available."""

    def route_with_trace(
        self,
        query: str,
        top_k: int = 5,
        *,
        control: RequestControl | None = None,
    ) -> tuple[object, RouteSnapshot | Mapping[str, object] | None]: ...


QueryRouterSource: TypeAlias = QueryRouterProtocol | QueryRouterWithTraceProtocol


@runtime_checkable
class ExplainableQueryRouterProtocol(Protocol):
    """Optional router explanation surface used for interactive traces."""

    def explain_routing_decision(self, query: str) -> str: ...


class GenerationServiceProtocol(Protocol):
    """Generation surface consumed by the answer pipeline."""

    def generate_answer_from_context(
        self,
        answer_context: AnswerContext,
        *,
        control: RequestControl | None = None,
    ) -> str: ...

    def generate_answer_stream_from_context(
        self,
        answer_context: AnswerContext,
        *,
        control: RequestControl | None = None,
    ) -> Iterable[object]: ...


@runtime_checkable
class GenerationTraceServiceProtocol(Protocol):
    """Optional non-streaming generation trace surface."""

    def generate_answer_with_trace_from_context(
        self,
        answer_context: AnswerContext,
        *,
        control: RequestControl | None = None,
    ) -> tuple[object, GenerationSnapshot | Mapping[str, object] | None]: ...


@runtime_checkable
class GenerationStreamTraceServiceProtocol(Protocol):
    """Optional streaming generation trace surface."""

    def generate_answer_stream_with_trace_from_context(
        self,
        answer_context: AnswerContext,
        *,
        chunk_callback: ChunkCallback = None,
        control: RequestControl | None = None,
    ) -> tuple[object, GenerationSnapshot | Mapping[str, object] | None]: ...


GenerationServiceSource: TypeAlias = (
    GenerationServiceProtocol
    | GenerationTraceServiceProtocol
    | GenerationStreamTraceServiceProtocol
)


class QueryRouterTraceAdapter:
    """Normalize router results without consulting shared request state."""

    def __init__(
        self,
        router: QueryRouterSource,
        semantic_settings: QuerySemanticRuntimeSettings,
    ) -> None:
        self.router = router
        self.semantic_settings = semantic_settings

    def route_with_trace(
        self,
        question: str,
        top_k: int,
        *,
        control: RequestControl | None = None,
    ) -> tuple[RouteResolution, RouteSnapshot]:
        if isinstance(self.router, QueryRouterWithTraceProtocol):
            raw_resolution, route_trace = self.router.route_with_trace(
                question,
                top_k,
                control=control,
            )
        else:
            raw_resolution = cast(QueryRouterProtocol, self.router).route(
                question,
                top_k,
                control=control,
            )
            route_trace = None
        if isinstance(raw_resolution, RouteResolution):
            resolution = raw_resolution
        elif isinstance(raw_resolution, Mapping):
            resolution = RouteResolution.from_dict(
                dict(raw_resolution),
                semantic_settings=self.semantic_settings,
            )
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
            snapshot = GraphRetrievalSnapshot.from_dict(
                trace_payload,
                semantic_settings=self.semantic_settings,
            )
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
        route_trace: RouteSnapshot | Mapping[str, object] | None = None,
    ) -> RouteSnapshot:
        if not route_trace and resolution.metadata:
            metadata_route_trace = resolution.metadata.get("route_trace")
            if isinstance(metadata_route_trace, Mapping):
                route_trace = metadata_route_trace
        if not self._has_route_trace(route_trace):
            route_trace = resolution.retrieval.route_trace
        if isinstance(route_trace, RouteSnapshot):
            return route_trace.copy(semantic_settings=self.semantic_settings)
        if isinstance(route_trace, Mapping):
            return RouteSnapshot.from_dict(
                route_trace,
                semantic_settings=self.semantic_settings,
            )
        return RouteSnapshot()

    @staticmethod
    def _has_route_trace(value: RouteSnapshot | Mapping[str, object] | None) -> bool:
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
        *,
        control: RequestControl | None = None,
    ) -> tuple[str, GenerationSnapshot]:
        if isinstance(self.generation_service, GenerationTraceServiceProtocol):
            answer, trace = self.generation_service.generate_answer_with_trace_from_context(
                answer_context,
                control=control,
            )
            return str(answer), self._normalize_generation_snapshot(trace)
        answer = cast(
            GenerationServiceProtocol, self.generation_service
        ).generate_answer_from_context(answer_context, control=control)
        return str(answer), GenerationSnapshot()

    def generate_answer_stream_with_trace_from_context(
        self,
        answer_context: AnswerContext,
        *,
        chunk_callback: ChunkCallback = None,
        control: RequestControl | None = None,
    ) -> tuple[str, GenerationSnapshot]:
        if isinstance(self.generation_service, GenerationStreamTraceServiceProtocol):
            answer, trace = self.generation_service.generate_answer_stream_with_trace_from_context(
                answer_context,
                chunk_callback=chunk_callback,
                control=control,
            )
            return str(answer), self._normalize_generation_snapshot(trace)

        chunks: list[str] = []
        generation_service = cast(GenerationServiceProtocol, self.generation_service)
        for chunk_text in generation_service.generate_answer_stream_from_context(
            answer_context,
            control=control,
        ):
            chunks.append(str(chunk_text))
            if chunk_callback:
                chunk_callback(str(chunk_text))
        answer = "".join(chunks).strip() or "Streaming output completed"
        return answer, GenerationSnapshot()

    @staticmethod
    def _normalize_generation_snapshot(
        trace: GenerationSnapshot | Mapping[str, object] | None,
    ) -> GenerationSnapshot:
        if isinstance(trace, GenerationSnapshot):
            return trace.copy()
        if isinstance(trace, Mapping):
            return GenerationSnapshot.from_dict(trace)
        return GenerationSnapshot()


__all__ = [
    "ExplainableQueryRouterProtocol",
    "GenerationServiceSource",
    "GenerationServiceProtocol",
    "GenerationTraceAdapter",
    "QueryRouterSource",
    "QueryRouterTraceAdapter",
    "QueryRouterProtocol",
]
