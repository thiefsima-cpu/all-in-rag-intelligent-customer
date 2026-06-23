"""Build grouped runtime views from build and serving runtime state."""

from __future__ import annotations

from .runtime_contracts import GraphDataModulePort, Neo4jManagerPort, VectorIndexModulePort
from .runtime_state import BuildRuntime, ServingRuntime
from .runtime_views import (
    SystemInfrastructureView,
    SystemRetrievalView,
    SystemServicesView,
)


class SystemRuntimeViewBuilder:
    """Assemble grouped runtime views from the current build/serving state."""

    def build_infrastructure_view(
        self,
        *,
        build_runtime: BuildRuntime | None,
        serving_runtime: ServingRuntime | None,
    ) -> SystemInfrastructureView:
        return SystemInfrastructureView(
            query_tracer=serving_runtime.query_tracer if serving_runtime else None,
            neo4j_manager=self._resolve_neo4j_manager(
                build_runtime=build_runtime,
                serving_runtime=serving_runtime,
            ),
            data_module=self._resolve_data_module(
                build_runtime=build_runtime,
                serving_runtime=serving_runtime,
            ),
            index_module=self._resolve_index_module(
                build_runtime=build_runtime,
                serving_runtime=serving_runtime,
            ),
        )

    def build_retrieval_view(
        self,
        *,
        serving_runtime: ServingRuntime | None,
    ) -> SystemRetrievalView:
        return SystemRetrievalView(
            retrieval_runtime_profile=(
                serving_runtime.retrieval_runtime_profile if serving_runtime else None
            ),
            query_understanding_service=(
                serving_runtime.query_understanding_service if serving_runtime else None
            ),
            traditional_retrieval=(
                serving_runtime.traditional_retrieval if serving_runtime else None
            ),
            graph_rag_retrieval=(serving_runtime.graph_rag_retrieval if serving_runtime else None),
            routing_workflow=(serving_runtime.routing_workflow if serving_runtime else None),
        )

    def build_services_view(
        self,
        *,
        build_runtime: BuildRuntime | None,
        serving_runtime: ServingRuntime | None,
    ) -> SystemServicesView:
        return SystemServicesView(
            generation_service=(serving_runtime.generation_service if serving_runtime else None),
            answer_workflow=(serving_runtime.answer_workflow if serving_runtime else None),
            knowledge_base_service=(
                build_runtime.knowledge_base_service if build_runtime else None
            ),
        )

    @staticmethod
    def _resolve_neo4j_manager(
        *,
        build_runtime: BuildRuntime | None,
        serving_runtime: ServingRuntime | None,
    ) -> Neo4jManagerPort | None:
        if serving_runtime:
            return serving_runtime.neo4j_manager
        if build_runtime:
            return build_runtime.neo4j_manager
        return None

    @staticmethod
    def _resolve_data_module(
        *,
        build_runtime: BuildRuntime | None,
        serving_runtime: ServingRuntime | None,
    ) -> GraphDataModulePort | None:
        if serving_runtime and serving_runtime.data_module:
            return serving_runtime.data_module
        if build_runtime:
            return build_runtime.data_module
        return None

    @staticmethod
    def _resolve_index_module(
        *,
        build_runtime: BuildRuntime | None,
        serving_runtime: ServingRuntime | None,
    ) -> VectorIndexModulePort | None:
        if serving_runtime and serving_runtime.index_module:
            return serving_runtime.index_module
        if build_runtime:
            return build_runtime.index_module
        return None


__all__ = ["SystemRuntimeViewBuilder"]
