"""Runtime statistics access contracts shared by build and serving layers."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from .json_types import JsonObject

if TYPE_CHECKING:
    from ..routing.contracts import RoutingWorkflowProtocol
    from ..runtime_contracts import GraphDataModulePort, QueryTracerPort, VectorIndexModulePort


class RuntimeProfilePayloadSource(Protocol):
    """Runtime-profile shaped object that can expose a JSON-compatible payload."""

    def to_dict(self) -> object: ...


class RuntimeStatsAccessPort(Protocol):
    """Stable boundary for runtime statistics and profile payload extraction."""

    def get_graph_data_stats(self, data_module: GraphDataModulePort | None) -> JsonObject: ...

    def get_vector_collection_stats(
        self,
        index_module: VectorIndexModulePort | None,
    ) -> JsonObject: ...

    def get_route_stats(self, routing_workflow: RoutingWorkflowProtocol | None) -> JsonObject: ...

    def get_retrieval_runtime_profile(
        self,
        retrieval_runtime_profile: RuntimeProfilePayloadSource | None,
    ) -> JsonObject: ...

    def get_query_trace_stats(self, query_tracer: QueryTracerPort | None) -> JsonObject: ...


__all__ = ["RuntimeProfilePayloadSource", "RuntimeStatsAccessPort"]
