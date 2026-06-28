"""Shared route execution strategy contracts and helpers."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import List, Optional, Protocol

from ...contracts import EvidenceDocument, QueryPlan, RetrievalRequest
from ...domain.shared.query_constraints import QueryConstraints
from ...retrieval.runtime_profile import RetrievalRuntimeProfile
from ...runtime import QueryAnalysis, SearchStrategy
from ...runtime.json_types import JsonObject, coerce_json_object, coerce_json_value
from ...runtime_contracts import GraphRAGRetrievalPort, HybridRetrievalPort


@dataclass(frozen=True, slots=True)
class RouteExecutionStageResult:
    """One traceable retrieval stage emitted by a route execution strategy."""

    name: str
    documents: List[EvidenceDocument] = field(default_factory=list)
    latency_ms: float = 0.0
    extra: object | None = None
    details: JsonObject = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class RouteExecutionOutcome:
    """Documents, stages, and fallbacks produced by a route execution strategy."""

    documents: List[EvidenceDocument] = field(default_factory=list)
    stages: List[RouteExecutionStageResult] = field(default_factory=list)
    fallbacks: List[str] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class RouteRetrievalServices:
    """Shared retrieval collaborators needed by route execution strategies."""

    traditional_retrieval: HybridRetrievalPort
    graph_rag_retrieval: GraphRAGRetrievalPort
    retrieval_profile: RetrievalRuntimeProfile


class RouteExecutionRequestPort(Protocol):
    """Route execution request shape consumed by strategy implementations."""

    query: str
    top_k: int
    analysis: QueryAnalysis
    retrieval_request: RetrievalRequest
    constraints: QueryConstraints
    query_plan: QueryPlan | None


class RouteRetrievalStrategy(Protocol):
    """Stable contract for one route retrieval execution strategy."""

    strategy: SearchStrategy

    def execute(
        self,
        request: RouteExecutionRequestPort,
        *,
        services: RouteRetrievalServices,
    ) -> RouteExecutionOutcome: ...


def build_route_retrieval_request(
    *,
    query: str,
    top_k: int,
    constraints: Optional[QueryConstraints] = None,
    candidate_k: Optional[int] = None,
    query_plan: Optional[QueryPlan] = None,
    strategy: str = "",
) -> RetrievalRequest:
    return RetrievalRequest.from_inputs(
        query=query,
        top_k=top_k,
        candidate_k=candidate_k,
        constraints=constraints,
        query_plan=query_plan,
        strategy=strategy,
    )


def merge_route_documents(
    primary_docs: List[EvidenceDocument],
    secondary_docs: List[EvidenceDocument],
    *,
    limit: int,
) -> List[EvidenceDocument]:
    merged: List[EvidenceDocument] = []
    seen = set()
    for doc in list(primary_docs) + list(secondary_docs):
        doc_id = doc.document_key()
        if doc_id in seen:
            continue
        seen.add(doc_id)
        merged.append(doc)
        if len(merged) >= limit:
            break
    return merged


def interleave_route_documents(
    graph_docs: List[EvidenceDocument],
    traditional_docs: List[EvidenceDocument],
    *,
    limit: int,
) -> List[EvidenceDocument]:
    combined_docs: List[EvidenceDocument] = []
    seen = set()
    max_len = max(len(traditional_docs), len(graph_docs))
    for index in range(max_len):
        for source_name, source_docs in (
            ("graph_rag", graph_docs),
            ("traditional", traditional_docs),
        ):
            if index >= len(source_docs):
                continue
            doc = source_docs[index]
            doc_id = doc.document_key()
            if doc_id in seen:
                continue
            seen.add(doc_id)
            metadata = dict(doc.metadata or {})
            metadata["search_source"] = source_name
            combined_docs.append(
                doc.copy_with(
                    source=source_name,
                    metadata=metadata,
                )
            )
            if len(combined_docs) >= limit:
                return combined_docs
    return combined_docs


def _elapsed_ms(start: float) -> float:
    return round((time.perf_counter() - start) * 1000, 2)


def _trace_stage_details(trace: object) -> JsonObject:
    to_stage_details = getattr(trace, "to_stage_details", None)
    if callable(to_stage_details):
        return coerce_json_object(to_stage_details())
    to_dict = getattr(trace, "to_dict", None)
    if callable(to_dict):
        return {"graph_trace": coerce_json_value(to_dict())}
    return {"graph_trace": coerce_json_value(trace)}


__all__ = [
    "RouteExecutionOutcome",
    "RouteExecutionRequestPort",
    "RouteExecutionStageResult",
    "RouteRetrievalServices",
    "RouteRetrievalStrategy",
    "build_route_retrieval_request",
    "interleave_route_documents",
    "merge_route_documents",
]
