"""
Request shaping and trace lifecycle for graph retrieval.
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional, Tuple, Union

from ..query_constraints import QueryConstraints
from ..query_understanding import QueryPlan
from ..retrieval.contracts import RetrievalRequest
from ..runtime import GraphRetrievalSnapshot
from .query_resolution import GraphQueryFactory
from .retrieval_types import GraphQuery


class GraphRetrievalRuntime:
    """Own request normalization and graph trace bookkeeping."""

    def __init__(self, query_factory: GraphQueryFactory):
        self.query_factory = query_factory

    def build_request(
        self,
        request_or_query: Union[str, RetrievalRequest],
        *,
        top_k: int = 5,
        constraints: Optional[QueryConstraints] = None,
        query_plan: Optional[QueryPlan] = None,
    ) -> RetrievalRequest:
        if isinstance(request_or_query, RetrievalRequest):
            return request_or_query
        return RetrievalRequest.from_inputs(
            query=request_or_query,
            top_k=top_k,
            candidate_k=top_k,
            constraints=constraints,
            query_plan=query_plan,
            strategy="graph_rag",
        )

    def resolve_request_context(self, request: RetrievalRequest) -> Tuple[GraphQuery, List[str]]:
        graph_query = (
            self.query_factory.graph_query_from_plan(request.query_plan)
            if request.query_plan
            else self.query_factory.understand_graph_query(request.query)
        )
        if request.effective_constraints.has_constraints():
            graph_query.constraints = request.effective_constraints.to_dict()
        evidence_goals = self.query_factory.decompose_graph_question(request.query, graph_query)
        return graph_query, evidence_goals

    @staticmethod
    def start_trace(
        query: str,
        *,
        requested_top_k: int = 0,
        retrieval_request: Optional[RetrievalRequest] = None,
    ) -> GraphRetrievalSnapshot:
        return GraphRetrievalSnapshot(
            query=query,
            strategy="graph_rag",
            requested_top_k=requested_top_k,
            retrieval_request=retrieval_request,
        )

    @staticmethod
    def populate_trace_context(
        trace: GraphRetrievalSnapshot,
        *,
        graph_query: GraphQuery,
        evidence_goals: List[str],
    ) -> None:
        trace.query_type = graph_query.query_type.value
        trace.source_entities = list(graph_query.source_entities or [])
        trace.target_entities = list(graph_query.target_entities or [])
        trace.relation_types = list(graph_query.relation_types or [])
        trace.sub_questions = list(evidence_goals or [])

    @staticmethod
    def finalize_trace(
        trace: GraphRetrievalSnapshot,
        *,
        start_time: float,
        doc_count: int = 0,
        evidence_unit_count: int = 0,
        error: str = "",
    ) -> GraphRetrievalSnapshot:
        trace.doc_count = max(0, int(doc_count or 0))
        trace.evidence_unit_count = max(0, int(evidence_unit_count or 0))
        trace.total_latency_ms = round((time.perf_counter() - start_time) * 1000, 2)
        if error:
            trace.error = str(error)
        return trace

    @staticmethod
    def record_event(
        trace: GraphRetrievalSnapshot,
        name: str,
        *,
        start_time: Optional[float] = None,
        latency_ms: Optional[float] = None,
        status: str = "ok",
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        if latency_ms is None:
            latency_ms = round((time.perf_counter() - start_time) * 1000, 2) if start_time else 0.0
        trace.add_event(
            name,
            status=status,
            latency_ms=latency_ms,
            details=details or {},
        )
