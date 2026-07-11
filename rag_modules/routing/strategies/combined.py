"""Combined graph and hybrid route execution strategy."""

from __future__ import annotations

import time
from concurrent.futures import Executor

from ...contracts import RequestControl, RetrievalRequest
from ...kernel.routing import SearchStrategy
from .base import (
    RouteExecutionOutcome,
    RouteExecutionRequestPort,
    RouteExecutionStageResult,
    RouteRetrievalServices,
    _elapsed_ms,
    build_route_retrieval_request,
)
from .combined_executor import CombinedBranchExecutor
from .combined_merger import CombinedResultMerger
from .combined_models import CombinedRouteRun
from .combined_timeout import CombinedBranchTimeoutPolicy


class CombinedRouteStrategy:
    """Combined graph and hybrid retrieval execution."""

    strategy = SearchStrategy.COMBINED

    def __init__(
        self,
        *,
        executor: Executor | None = None,
        max_workers: int | None = None,
        thread_name_prefix: str = "combined-route",
        branch_timeout_seconds: float | None = None,
    ) -> None:
        self._timeout_policy = CombinedBranchTimeoutPolicy(branch_timeout_seconds)
        self._branch_executor = CombinedBranchExecutor(
            executor=executor,
            max_workers=max_workers,
            thread_name_prefix=thread_name_prefix,
        )
        self._result_merger = CombinedResultMerger()

    def execute(
        self,
        request: RouteExecutionRequestPort,
        *,
        services: RouteRetrievalServices,
    ) -> RouteExecutionOutcome:
        start = time.perf_counter()
        run = self._prepare_run(request, services=services)
        branch_execution = self._branch_executor.execute(run, services=services)
        documents = self._result_merger.combine_branch_documents(
            run,
            branch_execution,
            services=services,
        )
        details = self._result_merger.stage_details(run, branch_execution, documents)

        return RouteExecutionOutcome(
            documents=list(documents.combined_docs),
            fallbacks=self._result_merger.timeout_fallbacks(branch_execution),
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
    ) -> CombinedRouteRun:
        candidate_k = services.retrieval_profile.candidates.combined_candidate_k(request.top_k)
        branch_timeout_seconds = self._timeout_policy.resolve_branch_timeout_seconds(request)
        route_control = request.retrieval_request.control
        traditional_control = self._timeout_policy.branch_control(
            route_control,
            timeout_seconds=branch_timeout_seconds,
            scope="combined.traditional",
        )
        graph_control = self._timeout_policy.branch_control(
            route_control,
            timeout_seconds=branch_timeout_seconds,
            scope="combined.graph",
        )
        return CombinedRouteRun(
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

    def close(self) -> None:
        self._branch_executor.close()


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


__all__ = ["CombinedRouteStrategy"]
