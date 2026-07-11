"""Branch execution for combined route strategy."""

from __future__ import annotations

import threading
import time
from concurrent.futures import Executor, Future, ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from typing import List, Sequence

from ...contracts import RequestControl, RetrievalRequest
from .base import RouteRetrievalServices, _elapsed_ms
from .combined_models import (
    BranchExecutionState,
    BranchName,
    BranchResult,
    CombinedRouteRun,
    GraphBranchResult,
    TraditionalBranchResult,
)

CANCEL_OBSERVE_GRACE_SECONDS = 0.05


class CombinedBranchExecutor:
    """Own and coordinate the traditional/graph branch executor."""

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
        run: CombinedRouteRun,
        *,
        services: RouteRetrievalServices,
    ) -> BranchExecutionState:
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
        return BranchExecutionState(
            results=branch_results,
            timed_out_branches=timed_out_branches,
            cancel_observed_branches=_observe_cancelled_branches(
                branch_futures,
                timed_out_branches=timed_out_branches,
            ),
        )

    def close(self) -> None:
        if not self._owns_executor:
            return
        with self._executor_lock:
            executor = self._executor
            self._executor = None
        if executor is not None:
            executor.shutdown(wait=False, cancel_futures=True)

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


def _submit_branch_futures(
    executor: Executor,
    run: CombinedRouteRun,
    *,
    services: RouteRetrievalServices,
) -> dict[BranchName, Future[BranchResult]]:
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
) -> BranchResult:
    traditional_start = time.perf_counter()
    outcome = services.traditional_retrieval.hybrid_evidence_search(retrieval_request)
    return TraditionalBranchResult(
        outcome=outcome,
        latency_ms=_elapsed_ms(traditional_start),
    )


def _load_graph_branch(
    services: RouteRetrievalServices,
    retrieval_request: RetrievalRequest,
) -> BranchResult:
    graph_start = time.perf_counter()
    docs, trace = services.graph_rag_retrieval.graph_rag_evidence_search_with_trace(
        retrieval_request
    )
    return GraphBranchResult(
        documents=list(docs),
        trace=trace,
        latency_ms=_elapsed_ms(graph_start),
    )


def _await_branch_results(
    branch_futures: dict[BranchName, Future[BranchResult]],
    *,
    timeout_seconds: float,
) -> tuple[dict[BranchName, BranchResult], List[BranchName]]:
    deadline = time.perf_counter() + timeout_seconds
    branch_results: dict[BranchName, BranchResult] = {}
    timed_out_branches: List[BranchName] = []
    for branch_name, future in branch_futures.items():
        try:
            branch_results[branch_name] = future.result(
                timeout=_remaining_timeout_seconds(deadline)
            )
        except FutureTimeoutError:
            timed_out_branches.append(branch_name)
    return branch_results, timed_out_branches


def _accept_ready_timed_out_branches(
    branch_futures: dict[BranchName, Future[BranchResult]],
    *,
    branch_results: dict[BranchName, BranchResult],
    timed_out_branches: List[BranchName],
) -> None:
    for branch_name in list(timed_out_branches):
        future = branch_futures[branch_name]
        if not future.done():
            continue
        branch_results[branch_name] = future.result(timeout=0)
        timed_out_branches.remove(branch_name)


def _cancel_timed_out_branches(
    branch_futures: dict[BranchName, Future[BranchResult]],
    *,
    branch_controls: dict[BranchName, RequestControl],
    timed_out_branches: Sequence[BranchName],
) -> None:
    for branch_name in timed_out_branches:
        branch_controls[branch_name].cancel("combined_branch_timeout")
        branch_futures[branch_name].cancel()


def _observe_cancelled_branches(
    branch_futures: dict[BranchName, Future[BranchResult]],
    *,
    timed_out_branches: Sequence[BranchName],
) -> List[BranchName]:
    observed: List[BranchName] = []
    for branch_name in timed_out_branches:
        future = branch_futures[branch_name]
        try:
            future.result(timeout=CANCEL_OBSERVE_GRACE_SECONDS)
        except Exception:
            pass
        if future.done():
            observed.append(branch_name)
    return observed


def _remaining_timeout_seconds(deadline: float) -> float:
    return max(0.0, deadline - time.perf_counter())


__all__ = ["CANCEL_OBSERVE_GRACE_SECONDS", "CombinedBranchExecutor"]
