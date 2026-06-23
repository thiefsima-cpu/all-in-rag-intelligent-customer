"""Execution strategies for route-specific retrieval orchestration."""

from __future__ import annotations

import threading
import time
from concurrent.futures import Executor, ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import List, Optional, Protocol

from ..domain.shared.query_constraints import QueryConstraints
from ..query_understanding import QueryPlan
from ..retrieval.contracts import EvidenceDocument, RetrievalRequest
from ..retrieval.hybrid_outcome import HybridRetrievalOutcome
from ..retrieval.runtime_profile import RetrievalRuntimeProfile
from ..runtime import GraphRetrievalSnapshot, QueryAnalysis, SearchStrategy
from ..runtime.json_types import JsonObject, coerce_json_object, coerce_json_value
from ..runtime_contracts import GraphRAGRetrievalPort, HybridRetrievalPort


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


class HybridRouteStrategy:
    """Pure hybrid retrieval execution."""

    strategy = SearchStrategy.HYBRID_TRADITIONAL

    def execute(
        self,
        request: RouteExecutionRequestPort,
        *,
        services: RouteRetrievalServices,
    ) -> RouteExecutionOutcome:
        start = time.perf_counter()
        outcome = services.traditional_retrieval.hybrid_evidence_search(request.retrieval_request)
        documents = list(outcome.documents)
        return RouteExecutionOutcome(
            documents=documents,
            stages=[
                RouteExecutionStageResult(
                    name="hybrid",
                    documents=documents,
                    latency_ms=_elapsed_ms(start),
                    details=coerce_json_object(outcome.to_stage_details()),
                )
            ],
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
    "CombinedRouteStrategy",
    "GraphRouteStrategy",
    "HybridRouteStrategy",
    "RouteExecutionOutcome",
    "RouteExecutionRequestPort",
    "RouteExecutionStageResult",
    "RouteRetrievalServices",
    "RouteRetrievalStrategy",
    "build_route_retrieval_request",
    "interleave_route_documents",
    "merge_route_documents",
]
