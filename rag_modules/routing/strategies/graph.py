"""Graph route execution strategy."""

from __future__ import annotations

import time
from typing import List

from ...contracts import EvidenceDocument, RetrievalRequest
from ...kernel.json_types import coerce_json_object
from ...kernel.routing import SearchStrategy
from .base import (
    RouteExecutionOutcome,
    RouteExecutionRequestPort,
    RouteExecutionStageResult,
    RouteRetrievalServices,
    _elapsed_ms,
    build_route_retrieval_request,
    merge_route_documents,
)


class GraphRouteStrategy:
    """Graph-first retrieval with hybrid supplement and fallback behavior."""

    strategy = SearchStrategy.GRAPH_RAG

    def execute(
        self,
        request: RouteExecutionRequestPort,
        *,
        services: RouteRetrievalServices,
    ) -> RouteExecutionOutcome:
        stages: List[RouteExecutionStageResult] = []
        _graph_request, documents = self._run_graph_stage(request, services, stages)
        if not documents:
            return self._hybrid_fallback(request, services, stages)
        if len(documents) < request.top_k:
            documents = self._supplement_documents(request, services, documents, stages)
        return RouteExecutionOutcome(
            documents=list(documents),
            stages=stages,
            fallbacks=[],
        )

    def _run_graph_stage(
        self,
        request: RouteExecutionRequestPort,
        services: RouteRetrievalServices,
        stages: List[RouteExecutionStageResult],
    ) -> tuple[RetrievalRequest, List[EvidenceDocument]]:
        graph_start = time.perf_counter()
        graph_request = request.retrieval_request.copy_with(
            top_k=request.top_k,
            candidate_k=request.top_k,
            strategy=SearchStrategy.GRAPH_RAG.value,
        )
        if graph_request.control is not None:
            graph_request.control.raise_if_cancelled()
        graph_documents, graph_trace = (
            services.graph_rag_retrieval.graph_rag_evidence_search_with_trace(graph_request)
        )
        stages.append(
            RouteExecutionStageResult(
                name="graph_rag",
                documents=list(graph_documents),
                latency_ms=_elapsed_ms(graph_start),
                extra=graph_trace,
            )
        )
        documents = services.traditional_retrieval.enrich_to_parent_evidence_documents(
            graph_request,
            graph_documents,
            top_n=request.top_k,
        )
        return graph_request, list(documents)

    def _hybrid_fallback(
        self,
        request: RouteExecutionRequestPort,
        services: RouteRetrievalServices,
        stages: List[RouteExecutionStageResult],
    ) -> RouteExecutionOutcome:
        fallback_start = time.perf_counter()
        outcome = services.traditional_retrieval.hybrid_evidence_search(request.retrieval_request)
        documents = list(outcome.documents)
        stages.append(
            RouteExecutionStageResult(
                name="hybrid_fallback",
                documents=documents,
                latency_ms=_elapsed_ms(fallback_start),
                details=coerce_json_object(outcome.to_stage_details()),
            )
        )
        return RouteExecutionOutcome(
            documents=documents,
            stages=stages,
            fallbacks=["graph_empty_to_hybrid"],
        )

    def _supplement_documents(
        self,
        request: RouteExecutionRequestPort,
        services: RouteRetrievalServices,
        documents: List[EvidenceDocument],
        stages: List[RouteExecutionStageResult],
    ) -> List[EvidenceDocument]:
        supplement_k = services.retrieval_profile.candidates.graph_supplement_candidate_k(
            request.top_k
        )
        supplement_start = time.perf_counter()
        outcome = services.traditional_retrieval.hybrid_evidence_search(
            build_route_retrieval_request(
                query=request.query,
                top_k=supplement_k,
                candidate_k=supplement_k,
                constraints=request.constraints,
                query_plan=request.query_plan,
                control=request.retrieval_request.control,
            )
        )
        supplement_docs = list(outcome.documents)
        stages.append(
            RouteExecutionStageResult(
                name="hybrid_supplement",
                documents=supplement_docs,
                latency_ms=_elapsed_ms(supplement_start),
                details=coerce_json_object(outcome.to_stage_details()),
            )
        )
        return merge_route_documents(documents, supplement_docs, limit=supplement_k)


__all__ = ["GraphRouteStrategy"]
