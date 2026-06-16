"""Default adapters for runtime statistics and profile payload extraction."""

from __future__ import annotations

from typing import Any


class DefaultRuntimeStatsAccess:
    """Default adapter over graph/vector/routing/runtime-profile statistics."""

    def get_graph_data_stats(self, data_module: Any) -> dict[str, Any]:
        if data_module is None:
            return {}
        return dict(data_module.get_statistics() or {})

    def get_vector_collection_stats(self, index_module: Any) -> dict[str, Any]:
        if index_module is None:
            return {}
        return dict(index_module.get_collection_stats() or {})

    def get_route_stats(self, routing_workflow: Any) -> dict[str, Any]:
        if routing_workflow is None:
            return {}
        return dict(routing_workflow.get_route_statistics() or {})

    def get_retrieval_runtime_profile(self, retrieval_runtime_profile: Any) -> dict[str, Any]:
        if retrieval_runtime_profile is None:
            return {}
        return dict(retrieval_runtime_profile.to_dict() or {})

    def get_query_trace_stats(self, query_tracer: Any) -> dict[str, Any]:
        if query_tracer is None:
            return {}
        stats_getter = getattr(query_tracer, "stats", None)
        if not callable(stats_getter):
            return {}
        return dict(stats_getter() or {})


__all__ = ["DefaultRuntimeStatsAccess"]
