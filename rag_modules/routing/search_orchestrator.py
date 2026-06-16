"""Retrieval orchestration facade over route execution strategies and post-process flow."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import List, Optional

from ..query_constraints import QueryConstraints
from ..query_understanding import QueryPlan
from ..retrieval.contracts import EvidenceDocument, RetrievalRequest
from ..retrieval.runtime_profile import RetrievalRuntimeProfile
from ..retrieval_post_processor import RetrievalPostProcessContext, RetrievalPostProcessor
from ..runtime import QueryAnalysis, SearchStrategy
from .execution_strategies import (
    CombinedRouteStrategy,
    GraphRouteStrategy,
    HybridRouteStrategy,
    RouteExecutionOutcome,
    RouteExecutionStageResult,
    RouteRetrievalServices,
    RouteRetrievalStrategy,
    build_route_retrieval_request,
    merge_route_documents,
)
from .trace_recorder import RouteTraceRecorder

logger = logging.getLogger(__name__)


@dataclass
class RouteExecutionRequest:
    query: str
    top_k: int
    analysis: QueryAnalysis
    retrieval_request: RetrievalRequest
    constraints: QueryConstraints
    query_plan: Optional[QueryPlan] = None


class RouteSearchOrchestrator:
    """Facade over route-specific retrieval execution strategies and post-processing."""

    def __init__(
        self,
        *,
        traditional_retrieval,
        graph_rag_retrieval,
        retrieval_profile: RetrievalRuntimeProfile,
        post_processor: RetrievalPostProcessor,
        strategies: Optional[List[RouteRetrievalStrategy]] = None,
    ) -> None:
        self.traditional_retrieval = traditional_retrieval
        self.graph_rag_retrieval = graph_rag_retrieval
        self.retrieval_profile = retrieval_profile
        self.post_processor = post_processor
        self.services = RouteRetrievalServices(
            traditional_retrieval=traditional_retrieval,
            graph_rag_retrieval=graph_rag_retrieval,
            retrieval_profile=retrieval_profile,
        )
        strategy_list = strategies or [
            HybridRouteStrategy(),
            GraphRouteStrategy(),
            CombinedRouteStrategy(),
        ]
        self.strategy_registry = {
            strategy.strategy: strategy
            for strategy in strategy_list
        }

    def execute(self, request: RouteExecutionRequest, *, trace: RouteTraceRecorder) -> List[EvidenceDocument]:
        strategy = self.strategy_registry.get(request.analysis.recommended_strategy)
        if strategy is None:
            logger.warning(
                "Unknown route strategy %s; falling back to hybrid strategy.",
                request.analysis.recommended_strategy,
            )
            strategy = self.strategy_registry.get(SearchStrategy.HYBRID_TRADITIONAL)
            if strategy is None:
                strategy = next(iter(self.strategy_registry.values()))
        outcome = strategy.execute(
            request,
            services=self.services,
        )
        trace.record_execution_outcome(outcome)
        return outcome.documents

    def post_process(
        self,
        request: RouteExecutionRequest,
        evidence_documents: List[EvidenceDocument],
        *,
        trace: RouteTraceRecorder,
        query_plan_payload: Optional[dict] = None,
    ) -> List[EvidenceDocument]:
        post_start = time.perf_counter()
        processed_documents = self.post_processor.post_process(
            evidence_documents,
            top_k=request.top_k,
            context=RetrievalPostProcessContext(
                query=request.query,
                strategy=request.analysis.strategy_name,
                query_complexity=request.analysis.query_complexity,
                relationship_intensity=request.analysis.relationship_intensity,
                route_confidence=request.analysis.confidence,
                query_plan=query_plan_payload or {},
            ),
        )
        trace.add_stage("post_process", start_time=post_start, documents=processed_documents)
        return processed_documents

    def execute_exception_fallback(
        self,
        request: RouteExecutionRequest,
        *,
        trace: RouteTraceRecorder,
        error: Exception,
    ) -> List[EvidenceDocument]:
        logger.error("Query routing failed, falling back to hybrid search: %s", error)
        outcome = self._build_exception_fallback_outcome(request)
        trace.record_execution_outcome(outcome)
        return outcome.documents

    @staticmethod
    def build_retrieval_request(
        *,
        query: str,
        top_k: int,
        constraints: Optional[QueryConstraints] = None,
        candidate_k: Optional[int] = None,
        query_plan: Optional[QueryPlan] = None,
        strategy: str = "",
    ) -> RetrievalRequest:
        return build_route_retrieval_request(
            query=query,
            top_k=top_k,
            constraints=constraints,
            candidate_k=candidate_k,
            query_plan=query_plan,
            strategy=strategy,
        )

    @staticmethod
    def merge_documents(
        primary_docs: List[EvidenceDocument],
        secondary_docs: List[EvidenceDocument],
        *,
        limit: int,
    ) -> List[EvidenceDocument]:
        return merge_route_documents(
            primary_docs,
            secondary_docs,
            limit=limit,
        )

    def _build_exception_fallback_outcome(
        self,
        request: RouteExecutionRequest,
    ) -> RouteExecutionOutcome:
        start = time.perf_counter()
        evidence_documents = self.traditional_retrieval.hybrid_evidence_search(
            request.retrieval_request
        )
        return RouteExecutionOutcome(
            documents=list(evidence_documents),
            fallbacks=["router_exception_to_hybrid"],
            stages=[
                RouteExecutionStageResult(
                    name="hybrid_exception_fallback",
                    documents=list(evidence_documents),
                    latency_ms=round((time.perf_counter() - start) * 1000, 2),
                )
            ],
        )


__all__ = ["RouteExecutionRequest", "RouteSearchOrchestrator"]
