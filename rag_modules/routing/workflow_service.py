"""Canonical routing workflow service."""

from __future__ import annotations

import logging
import time
from typing import List, Optional

from ..domain.shared.query_constraints import QueryConstraints
from ..query_understanding.service import QueryUnderstandingService
from ..retrieval.contracts import EvidenceDocument
from ..retrieval.post_processor import RetrievalPostProcessor
from ..retrieval.runtime_profile import RetrievalRuntimeProfile
from ..runtime import (
    QueryAnalysis,
    QueryUnderstandingSnapshot,
    RetrievalOutcome,
    RouteResolution,
    RouteSnapshot,
)
from ..runtime.json_types import JsonObject
from .search_orchestrator import RouteExecutionRequest, RouteSearchOrchestrator
from .statistics import RouteStatisticsTracker
from .trace_recorder import RouteTraceRecorder

logger = logging.getLogger(__name__)


class RoutingWorkflowService:
    """Canonical routing workflow that owns planning, execution, and tracing."""

    def __init__(
        self,
        *,
        traditional_retrieval,
        graph_rag_retrieval,
        llm_client,
        config,
        retrieval_profile: Optional[RetrievalRuntimeProfile] = None,
        query_understanding_service: Optional[QueryUnderstandingService] = None,
        post_processor: Optional[RetrievalPostProcessor] = None,
        route_stats: Optional[RouteStatisticsTracker] = None,
        search_orchestrator: Optional[RouteSearchOrchestrator] = None,
    ) -> None:
        self.traditional_retrieval = traditional_retrieval
        self.graph_rag_retrieval = graph_rag_retrieval
        self.llm_client = llm_client
        self.config = config
        self.retrieval_profile = retrieval_profile or RetrievalRuntimeProfile.from_config(config)
        if query_understanding_service is None:
            query_understanding_service = QueryUnderstandingService(
                llm_client=llm_client,
                config=config,
                retrieval_profile=self.retrieval_profile,
            )
        self.query_understanding_service = query_understanding_service
        self.query_planner = self.query_understanding_service.query_planner
        self.post_processor = post_processor or RetrievalPostProcessor(
            config,
            settings=self.retrieval_profile.postprocess,
        )
        self.route_stats = route_stats or RouteStatisticsTracker()
        self.search_orchestrator = search_orchestrator or RouteSearchOrchestrator(
            traditional_retrieval=traditional_retrieval,
            graph_rag_retrieval=graph_rag_retrieval,
            retrieval_profile=self.retrieval_profile,
            post_processor=self.post_processor,
        )

    def analyze_query(self, query: str) -> QueryAnalysis:
        return self.query_understanding_service.analyze(query)

    def understand_query(self, query: str) -> QueryUnderstandingSnapshot:
        return self.query_understanding_service.understand(query)

    def explain_routing_decision(self, query: str) -> str:
        return self.query_understanding_service.explain(query)

    def route(self, query: str, top_k: int = 5) -> RouteResolution:
        resolution, _trace = self.route_with_trace(query, top_k)
        return resolution

    def route_with_trace(
        self,
        query: str,
        top_k: int = 5,
    ) -> tuple[RouteResolution, RouteSnapshot]:
        logger.info("Routing query: %s", query)
        route_start = time.perf_counter()
        trace = RouteTraceRecorder(query=query, requested_top_k=top_k)

        understanding, execution_request = self._build_execution_request(
            query=query,
            top_k=top_k,
            trace=trace,
        )
        query_plan_payload = understanding.query_plan.to_dict()

        try:
            evidence_documents = self.search_orchestrator.execute(
                execution_request,
                trace=trace,
            )
            evidence_documents = self.search_orchestrator.post_process(
                execution_request,
                evidence_documents,
                trace=trace,
                query_plan_payload=query_plan_payload,
            )
            route_trace = trace.finalize(
                total_start_time=route_start,
                final_doc_count=len(evidence_documents),
            )
            resolution = self._build_resolution(
                understanding=understanding,
                query=query,
                strategy=execution_request.analysis.strategy_name,
                evidence_documents=evidence_documents,
                route_trace=route_trace,
            )
            return resolution, RouteSnapshot.from_dict(route_trace.to_dict())
        except Exception as exc:
            evidence_documents = self.search_orchestrator.execute_exception_fallback(
                execution_request,
                trace=trace,
                error=exc,
            )
            route_trace = trace.finalize(
                total_start_time=route_start,
                final_doc_count=len(evidence_documents),
                error=str(exc),
            )
            resolution = self._build_resolution(
                understanding=understanding,
                query=query,
                strategy=execution_request.analysis.strategy_name,
                evidence_documents=evidence_documents,
                route_trace=route_trace,
                metadata={"error": str(exc)},
            )
            return resolution, RouteSnapshot.from_dict(route_trace.to_dict())

    def get_route_statistics(self) -> JsonObject:
        return self.route_stats.summary()

    def close(self) -> None:
        close = getattr(self.search_orchestrator, "close", None)
        if callable(close):
            close()

    def _build_execution_request(
        self,
        *,
        query: str,
        top_k: int,
        trace: RouteTraceRecorder,
    ) -> tuple[QueryUnderstandingSnapshot, RouteExecutionRequest]:
        plan_start = time.perf_counter()
        understanding = self.query_understanding_service.understand(query)
        plan = understanding.query_plan
        analysis = understanding.analysis
        trace.record_plan(plan, start_time=plan_start)
        self.route_stats.record(analysis.recommended_strategy)
        trace.set_strategy(analysis.strategy_name)
        retrieval_request = self.search_orchestrator.build_retrieval_request(
            query=query,
            top_k=top_k,
            constraints=understanding.constraints,
            query_plan=plan,
            strategy=analysis.strategy_name,
        )
        trace.set_retrieval_request(retrieval_request)
        return understanding, RouteExecutionRequest(
            query=query,
            top_k=top_k,
            analysis=analysis,
            retrieval_request=retrieval_request,
            constraints=understanding.constraints or QueryConstraints(),
            query_plan=plan,
        )

    def _build_resolution(
        self,
        *,
        understanding: QueryUnderstandingSnapshot,
        query: str,
        strategy: str,
        evidence_documents: List[EvidenceDocument],
        route_trace: RouteSnapshot,
        metadata: JsonObject | None = None,
    ) -> RouteResolution:
        return RouteResolution(
            understanding=understanding,
            retrieval=self._build_retrieval_outcome(
                understanding=understanding,
                query=query,
                strategy=strategy,
                evidence_documents=evidence_documents,
                route_trace=route_trace,
            ),
            metadata={
                "route_trace": route_trace.to_dict(),
                **dict(metadata or {}),
            },
        )

    def _build_retrieval_outcome(
        self,
        *,
        understanding: QueryUnderstandingSnapshot,
        query: str,
        strategy: str,
        evidence_documents: List[EvidenceDocument],
        route_trace: RouteSnapshot,
    ) -> RetrievalOutcome:
        return RetrievalOutcome(
            query=query,
            strategy=strategy,
            evidence_documents=list(evidence_documents or []),
            route_trace=RouteSnapshot.from_dict(route_trace.to_dict()),
            metadata={
                "query_understanding": understanding.to_dict(),
                "analysis": understanding.analysis.to_dict(),
                "route_stats": self.route_stats.to_dict(),
                "retrieval_runtime_profile": self.retrieval_profile.to_dict(),
            },
        )


__all__ = ["RoutingWorkflowService"]
