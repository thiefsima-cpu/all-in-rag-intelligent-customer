"""
Structured query tracing.

Trace events are intentionally compact JSONL records so they can be inspected
with plain text tools and kept out of business logic.
"""

from __future__ import annotations

import json
import logging
import os
import time
import uuid
from typing import Any, Dict, List, Optional

from langchain_core.documents import Document

from .retrieval.retrieval_contracts import EvidenceDocument, ensure_evidence_documents, to_langchain_documents
from .runtime_models import (
    AnswerTraceSnapshot,
    AnswerContext,
    GenerationSnapshot,
    GraphRetrievalSnapshot,
    ModelSuiteSnapshot,
    QueryDiagnostics,
    QueryTraceEvent,
    RetrievalTraceSnapshot,
    RetrievalOutcome,
    RouteSnapshot,
    analysis_strategy_name,
)
from .retrieval_observability import summarize_documents

logger = logging.getLogger(__name__)


class QueryTracer:
    def __init__(self, config):
        self.config = config
        self.enabled = bool(getattr(config, "enable_query_tracing", True))
        self.trace_path = getattr(config, "query_trace_path", "storage/traces/query_trace.jsonl")
        self.last_event: QueryTraceEvent = QueryTraceEvent()

    def record(
        self,
        query: str,
        analysis: Any,
        documents: List[Document | EvidenceDocument] | RetrievalOutcome | AnswerContext,
        latency_ms: float,
        answer: Optional[str] = None,
        error: Optional[str] = None,
        route_trace: Optional[Dict[str, Any] | RouteSnapshot] = None,
        graph_trace: Optional[Dict[str, Any] | GraphRetrievalSnapshot] = None,
        generation_trace: Optional[Dict[str, Any] | GenerationSnapshot] = None,
    ) -> QueryTraceEvent:
        evidence_documents = self._normalize_evidence_documents(documents)
        event = self._build_event(
            query,
            analysis,
            evidence_documents,
            latency_ms,
            answer,
            error,
            route_trace,
            graph_trace,
            generation_trace,
        )
        self.last_event = event
        if not self.enabled:
            return event
        try:
            os.makedirs(os.path.dirname(self.trace_path) or ".", exist_ok=True)
            with open(self.trace_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(event.to_dict(), ensure_ascii=False) + "\n")
        except Exception as exc:
            logger.warning("写入查询 trace 失败: %s", exc)
        return event

    def _build_event(
        self,
        query: str,
        analysis: Any,
        documents: List[Document | EvidenceDocument] | RetrievalOutcome | AnswerContext,
        latency_ms: float,
        answer: Optional[str],
        error: Optional[str],
        route_trace: Optional[Dict[str, Any] | RouteSnapshot],
        graph_trace: Optional[Dict[str, Any] | GraphRetrievalSnapshot],
        generation_trace: Optional[Dict[str, Any] | GenerationSnapshot],
    ) -> QueryTraceEvent:
        langchain_documents = to_langchain_documents(self._normalize_evidence_documents(documents))
        plan = {}
        if langchain_documents:
            plan = langchain_documents[0].metadata.get("query_plan") or {}
        strategy = analysis_strategy_name(analysis) or None
        if strategy is None:
            if isinstance(documents, AnswerContext):
                strategy = documents.retrieval.strategy or None
            elif isinstance(documents, RetrievalOutcome):
                strategy = documents.strategy or None
        route_snapshot = self._normalize_route_snapshot(route_trace)
        graph_snapshot = self._normalize_graph_snapshot(graph_trace)
        generation_snapshot = self._normalize_generation_snapshot(generation_trace)
        diagnostics = self._build_diagnostics(
            langchain_documents or [],
            error,
            route_snapshot,
            generation_snapshot,
        )
        return QueryTraceEvent(
            query_id=str(uuid.uuid4()),
            timestamp=int(time.time()),
            query=query,
            strategy=strategy,
            latency_ms=round(float(latency_ms or 0.0), 2),
            plan=plan,
            models=ModelSuiteSnapshot(
                llm=getattr(self.config, "llm_model", ""),
                embedding=getattr(self.config, "embedding_model", ""),
                rerank=getattr(self.config, "rerank_model", ""),
            ),
            retrieval=RetrievalTraceSnapshot(
                doc_count=len(langchain_documents or []),
                evidence=summarize_documents(langchain_documents or [], limit=10),
                route_trace=route_snapshot,
                graph_trace=graph_snapshot,
                failure_reasons=list(diagnostics.failure_reasons or []),
            ),
            generation=generation_snapshot,
            diagnostics=diagnostics,
            answer=AnswerTraceSnapshot(
                chars=len(answer or ""),
                preview=(answer or "")[:300],
            ),
            error=error or "",
        )

    @staticmethod
    def _normalize_evidence_documents(
        documents: List[Document | EvidenceDocument] | RetrievalOutcome | AnswerContext,
    ) -> List[EvidenceDocument]:
        if isinstance(documents, AnswerContext):
            return list(documents.evidence_documents)
        if isinstance(documents, RetrievalOutcome):
            return list(documents.evidence_documents)
        return ensure_evidence_documents(documents)

    @staticmethod
    def _normalize_route_snapshot(route_trace: Optional[Dict[str, Any] | RouteSnapshot]) -> RouteSnapshot:
        if isinstance(route_trace, RouteSnapshot):
            return RouteSnapshot.from_dict(route_trace.to_dict())
        return RouteSnapshot.from_dict(route_trace or {})

    @staticmethod
    def _normalize_graph_snapshot(
        graph_trace: Optional[Dict[str, Any] | GraphRetrievalSnapshot],
    ) -> GraphRetrievalSnapshot:
        if isinstance(graph_trace, GraphRetrievalSnapshot):
            return GraphRetrievalSnapshot.from_dict(graph_trace.to_dict())
        return GraphRetrievalSnapshot.from_dict(graph_trace or {})

    @staticmethod
    def _normalize_generation_snapshot(
        generation_trace: Optional[Dict[str, Any] | GenerationSnapshot],
    ) -> GenerationSnapshot:
        if isinstance(generation_trace, GenerationSnapshot):
            return GenerationSnapshot.from_dict(generation_trace.to_dict())
        return GenerationSnapshot.from_dict(generation_trace or {})

    def _build_diagnostics(
        self,
        documents: List[Document],
        error: Optional[str],
        route_trace: RouteSnapshot,
        generation_trace: GenerationSnapshot,
    ) -> QueryDiagnostics:
        retrieval_bucket = self._classify_retrieval_state(documents, route_trace, error)
        generation_bucket = self._classify_generation_state(generation_trace, error)
        failure_reasons = self._failure_reasons(documents, error, route_trace)
        return QueryDiagnostics(
            retrieval_bucket=retrieval_bucket,
            generation_bucket=generation_bucket,
            overall_bucket=self._combine_buckets(retrieval_bucket, generation_bucket, error),
            failure_reasons=failure_reasons,
        )

    @staticmethod
    def _failure_reasons(
        documents: List[Document],
        error: Optional[str],
        route_trace: RouteSnapshot,
    ) -> List[str]:
        reasons = []
        if error:
            reasons.append("answer_or_application_error")
        reasons.extend(route_trace.diagnostics.failure_reasons)
        if not documents:
            reasons.append("no_final_documents")
        stages = route_trace.stages or {}
        plan_stage = stages.get("plan")
        if plan_stage and plan_stage.details.get("used_cache") is False and route_trace.error:
            reasons.append("router_error")
        graph_stage = stages.get("graph_rag")
        if graph_stage and graph_stage.doc_count == 0:
            reasons.append("graph_empty")
        hybrid_stage = (
            stages.get("hybrid")
            or stages.get("hybrid_fallback")
            or stages.get("combined")
        )
        if hybrid_stage and hybrid_stage.doc_count == 0:
            reasons.append("hybrid_empty")
        return list(dict.fromkeys(reasons))

    @staticmethod
    def _classify_retrieval_state(
        documents: List[Document],
        route_trace: RouteSnapshot,
        error: Optional[str],
    ) -> str:
        if error and not documents:
            return "retrieval_and_generation_failed"
        if not documents:
            return "retrieval_empty"
        if route_trace.fallbacks:
            return "retrieval_used_fallback"
        stages = route_trace.stages or {}
        graph_stage = stages.get("graph_rag")
        hybrid_stage = stages.get("hybrid") or stages.get("hybrid_fallback") or stages.get("combined")
        if graph_stage and hybrid_stage and graph_stage.doc_count == 0 and hybrid_stage.doc_count > 0:
            return "graph_sparse_hybrid_supported"
        if graph_stage and graph_stage.doc_count > 0 and len(documents) <= 1:
            return "graph_narrow"
        return "retrieval_ok"

    @staticmethod
    def _classify_generation_state(generation_trace: GenerationSnapshot, error: Optional[str]) -> str:
        if (
            not generation_trace.mode
            and not generation_trace.decision_reason
            and generation_trace.total_evidence_items == 0
            and generation_trace.selected_evidence_items == 0
            and generation_trace.plan_latency_ms == 0.0
            and generation_trace.compose_latency_ms == 0.0
            and generation_trace.direct_latency_ms == 0.0
            and not generation_trace.fallback_used
            and not generation_trace.fallback_reason
            and generation_trace.total_latency_ms == 0.0
        ):
            return "generation_not_recorded"
        if error:
            return "application_error"
        if generation_trace.fallback_used:
            reason = str(generation_trace.fallback_reason or "").lower()
            if "timeout" in reason or "timed out" in reason or "readtimeout" in reason:
                return "generation_timeout_fallback"
            return "generation_fallback"
        mode = str(generation_trace.mode or "")
        if mode == "two_stage":
            return "generation_two_stage"
        if mode == "direct":
            return "generation_direct"
        return "generation_unknown"

    @staticmethod
    def _combine_buckets(retrieval_bucket: str, generation_bucket: str, error: Optional[str]) -> str:
        if error:
            return "query_failed"
        if generation_bucket == "generation_timeout_fallback":
            return "latency_timeout"
        if retrieval_bucket in {"retrieval_empty", "retrieval_and_generation_failed"}:
            return "no_answerable_evidence"
        if retrieval_bucket == "retrieval_used_fallback" and generation_bucket == "generation_two_stage":
            return "graph_grounded_response"
        if generation_bucket == "generation_direct":
            return "simple_grounded_response"
        return "ok"
