"""Intelligent query router."""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional, Tuple

from langchain_core.documents import Document

from .query_constraints import QueryConstraints
from .query_plan import QueryPlan, QueryPlanner
from .retrieval.retrieval_contracts import EvidenceDocument, RetrievalRequest
from .retrieval_post_processor import RetrievalPostProcessContext, RetrievalPostProcessor
from .runtime_models import (
    QueryAnalysis,
    RetrievalOutcome,
    RouteSnapshot,
    RouteStageSnapshot,
    SearchStrategy,
)

logger = logging.getLogger(__name__)


class IntelligentQueryRouter:
    """Route a query to hybrid retrieval, GraphRAG, or a combined strategy."""

    def __init__(
        self,
        traditional_retrieval,
        graph_rag_retrieval,
        llm_client,
        config,
    ):
        self.traditional_retrieval = traditional_retrieval
        self.graph_rag_retrieval = graph_rag_retrieval
        self.llm_client = llm_client
        self.config = config
        self.query_planner = QueryPlanner(
            llm_client,
            config.llm_model,
            cache_size=getattr(config, "query_plan_cache_size", 128),
            timeout_seconds=getattr(config, "llm_timeout_seconds", 20),
            fast_rule_planning=getattr(config, "fast_rule_query_planning", True),
        )
        self.post_processor = RetrievalPostProcessor(config)
        self.route_stats = {
            "traditional_count": 0,
            "graph_rag_count": 0,
            "combined_count": 0,
            "total_queries": 0,
        }
        self._current_plan: Optional[QueryPlan] = None
        self.last_trace: RouteSnapshot = RouteSnapshot()

    @staticmethod
    def _analysis_from_plan(plan: QueryPlan) -> QueryAnalysis:
        try:
            strategy = SearchStrategy(plan.strategy)
        except ValueError:
            strategy = SearchStrategy.HYBRID_TRADITIONAL

        return QueryAnalysis(
            query_complexity=plan.complexity,
            relationship_intensity=plan.relationship_intensity,
            reasoning_required=plan.reasoning_required,
            entity_count=plan.entity_count,
            recommended_strategy=strategy,
            confidence=plan.confidence,
            reasoning=plan.reasoning,
        )

    def analyze_query(self, query: str) -> QueryAnalysis:
        """Compatibility wrapper for callers that only need route analysis."""
        return self._analysis_from_plan(self.query_planner.plan(query))

    def route_query(self, query: str, top_k: int = 5) -> Tuple[RetrievalOutcome, QueryAnalysis]:
        logger.info("Routing query: %s", query)
        route_start = time.perf_counter()
        self.last_trace = RouteSnapshot(
            query=query,
            requested_top_k=top_k,
        )

        plan_start = time.perf_counter()
        plan = self.query_planner.plan(query)
        self.last_trace.add_stage(
            "plan",
            RouteStageSnapshot(
                latency_ms=self._elapsed_ms(plan_start),
                details={
                    "used_cache": plan.used_cache,
                    "strategy": plan.strategy,
                    "planner_mode": plan.planner_mode,
                    "fallback_reason": plan.fallback_reason,
                },
            ),
        )
        self._current_plan = plan
        constraints = plan.constraints
        analysis = self._analysis_from_plan(plan)
        self._update_route_stats(analysis.recommended_strategy)
        self.last_trace.strategy = analysis.strategy_name
        retrieval_request = self._build_retrieval_request(
            query=query,
            top_k=top_k,
            constraints=constraints,
            query_plan=plan,
            strategy=analysis.strategy_name,
        )
        self.last_trace.retrieval_request = retrieval_request
        self.last_trace.refresh_diagnostics()

        try:
            if analysis.recommended_strategy == SearchStrategy.HYBRID_TRADITIONAL:
                stage_start = time.perf_counter()
                evidence_documents = self.traditional_retrieval.hybrid_evidence_search(retrieval_request)
                self.last_trace.add_stage("hybrid", self._stage_snapshot(stage_start, evidence_documents))
            elif analysis.recommended_strategy == SearchStrategy.GRAPH_RAG:
                evidence_documents = self._graph_first_search(
                    query=query,
                    top_k=top_k,
                    constraints=constraints,
                    query_plan=plan,
                )
            else:
                stage_start = time.perf_counter()
                evidence_documents = self._combined_search(
                    query,
                    top_k,
                    constraints=constraints,
                    query_plan=plan,
                )
                self.last_trace.add_stage("combined", self._stage_snapshot(stage_start, evidence_documents))

            post_start = time.perf_counter()
            evidence_documents = self.post_processor.post_process_evidence(
                evidence_documents,
                top_k=top_k,
                context=RetrievalPostProcessContext(
                    query=query,
                    strategy=analysis.strategy_name,
                    query_complexity=analysis.query_complexity,
                    relationship_intensity=analysis.relationship_intensity,
                    route_confidence=analysis.confidence,
                    query_plan=self._current_plan.to_dict() if self._current_plan else {},
                ),
            )
            self.last_trace.add_stage("post_process", self._stage_snapshot(post_start, evidence_documents))
            self.last_trace.finalize(
                total_latency_ms=self._elapsed_ms(route_start),
                final_doc_count=len(evidence_documents),
            )
            return self._build_retrieval_outcome(
                query=query,
                strategy=analysis.strategy_name,
                evidence_documents=evidence_documents,
            ), analysis
        except Exception as exc:
            logger.error("Query routing failed, falling back to hybrid search: %s", exc)
            self.last_trace.add_fallback("router_exception_to_hybrid")
            stage_start = time.perf_counter()
            evidence_documents = self.traditional_retrieval.hybrid_evidence_search(retrieval_request)
            self.last_trace.add_stage(
                "hybrid_exception_fallback",
                self._stage_snapshot(stage_start, evidence_documents),
            )
            self.last_trace.finalize(
                total_latency_ms=self._elapsed_ms(route_start),
                final_doc_count=len(evidence_documents),
                error=str(exc),
            )
            return self._build_retrieval_outcome(
                query=query,
                strategy=analysis.strategy_name,
                evidence_documents=evidence_documents,
            ), analysis

    def _graph_first_search(
        self,
        query: str,
        top_k: int,
        constraints: Optional[QueryConstraints] = None,
        query_plan: Optional[QueryPlan] = None,
    ) -> List[EvidenceDocument]:
        stage_start = time.perf_counter()
        evidence_documents = self.graph_rag_retrieval.graph_rag_evidence_search(
            query,
            top_k,
            constraints=constraints,
            query_plan=query_plan,
        )
        self.last_trace.add_stage(
            "graph_rag",
            self._stage_snapshot(
                stage_start,
                evidence_documents,
                extra=getattr(self.graph_rag_retrieval, "last_trace", {}),
            ),
        )
        evidence_documents = self.traditional_retrieval.enrich_to_parent_evidence_documents(
            evidence_documents,
            top_n=top_k,
        )

        if not evidence_documents:
            logger.info("GraphRAG returned no documents; using hybrid fallback.")
            self.last_trace.add_fallback("graph_empty_to_hybrid")
            fallback_start = time.perf_counter()
            evidence_documents = self.traditional_retrieval.hybrid_evidence_search(
                self._build_retrieval_request(
                    query=query,
                    top_k=top_k,
                    constraints=constraints,
                    query_plan=query_plan,
                )
            )
            self.last_trace.add_stage("hybrid_fallback", self._stage_snapshot(fallback_start, evidence_documents))
            return evidence_documents

        if len(evidence_documents) < top_k:
            logger.info("GraphRAG returned %s documents; supplementing with hybrid results.", len(evidence_documents))
            self.last_trace.add_fallback("graph_insufficient_hybrid_supplement")
            supplement_start = time.perf_counter()
            supplement_docs = self.traditional_retrieval.hybrid_evidence_search(
                self._build_retrieval_request(
                    query=query,
                    top_k=max(top_k * 2, 10),
                    constraints=constraints,
                    query_plan=query_plan,
                )
            )
            self.last_trace.add_stage(
                "hybrid_supplement",
                self._stage_snapshot(supplement_start, supplement_docs),
            )
            evidence_documents = self._merge_documents(
                evidence_documents,
                supplement_docs,
                limit=max(top_k * 2, 10),
            )

        return evidence_documents

    def _combined_search(
        self,
        query: str,
        top_k: int,
        constraints: Optional[QueryConstraints] = None,
        query_plan: Optional[QueryPlan] = None,
    ) -> List[EvidenceDocument]:
        candidate_k = max(top_k * 6, 30)
        traditional_request = self._build_retrieval_request(
            query=query,
            top_k=candidate_k,
            candidate_k=candidate_k,
            constraints=constraints,
            query_plan=query_plan,
            strategy=SearchStrategy.COMBINED.value,
        )

        traditional_docs = self.traditional_retrieval.hybrid_evidence_search(traditional_request)
        graph_docs = self.graph_rag_retrieval.graph_rag_evidence_search(
            query,
            candidate_k,
            constraints=constraints,
            query_plan=query_plan,
        )
        graph_docs = self.traditional_retrieval.enrich_to_parent_evidence_documents(
            graph_docs,
            top_n=candidate_k,
        )

        combined_docs: List[EvidenceDocument] = []
        seen = set()
        max_len = max(len(traditional_docs), len(graph_docs))
        for index in range(max_len):
            for source_name, source_docs in (("graph_rag", graph_docs), ("traditional", traditional_docs)):
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

        return combined_docs[:candidate_k]

    @staticmethod
    def _merge_documents(
        primary_docs: List[EvidenceDocument],
        secondary_docs: List[EvidenceDocument],
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

    @staticmethod
    def _build_retrieval_request(
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

    def _build_retrieval_outcome(
        self,
        *,
        query: str,
        strategy: str,
        evidence_documents: List[EvidenceDocument],
    ) -> RetrievalOutcome:
        return RetrievalOutcome(
            query=query,
            strategy=strategy,
            evidence_documents=list(evidence_documents or []),
            route_trace=RouteSnapshot.from_dict(self.last_trace.to_dict()),
            metadata={
                "route_stats": dict(self.route_stats),
            },
        )

    @staticmethod
    def _elapsed_ms(start: float) -> float:
        return round((time.perf_counter() - start) * 1000, 2)

    def _stage_snapshot(
        self,
        start: float,
        documents: List[Document | EvidenceDocument],
        extra: Optional[Any] = None,
    ) -> RouteStageSnapshot:
        details = {}
        if extra:
            if hasattr(extra, "to_stage_details"):
                extra_payload = extra.to_stage_details()
            elif hasattr(extra, "to_dict"):
                extra_payload = extra.to_dict()
            else:
                extra_payload = dict(extra)
            details.update(
                {
                    key: value
                    for key, value in extra_payload.items()
                    if key not in {"latency_ms", "total_latency_ms", "doc_count", "sources"}
                }
            )
        return RouteStageSnapshot(
            latency_ms=self._elapsed_ms(start),
            doc_count=len(documents or []),
            sources=self._count_doc_sources(documents or []),
            details=details,
        )

    @staticmethod
    def _count_doc_sources(documents: List[Document | EvidenceDocument]) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for doc in documents:
            if isinstance(doc, EvidenceDocument):
                metadata = doc.metadata or {}
                source = (
                    doc.source
                    or doc.search_method
                    or doc.search_type
                    or metadata.get("search_source")
                    or "unknown"
                )
            else:
                metadata = doc.metadata or {}
                source = (
                    metadata.get("source")
                    or metadata.get("search_method")
                    or metadata.get("search_type")
                    or metadata.get("search_source")
                    or "unknown"
                )
            counts[str(source)] = counts.get(str(source), 0) + 1
        return counts

    def _update_route_stats(self, strategy: SearchStrategy):
        self.route_stats["total_queries"] += 1
        if strategy == SearchStrategy.HYBRID_TRADITIONAL:
            self.route_stats["traditional_count"] += 1
        elif strategy == SearchStrategy.GRAPH_RAG:
            self.route_stats["graph_rag_count"] += 1
        elif strategy == SearchStrategy.COMBINED:
            self.route_stats["combined_count"] += 1

    def get_route_statistics(self) -> Dict[str, Any]:
        total = self.route_stats["total_queries"]
        if total == 0:
            return self.route_stats
        return {
            **self.route_stats,
            "traditional_ratio": self.route_stats["traditional_count"] / total,
            "graph_rag_ratio": self.route_stats["graph_rag_count"] / total,
            "combined_ratio": self.route_stats["combined_count"] / total,
        }

