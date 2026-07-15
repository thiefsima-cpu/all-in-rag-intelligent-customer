"""Default adapters for runtime statistics and profile payload extraction."""

from __future__ import annotations

from ..kernel.json_types import JsonObject, coerce_json_object
from .stats_ports import (
    GraphStatisticsSourcePort,
    QueryTraceStatisticsSourcePort,
    RouteStatisticsSourcePort,
    RuntimeProfilePayloadSource,
    VectorCollectionStatisticsSourcePort,
)


class DefaultRuntimeStatsAccess:
    """Default adapter over graph/vector/routing/runtime-profile statistics."""

    def get_graph_data_stats(
        self,
        data_module: GraphStatisticsSourcePort | None,
    ) -> JsonObject:
        if data_module is None:
            return {}
        return coerce_json_object(data_module.get_statistics())

    def get_vector_collection_stats(
        self,
        index_module: VectorCollectionStatisticsSourcePort | None,
    ) -> JsonObject:
        if index_module is None:
            return {}
        return coerce_json_object(index_module.get_collection_stats())

    def get_route_stats(
        self,
        routing_workflow: RouteStatisticsSourcePort | None,
    ) -> JsonObject:
        if routing_workflow is None:
            return {}
        return coerce_json_object(routing_workflow.get_route_statistics())

    def get_retrieval_runtime_profile(
        self,
        retrieval_runtime_profile: RuntimeProfilePayloadSource | None,
    ) -> JsonObject:
        if retrieval_runtime_profile is None:
            return {}
        return coerce_json_object(retrieval_runtime_profile.to_dict())

    def get_query_trace_stats(
        self,
        query_tracer: QueryTraceStatisticsSourcePort | None,
    ) -> JsonObject:
        if query_tracer is None:
            return {}
        stats = getattr(query_tracer, "stats", None)
        if not callable(stats):
            return {}
        return coerce_json_object(stats())


__all__ = ["DefaultRuntimeStatsAccess"]
