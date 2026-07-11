"""Result merging and trace details for combined route execution."""

from __future__ import annotations

from typing import Any, List, Sequence

from ...contracts import EvidenceDocument
from ...kernel.json_types import coerce_json_object
from .base import RouteRetrievalServices, _trace_stage_details, interleave_route_documents
from .combined_models import (
    BranchExecutionState,
    BranchName,
    CombinedBranchDocuments,
    CombinedRouteRun,
    GraphBranchResult,
    TraditionalBranchResult,
)


class CombinedResultMerger:
    """Merge branch documents and expose combined-stage trace details."""

    def combine_branch_documents(
        self,
        run: CombinedRouteRun,
        branch_execution: BranchExecutionState,
        *,
        services: RouteRetrievalServices,
    ) -> CombinedBranchDocuments:
        traditional_result = branch_execution.results.get("traditional")
        graph_result = branch_execution.results.get("graph")
        traditional_outcome = None
        traditional_latency_ms = None
        traditional_docs: List[EvidenceDocument] = []
        if isinstance(traditional_result, TraditionalBranchResult):
            traditional_outcome = traditional_result.outcome
            traditional_latency_ms = traditional_result.latency_ms
            traditional_docs = list(traditional_outcome.documents)

        graph_trace = None
        graph_latency_ms = None
        graph_docs: List[EvidenceDocument] = []
        if isinstance(graph_result, GraphBranchResult):
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
        return CombinedBranchDocuments(
            combined_docs=combined_docs,
            traditional_outcome=traditional_outcome,
            graph_trace=graph_trace,
            traditional_docs=traditional_docs,
            graph_docs=graph_docs,
            traditional_latency_ms=traditional_latency_ms,
            graph_latency_ms=graph_latency_ms,
        )

    @staticmethod
    def stage_details(
        run: CombinedRouteRun,
        branch_execution: BranchExecutionState,
        documents: CombinedBranchDocuments,
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

    @staticmethod
    def timeout_fallbacks(branch_execution: BranchExecutionState) -> List[str]:
        return _timeout_fallbacks(
            timed_out_branches=branch_execution.timed_out_branches,
            has_traditional_result=_has_branch_result(
                branch_execution,
                branch_name="traditional",
                result_type=TraditionalBranchResult,
            ),
            has_graph_result=_has_branch_result(
                branch_execution,
                branch_name="graph",
                result_type=GraphBranchResult,
            ),
        )


def _has_branch_result(
    branch_execution: BranchExecutionState,
    *,
    branch_name: BranchName,
    result_type: type[Any],
) -> bool:
    return isinstance(branch_execution.results.get(branch_name), result_type)


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


__all__ = ["CombinedResultMerger"]
