"""Combined graph and hybrid route execution strategy."""

from __future__ import annotations

import threading
import time
from concurrent.futures import Executor, ThreadPoolExecutor
from typing import List

from ...retrieval.contracts import EvidenceDocument
from ...retrieval.hybrid_outcome import HybridRetrievalOutcome
from ...runtime import GraphRetrievalSnapshot, SearchStrategy
from ...runtime.json_types import coerce_json_object
from .base import (
    RouteExecutionOutcome,
    RouteExecutionRequestPort,
    RouteExecutionStageResult,
    RouteRetrievalServices,
    _elapsed_ms,
    _trace_stage_details,
    build_route_retrieval_request,
    interleave_route_documents,
)


class CombinedRouteStrategy:
    """Combined graph and hybrid retrieval execution."""

    strategy = SearchStrategy.COMBINED

    def __init__(
        self,
        *,
        executor: Executor | None = None,
        max_workers: int | None = None,
        thread_name_prefix: str = "combined-route",
    ) -> None:
        self._executor = executor
        self._executor_lock = threading.Lock()
        self._owns_executor = executor is None
        self._max_workers = max_workers
        self._thread_name_prefix = thread_name_prefix

    def execute(
        self,
        request: RouteExecutionRequestPort,
        *,
        services: RouteRetrievalServices,
    ) -> RouteExecutionOutcome:
        start = time.perf_counter()
        candidate_k = services.retrieval_profile.candidates.combined_candidate_k(request.top_k)
        traditional_request = build_route_retrieval_request(
            query=request.query,
            top_k=candidate_k,
            candidate_k=candidate_k,
            constraints=request.constraints,
            query_plan=request.query_plan,
            strategy=SearchStrategy.COMBINED.value,
        )

        def load_traditional() -> tuple[HybridRetrievalOutcome, float]:
            traditional_start = time.perf_counter()
            outcome = services.traditional_retrieval.hybrid_evidence_search(traditional_request)
            return outcome, _elapsed_ms(traditional_start)

        def load_graph() -> tuple[List[EvidenceDocument], object, float]:
            graph_start = time.perf_counter()
            if hasattr(services.graph_rag_retrieval, "graph_rag_evidence_search_with_trace"):
                docs, trace = services.graph_rag_retrieval.graph_rag_evidence_search_with_trace(
                    request.query,
                    candidate_k,
                    constraints=request.constraints,
                    query_plan=request.query_plan,
                )
            else:
                docs = services.graph_rag_retrieval.graph_rag_evidence_search(
                    request.query,
                    candidate_k,
                    constraints=request.constraints,
                    query_plan=request.query_plan,
                )
                trace = GraphRetrievalSnapshot(
                    query=request.query,
                    requested_top_k=candidate_k,
                    doc_count=len(docs),
                )
            return list(docs), trace, _elapsed_ms(graph_start)

        executor = self._resolve_executor()
        traditional_future = executor.submit(load_traditional)
        graph_future = executor.submit(load_graph)
        traditional_outcome, traditional_latency_ms = traditional_future.result()
        graph_docs, graph_trace, graph_latency_ms = graph_future.result()

        traditional_docs = list(traditional_outcome.documents)
        graph_docs = services.traditional_retrieval.enrich_to_parent_evidence_documents(
            graph_docs,
            top_n=candidate_k,
        )
        combined_docs = interleave_route_documents(
            graph_docs,
            traditional_docs,
            limit=candidate_k,
        )

        details = coerce_json_object(
            {
                "candidate_k": candidate_k,
                "traditional_doc_count": len(traditional_docs),
                "graph_doc_count": len(graph_docs),
                "traditional_latency_ms": traditional_latency_ms,
                "graph_latency_ms": graph_latency_ms,
                "parallel_execution": True,
            }
        )
        details.update(coerce_json_object(traditional_outcome.to_stage_details()))
        if graph_trace:
            details.update(_trace_stage_details(graph_trace))

        return RouteExecutionOutcome(
            documents=list(combined_docs),
            stages=[
                RouteExecutionStageResult(
                    name="combined",
                    documents=list(combined_docs),
                    latency_ms=_elapsed_ms(start),
                    details=details,
                )
            ],
        )

    def _resolve_executor(self) -> Executor:
        executor = self._executor
        if executor is not None:
            return executor
        with self._executor_lock:
            executor = self._executor
            if executor is None:
                if self._max_workers is None:
                    executor = ThreadPoolExecutor(thread_name_prefix=self._thread_name_prefix)
                else:
                    executor = ThreadPoolExecutor(
                        max_workers=self._max_workers,
                        thread_name_prefix=self._thread_name_prefix,
                    )
                self._executor = executor
        return executor

    def close(self) -> None:
        if not self._owns_executor:
            return
        with self._executor_lock:
            executor = self._executor
            self._executor = None
        if executor is not None:
            executor.shutdown(wait=False, cancel_futures=True)


__all__ = ["CombinedRouteStrategy"]
