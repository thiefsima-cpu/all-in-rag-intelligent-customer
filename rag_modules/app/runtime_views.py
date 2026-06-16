"""Grouped runtime view dataclasses exposed by the application runtime surface."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class SystemInfrastructureView:
    """Infrastructure-facing runtime dependencies."""

    query_tracer: Any = None
    neo4j_manager: Any = None
    data_module: Any = None
    index_module: Any = None


@dataclass(frozen=True)
class SystemRetrievalView:
    """Retrieval and routing-facing runtime dependencies."""

    retrieval_runtime_profile: Any = None
    query_understanding_service: Any = None
    traditional_retrieval: Any = None
    graph_rag_retrieval: Any = None
    routing_workflow: Any = None


@dataclass(frozen=True)
class SystemServicesView:
    """Application service-facing runtime dependencies."""

    generation_service: Any = None
    answer_workflow: Any = None
    question_answer_service: Any = None
    knowledge_base_service: Any = None


__all__ = [
    "SystemInfrastructureView",
    "SystemRetrievalView",
    "SystemServicesView",
]
