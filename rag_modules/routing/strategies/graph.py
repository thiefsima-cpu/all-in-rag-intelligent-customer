"""Graph route execution strategy."""

from __future__ import annotations

import time
from typing import List

from ...runtime import GraphRetrievalSnapshot, SearchStrategy
from ...runtime.json_types import coerce_json_object
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
        fallbacks: List[str] = []

        graph_start = time.perf_counter()
        if hasattr(services.graph_rag_retrieval, "graph_rag_evidence_search_with_trace"):
            graph_documents, graph_trace = (
                services.graph_rag_retrieval.graph_rag_evidence_search_with_trace(
                    request.query,
                    request.top_k,
                    constraints=request.constraints,
                    query_plan=request.query_plan,
                )
            )
        else:
            graph_documents = services.graph_rag_retrieval.graph_rag_evidence_search(
                request.query,
                request.top_k,
                constraints=request.constraints,
                query_plan=request.query_plan,
            )
            graph_trace = GraphRetrievalSnapshot(
                query=request.query,
                requested_top_k=request.top_k,
                doc_count=len(graph_documents),
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
            graph_documents,
            top_n=request.top_k,
        )

        if not documents:
            fallback_start = time.perf_counter()
            fallback_outcome = services.traditional_retrieval.hybrid_evidence_search(
                request.retrieval_request
            )
            fallback_documents = list(fallback_outcome.documents)
            fallbacks.append("graph_empty_to_hybrid")
            stages.append(
                RouteExecutionStageResult(
                    name="hybrid_fallback",
                    documents=fallback_documents,
                    latency_ms=_elapsed_ms(fallback_start),
                    details=coerce_json_object(fallback_outcome.to_stage_details()),
                )
            )
            return RouteExecutionOutcome(
                documents=fallback_documents,
                stages=stages,
                fallbacks=fallbacks,
            )

        if len(documents) < request.top_k:
            supplement_k = services.retrieval_profile.candidates.graph_supplement_candidate_k(
                request.top_k
            )
            supplement_start = time.perf_counter()
            supplement_outcome = services.traditional_retrieval.hybrid_evidence_search(
                build_route_retrieval_request(
                    query=request.query,
                    top_k=supplement_k,
                    candidate_k=supplement_k,
                    constraints=request.constraints,
                    query_plan=request.query_plan,
                )
            )
            supplement_docs = list(supplement_outcome.documents)
            fallbacks.append("graph_insufficient_hybrid_supplement")
            stages.append(
                RouteExecutionStageResult(
                    name="hybrid_supplement",
                    documents=supplement_docs,
                    latency_ms=_elapsed_ms(supplement_start),
                    details=coerce_json_object(supplement_outcome.to_stage_details()),
                )
            )
            documents = merge_route_documents(
                documents,
                supplement_docs,
                limit=supplement_k,
            )

        return RouteExecutionOutcome(
            documents=list(documents),
            stages=stages,
            fallbacks=fallbacks,
        )


__all__ = ["GraphRouteStrategy"]
