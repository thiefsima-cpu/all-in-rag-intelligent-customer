"""Runtime shutdown orchestration for app-facing lifecycle management."""

from __future__ import annotations

from typing import Any

from ..runtime_view import SystemRuntime


class RuntimeShutdownService:
    """Close runtime resources through grouped runtime views."""

    def close(self, *, runtime: SystemRuntime) -> None:
        serving_runtime = runtime.serving_runtime
        if serving_runtime is not None:
            self._close_if_present(runtime.infrastructure.query_tracer)
            self._close_if_present(getattr(runtime.retrieval, "routing_workflow", None))
            self._close_if_present(runtime.retrieval.traditional_retrieval)
            self._close_if_present(runtime.retrieval.graph_rag_retrieval)
            serving_runtime.retrieval_engines_initialized = False

        knowledge_base_service = runtime.services.knowledge_base_service
        if knowledge_base_service is not None:
            self._close_if_present(knowledge_base_service)
            return

        self._close_if_present(runtime.infrastructure.neo4j_manager)

    @staticmethod
    def _close_if_present(resource: Any) -> None:
        if resource is not None and hasattr(resource, "close"):
            resource.close()


__all__ = ["RuntimeShutdownService"]
