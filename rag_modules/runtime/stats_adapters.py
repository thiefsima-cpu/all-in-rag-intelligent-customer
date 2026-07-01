"""Default adapters for runtime statistics and profile payload extraction."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .json_types import JsonObject, coerce_json_object

if TYPE_CHECKING:
    from ..retrieval.runtime_profile import RetrievalRuntimeProfile
    from ..routing.contracts import RoutingWorkflowProtocol
    from ..runtime_contracts import GraphDataModulePort, QueryTracerPort, VectorIndexModulePort


class DefaultRuntimeStatsAccess:
    """Default adapter over graph/vector/routing/runtime-profile statistics."""

    def get_graph_data_stats(self, data_module: GraphDataModulePort | None) -> JsonObject:
        if data_module is None:
            return {}
        return coerce_json_object(data_module.get_statistics())

    def get_vector_collection_stats(
        self,
        index_module: VectorIndexModulePort | None,
    ) -> JsonObject:
        if index_module is None:
            return {}
        return coerce_json_object(index_module.get_collection_stats())

    def get_route_stats(self, routing_workflow: RoutingWorkflowProtocol | None) -> JsonObject:
        if routing_workflow is None:
            return {}
        return coerce_json_object(routing_workflow.get_route_statistics())

    def get_retrieval_runtime_profile(
        self,
        retrieval_runtime_profile: RetrievalRuntimeProfile | None,
    ) -> JsonObject:
        if retrieval_runtime_profile is None:
            return {}
        return coerce_json_object(retrieval_runtime_profile.to_dict())

    def get_query_trace_stats(self, query_tracer: QueryTracerPort | None) -> JsonObject:
        if query_tracer is None:
            return {}
        return coerce_json_object(query_tracer.stats())


__all__ = ["DefaultRuntimeStatsAccess"]
