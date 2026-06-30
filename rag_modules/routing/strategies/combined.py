"""Combined graph and hybrid route execution strategy."""

from __future__ import annotations

import threading
import time
from concurrent.futures import Executor, ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from typing import List

from ...contracts import EvidenceDocument
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

_DEFAULT_BRANCH_TIMEOUT_SECONDS = 5.0
_MIN_BRANCH_TIMEOUT_SECONDS = 0.001
_BRANCH_TIMEOUT_METADATA_KEYS = (
    "combined_branch_timeout_seconds",
    "route_branch_timeout_seconds",
    "retrieval_branch_timeout_seconds",
    "request_budget_seconds",
)
_MISSING_RESULT = object()


class CombinedRouteStrategy:
    """Combined graph and hybrid retrieval execution."""

    strategy = SearchStrategy.COMBINED

    def __init__(
        self,
        *,
        executor: Executor | None = None,
        max_workers: int | None = None,
        thread_name_prefix: str = "combined-route",
        branch_timeout_seconds: float | None = _DEFAULT_BRANCH_TIMEOUT_SECONDS,
    ) -> None:
        self._executor = executor
        self._executor_lock = threading.Lock()
        self._owns_executor = executor is None
        self._max_workers = max_workers
        self._thread_name_prefix = thread_name_prefix
        self._branch_timeout_seconds = _coerce_branch_timeout_seconds(
            branch_timeout_seconds,
            default=_DEFAULT_BRANCH_TIMEOUT_SECONDS,
        )

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
        branch_futures = {
            "traditional": traditional_future,
            "graph": graph_future,
        }
        branch_timeout_seconds = self._resolve_branch_timeout_seconds(request)
        deadline = time.perf_counter() + branch_timeout_seconds
        branch_results: dict[str, object] = {}
        timed_out_branches: List[str] = []

        for branch_name, future in branch_futures.items():
            try:
                branch_results[branch_name] = future.result(
                    timeout=_remaining_timeout_seconds(deadline)
                )
            except FutureTimeoutError:
                timed_out_branches.append(branch_name)

        for branch_name in list(timed_out_branches):
            future = branch_futures[branch_name]
            if not _future_done(future):
                continue
            branch_results[branch_name] = future.result(timeout=0)
            timed_out_branches.remove(branch_name)

        cancelled_branches = []
        for branch_name in timed_out_branches:
            if _cancel_future(branch_futures[branch_name]):
                cancelled_branches.append(branch_name)

        traditional_result = branch_results.get("traditional", _MISSING_RESULT)
        graph_result = branch_results.get("graph", _MISSING_RESULT)
        traditional_outcome = None
        traditional_latency_ms = None
        traditional_docs: List[EvidenceDocument] = []
        if traditional_result is not _MISSING_RESULT:
            traditional_outcome, traditional_latency_ms = traditional_result
            traditional_docs = list(traditional_outcome.documents)

        graph_trace = None
        graph_latency_ms = None
        graph_docs: List[EvidenceDocument] = []
        if graph_result is not _MISSING_RESULT:
            raw_graph_docs, graph_trace, graph_latency_ms = graph_result
            graph_docs = services.traditional_retrieval.enrich_to_parent_evidence_documents(
                raw_graph_docs,
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
                "branch_timeout_seconds": branch_timeout_seconds,
                "timed_out_branches": timed_out_branches,
                "cancel_requested_branches": timed_out_branches,
                "cancelled_branches": cancelled_branches,
                "traditional_timed_out": "traditional" in timed_out_branches,
                "graph_timed_out": "graph" in timed_out_branches,
            }
        )
        if traditional_outcome is not None:
            details.update(coerce_json_object(traditional_outcome.to_stage_details()))
        if graph_trace:
            details.update(_trace_stage_details(graph_trace))

        return RouteExecutionOutcome(
            documents=list(combined_docs),
            fallbacks=_timeout_fallbacks(
                timed_out_branches=timed_out_branches,
                has_traditional_result=traditional_result is not _MISSING_RESULT,
                has_graph_result=graph_result is not _MISSING_RESULT,
            ),
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

    def _resolve_branch_timeout_seconds(self, request: RouteExecutionRequestPort) -> float:
        metadata_timeout_seconds = _metadata_branch_timeout_seconds(
            request,
            default=self._branch_timeout_seconds,
        )
        return (
            self._branch_timeout_seconds
            if metadata_timeout_seconds is None
            else metadata_timeout_seconds
        )

    def close(self) -> None:
        if not self._owns_executor:
            return
        with self._executor_lock:
            executor = self._executor
            self._executor = None
        if executor is not None:
            executor.shutdown(wait=False, cancel_futures=True)


def _coerce_branch_timeout_seconds(value: object, *, default: float) -> float:
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        seconds = float(default)
    if seconds <= 0:
        seconds = float(default)
    return max(_MIN_BRANCH_TIMEOUT_SECONDS, seconds)


def _remaining_timeout_seconds(deadline: float) -> float:
    return max(0.0, deadline - time.perf_counter())


def _future_done(future: object) -> bool:
    done = getattr(future, "done", None)
    return bool(done()) if callable(done) else False


def _cancel_future(future: object) -> bool:
    cancel = getattr(future, "cancel", None)
    return bool(cancel()) if callable(cancel) else False


def _timeout_fallbacks(
    *,
    timed_out_branches: List[str],
    has_traditional_result: bool,
    has_graph_result: bool,
) -> List[str]:
    timed_out = set(timed_out_branches)
    if timed_out == {"traditional", "graph"}:
        return ["combined_branches_timeout"]
    if "graph" in timed_out and has_traditional_result:
        return ["combined_graph_timeout_to_hybrid"]
    if "traditional" in timed_out and has_graph_result:
        return ["combined_hybrid_timeout_to_graph"]
    if timed_out:
        return ["combined_branch_timeout"]
    return []


def _metadata_branch_timeout_seconds(
    request: RouteExecutionRequestPort,
    *,
    default: float,
) -> float | None:
    retrieval_request = getattr(request, "retrieval_request", None)
    metadata = getattr(retrieval_request, "metadata", None)
    if not isinstance(metadata, dict):
        return None
    for key in _BRANCH_TIMEOUT_METADATA_KEYS:
        if key in metadata:
            return _coerce_branch_timeout_seconds(metadata[key], default=default)
    return None


__all__ = ["CombinedRouteStrategy"]
