"""Combined graph and hybrid route execution strategy."""

from __future__ import annotations

import threading
import time
from concurrent.futures import Executor, Future, ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from dataclasses import dataclass
from typing import Any, List, Literal, Sequence, TypeAlias, cast

from ...contracts import EvidenceDocument, RequestControl, RetrievalRequest
from ...contracts.runtime.retrieval import HybridRetrievalOutcome
from ...kernel.json_types import coerce_json_object
from ...kernel.routing import SearchStrategy
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
_CANCEL_OBSERVE_GRACE_SECONDS = 0.05
_BRANCH_TIMEOUT_METADATA_KEYS = (
    "combined_branch_timeout_seconds",
    "route_branch_timeout_seconds",
    "retrieval_branch_timeout_seconds",
    "request_budget_seconds",
)

_BranchName: TypeAlias = Literal["traditional", "graph"]


@dataclass(frozen=True)
class _TraditionalBranchResult:
    outcome: HybridRetrievalOutcome
    latency_ms: float


@dataclass(frozen=True)
class _GraphBranchResult:
    documents: List[EvidenceDocument]
    trace: object
    latency_ms: float


_BranchResult: TypeAlias = _TraditionalBranchResult | _GraphBranchResult


@dataclass(frozen=True)
class _CombinedRouteRun:
    candidate_k: int
    branch_timeout_seconds: float
    traditional_request: RetrievalRequest
    graph_request: RetrievalRequest
    branch_controls: dict[_BranchName, RequestControl]


@dataclass(frozen=True)
class _BranchExecutionState:
    results: dict[_BranchName, _BranchResult]
    timed_out_branches: List[_BranchName]
    cancel_observed_branches: List[_BranchName]


@dataclass(frozen=True)
class _CombinedBranchDocuments:
    combined_docs: List[EvidenceDocument]
    traditional_outcome: HybridRetrievalOutcome | None
    graph_trace: object | None
    traditional_docs: List[EvidenceDocument]
    graph_docs: List[EvidenceDocument]
    traditional_latency_ms: float | None
    graph_latency_ms: float | None


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
        run = self._prepare_run(request, services=services)
        branch_execution = self._execute_branches(run, services=services)
        documents = self._combine_branch_documents(run, branch_execution, services=services)
        details = _combined_stage_details(run, branch_execution, documents)

        return RouteExecutionOutcome(
            documents=list(documents.combined_docs),
            fallbacks=_timeout_fallbacks(
                timed_out_branches=branch_execution.timed_out_branches,
                has_traditional_result=_has_branch_result(
                    branch_execution,
                    branch_name="traditional",
                    result_type=_TraditionalBranchResult,
                ),
                has_graph_result=_has_branch_result(
                    branch_execution,
                    branch_name="graph",
                    result_type=_GraphBranchResult,
                ),
            ),
            stages=[
                RouteExecutionStageResult(
                    name="combined",
                    documents=list(documents.combined_docs),
                    latency_ms=_elapsed_ms(start),
                    details=details,
                )
            ],
        )

    def _prepare_run(
        self,
        request: RouteExecutionRequestPort,
        *,
        services: RouteRetrievalServices,
    ) -> _CombinedRouteRun:
        candidate_k = services.retrieval_profile.candidates.combined_candidate_k(request.top_k)
        branch_timeout_seconds = self._resolve_branch_timeout_seconds(request)
        route_control = request.retrieval_request.control
        traditional_control = _branch_control(
            route_control,
            timeout_seconds=branch_timeout_seconds,
            scope="combined.traditional",
        )
        graph_control = _branch_control(
            route_control,
            timeout_seconds=branch_timeout_seconds,
            scope="combined.graph",
        )
        return _CombinedRouteRun(
            candidate_k=candidate_k,
            branch_timeout_seconds=branch_timeout_seconds,
            traditional_request=_build_combined_retrieval_request(
                request,
                candidate_k=candidate_k,
                control=traditional_control,
            ),
            graph_request=_build_combined_retrieval_request(
                request,
                candidate_k=candidate_k,
                control=graph_control,
            ),
            branch_controls={
                "traditional": traditional_control,
                "graph": graph_control,
            },
        )

    def _execute_branches(
        self,
        run: _CombinedRouteRun,
        *,
        services: RouteRetrievalServices,
    ) -> _BranchExecutionState:
        branch_futures = _submit_branch_futures(
            self._resolve_executor(),
            run,
            services=services,
        )
        branch_results, timed_out_branches = _await_branch_results(
            branch_futures,
            timeout_seconds=run.branch_timeout_seconds,
        )
        _accept_ready_timed_out_branches(
            branch_futures,
            branch_results=branch_results,
            timed_out_branches=timed_out_branches,
        )
        _cancel_timed_out_branches(
            branch_futures,
            branch_controls=run.branch_controls,
            timed_out_branches=timed_out_branches,
        )
        return _BranchExecutionState(
            results=branch_results,
            timed_out_branches=timed_out_branches,
            cancel_observed_branches=_observe_cancelled_branches(
                branch_futures,
                timed_out_branches=timed_out_branches,
            ),
        )

    @staticmethod
    def _combine_branch_documents(
        run: _CombinedRouteRun,
        branch_execution: _BranchExecutionState,
        *,
        services: RouteRetrievalServices,
    ) -> _CombinedBranchDocuments:
        traditional_result = branch_execution.results.get("traditional")
        graph_result = branch_execution.results.get("graph")
        traditional_outcome = None
        traditional_latency_ms = None
        traditional_docs: List[EvidenceDocument] = []
        if isinstance(traditional_result, _TraditionalBranchResult):
            traditional_outcome = traditional_result.outcome
            traditional_latency_ms = traditional_result.latency_ms
            traditional_docs = list(traditional_outcome.documents)

        graph_trace = None
        graph_latency_ms = None
        graph_docs: List[EvidenceDocument] = []
        if isinstance(graph_result, _GraphBranchResult):
            graph_trace = graph_result.trace
            graph_latency_ms = graph_result.latency_ms
            graph_docs = services.traditional_retrieval.enrich_to_parent_evidence_documents(
                run.graph_request,
                graph_result.documents,
                top_n=run.candidate_k,
            )
        combined_docs = interleave_route_documents(
            graph_docs,
            traditional_docs,
            limit=run.candidate_k,
        )
        return _CombinedBranchDocuments(
            combined_docs=combined_docs,
            traditional_outcome=traditional_outcome,
            graph_trace=graph_trace,
            traditional_docs=traditional_docs,
            graph_docs=graph_docs,
            traditional_latency_ms=traditional_latency_ms,
            graph_latency_ms=graph_latency_ms,
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


def _build_combined_retrieval_request(
    request: RouteExecutionRequestPort,
    *,
    candidate_k: int,
    control: RequestControl,
) -> RetrievalRequest:
    return build_route_retrieval_request(
        query=request.query,
        top_k=candidate_k,
        candidate_k=candidate_k,
        constraints=request.constraints,
        query_plan=request.query_plan,
        strategy=SearchStrategy.COMBINED.value,
        control=control,
    )


def _submit_branch_futures(
    executor: Executor,
    run: _CombinedRouteRun,
    *,
    services: RouteRetrievalServices,
) -> dict[_BranchName, Future[_BranchResult]]:
    return {
        "traditional": executor.submit(
            _load_traditional_branch,
            services,
            run.traditional_request,
        ),
        "graph": executor.submit(
            _load_graph_branch,
            services,
            run.graph_request,
        ),
    }


def _load_traditional_branch(
    services: RouteRetrievalServices,
    retrieval_request: RetrievalRequest,
) -> _BranchResult:
    traditional_start = time.perf_counter()
    outcome = services.traditional_retrieval.hybrid_evidence_search(retrieval_request)
    return _TraditionalBranchResult(
        outcome=outcome,
        latency_ms=_elapsed_ms(traditional_start),
    )


def _load_graph_branch(
    services: RouteRetrievalServices,
    retrieval_request: RetrievalRequest,
) -> _BranchResult:
    graph_start = time.perf_counter()
    docs, trace = services.graph_rag_retrieval.graph_rag_evidence_search_with_trace(
        retrieval_request
    )
    return _GraphBranchResult(
        documents=list(docs),
        trace=trace,
        latency_ms=_elapsed_ms(graph_start),
    )


def _await_branch_results(
    branch_futures: dict[_BranchName, Future[_BranchResult]],
    *,
    timeout_seconds: float,
) -> tuple[dict[_BranchName, _BranchResult], List[_BranchName]]:
    deadline = time.perf_counter() + timeout_seconds
    branch_results: dict[_BranchName, _BranchResult] = {}
    timed_out_branches: List[_BranchName] = []
    for branch_name, future in branch_futures.items():
        try:
            branch_results[branch_name] = future.result(
                timeout=_remaining_timeout_seconds(deadline)
            )
        except FutureTimeoutError:
            timed_out_branches.append(branch_name)
    return branch_results, timed_out_branches


def _accept_ready_timed_out_branches(
    branch_futures: dict[_BranchName, Future[_BranchResult]],
    *,
    branch_results: dict[_BranchName, _BranchResult],
    timed_out_branches: List[_BranchName],
) -> None:
    for branch_name in list(timed_out_branches):
        future = branch_futures[branch_name]
        if not _future_done(future):
            continue
        branch_results[branch_name] = future.result(timeout=0)
        timed_out_branches.remove(branch_name)


def _cancel_timed_out_branches(
    branch_futures: dict[_BranchName, Future[_BranchResult]],
    *,
    branch_controls: dict[_BranchName, RequestControl],
    timed_out_branches: Sequence[_BranchName],
) -> None:
    for branch_name in timed_out_branches:
        branch_controls[branch_name].cancel("combined_branch_timeout")
        _cancel_future(branch_futures[branch_name])


def _combined_stage_details(
    run: _CombinedRouteRun,
    branch_execution: _BranchExecutionState,
    documents: _CombinedBranchDocuments,
) -> dict[str, Any]:
    details = coerce_json_object(
        {
            "candidate_k": run.candidate_k,
            "traditional_doc_count": len(documents.traditional_docs),
            "graph_doc_count": len(documents.graph_docs),
            "traditional_latency_ms": documents.traditional_latency_ms,
            "graph_latency_ms": documents.graph_latency_ms,
            "parallel_execution": True,
            "branch_timeout_seconds": run.branch_timeout_seconds,
            "timed_out_branches": branch_execution.timed_out_branches,
            "cancel_requested_branches": branch_execution.timed_out_branches,
            "cancel_observed_branches": branch_execution.cancel_observed_branches,
            "traditional_control": run.branch_controls["traditional"].to_trace_details(),
            "graph_control": run.branch_controls["graph"].to_trace_details(),
            "traditional_timed_out": "traditional" in branch_execution.timed_out_branches,
            "graph_timed_out": "graph" in branch_execution.timed_out_branches,
        }
    )
    if documents.traditional_outcome is not None:
        details.update(coerce_json_object(documents.traditional_outcome.to_stage_details()))
    if documents.graph_trace:
        details.update(_trace_stage_details(documents.graph_trace))
    return details


def _has_branch_result(
    branch_execution: _BranchExecutionState,
    *,
    branch_name: _BranchName,
    result_type: type[Any],
) -> bool:
    return isinstance(branch_execution.results.get(branch_name), result_type)


def _coerce_branch_timeout_seconds(value: object, *, default: float) -> float:
    try:
        seconds = float(cast(Any, value))
    except (TypeError, ValueError):
        seconds = float(default)
    if seconds <= 0:
        seconds = float(default)
    return max(_MIN_BRANCH_TIMEOUT_SECONDS, seconds)


def _remaining_timeout_seconds(deadline: float) -> float:
    return max(0.0, deadline - time.perf_counter())


def _future_done(future: Future[_BranchResult]) -> bool:
    return future.done()


def _cancel_future(future: Future[_BranchResult]) -> bool:
    return future.cancel()


def _branch_control(
    route_control: RequestControl | None,
    *,
    timeout_seconds: float,
    scope: str,
) -> RequestControl:
    if route_control is not None:
        return route_control.child(timeout_seconds, scope=scope)
    return RequestControl.for_timeout(timeout_seconds, scope=scope)


def _observe_cancelled_branches(
    branch_futures: dict[_BranchName, Future[_BranchResult]],
    *,
    timed_out_branches: Sequence[_BranchName],
) -> List[_BranchName]:
    observed: List[_BranchName] = []
    for branch_name in timed_out_branches:
        future = branch_futures[branch_name]
        try:
            future.result(timeout=_CANCEL_OBSERVE_GRACE_SECONDS)
        except Exception:
            pass
        if future.done():
            observed.append(branch_name)
    return observed


def _timeout_fallbacks(
    *,
    timed_out_branches: Sequence[str],
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
