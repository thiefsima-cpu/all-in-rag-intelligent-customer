"""Hybrid route execution strategy."""

from __future__ import annotations

import time

from ...runtime import SearchStrategy
from ...runtime.json_types import coerce_json_object
from .base import (
    RouteExecutionOutcome,
    RouteExecutionRequestPort,
    RouteExecutionStageResult,
    RouteRetrievalServices,
    _elapsed_ms,
)


class HybridRouteStrategy:
    """Pure hybrid retrieval execution."""

    strategy = SearchStrategy.HYBRID_TRADITIONAL

    def execute(
        self,
        request: RouteExecutionRequestPort,
        *,
        services: RouteRetrievalServices,
    ) -> RouteExecutionOutcome:
        start = time.perf_counter()
        outcome = services.traditional_retrieval.hybrid_evidence_search(request.retrieval_request)
        documents = list(outcome.documents)
        return RouteExecutionOutcome(
            documents=documents,
            stages=[
                RouteExecutionStageResult(
                    name="hybrid",
                    documents=documents,
                    latency_ms=_elapsed_ms(start),
                    details=coerce_json_object(outcome.to_stage_details()),
                )
            ],
        )


__all__ = ["HybridRouteStrategy"]
