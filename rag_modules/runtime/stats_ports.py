"""Runtime statistics access contracts shared by build and serving layers."""

from __future__ import annotations

from typing import Any, Protocol


class RuntimeStatsAccessPort(Protocol):
    """Stable boundary for runtime statistics and profile payload extraction."""

    def get_graph_data_stats(self, data_module: Any) -> dict[str, Any]: ...

    def get_vector_collection_stats(self, index_module: Any) -> dict[str, Any]: ...

    def get_route_stats(self, routing_workflow: Any) -> dict[str, Any]: ...

    def get_retrieval_runtime_profile(self, retrieval_runtime_profile: Any) -> dict[str, Any]: ...

    def get_query_trace_stats(self, query_tracer: Any) -> dict[str, Any]: ...


__all__ = ["RuntimeStatsAccessPort"]
