"""Runtime-owned statistics access contracts."""

from __future__ import annotations

from typing import Protocol

from ..kernel.json_types import JsonObject


class GraphStatisticsSourcePort(Protocol):
    """Graph data source shape needed for runtime diagnostics."""

    def get_statistics(self) -> object: ...


class VectorCollectionStatisticsSourcePort(Protocol):
    """Vector collection source shape needed for runtime diagnostics."""

    def get_collection_stats(self, collection_name: str | None = None) -> object: ...


class RouteStatisticsSourcePort(Protocol):
    """Routing source shape needed for runtime diagnostics."""

    def get_route_statistics(self) -> object: ...


class QueryTraceStatisticsSourcePort(Protocol):
    """Query trace source shape needed for runtime diagnostics."""

    def stats(self) -> object: ...


class RuntimeProfilePayloadSource(Protocol):
    """Runtime-profile shaped object that can expose a JSON-compatible payload."""

    def to_dict(self) -> object: ...


class RuntimeStatsAccessPort(Protocol):
    """Stable boundary for runtime statistics and profile payload extraction."""

    def get_graph_data_stats(
        self,
        data_module: GraphStatisticsSourcePort | None,
    ) -> JsonObject: ...

    def get_vector_collection_stats(
        self,
        index_module: VectorCollectionStatisticsSourcePort | None,
    ) -> JsonObject: ...

    def get_route_stats(
        self,
        routing_workflow: RouteStatisticsSourcePort | None,
    ) -> JsonObject: ...

    def get_retrieval_runtime_profile(
        self,
        retrieval_runtime_profile: RuntimeProfilePayloadSource | None,
    ) -> JsonObject: ...

    def get_query_trace_stats(
        self,
        query_tracer: QueryTraceStatisticsSourcePort | None,
    ) -> JsonObject: ...


__all__ = [
    "GraphStatisticsSourcePort",
    "QueryTraceStatisticsSourcePort",
    "RouteStatisticsSourcePort",
    "RuntimeProfilePayloadSource",
    "RuntimeStatsAccessPort",
    "VectorCollectionStatisticsSourcePort",
]
