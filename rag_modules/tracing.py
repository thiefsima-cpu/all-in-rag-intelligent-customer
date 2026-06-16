"""Structured query tracing."""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any, Dict, List, Optional

from .retrieval.contracts import EvidenceDocument, ensure_evidence_documents
from .retrieval_observability import summarize_documents
from .runtime import (
    AnswerContext,
    AnswerTraceSnapshot,
    GenerationSnapshot,
    GraphRetrievalSnapshot,
    ModelSuiteSnapshot,
    QueryDiagnostics,
    QueryTraceEvent,
    RetrievalOutcome,
    RetrievalTraceSnapshot,
    RouteSnapshot,
    analysis_strategy_name,
)
from .runtime.snapshot_utils import (
    clone_generation_snapshot,
    clone_graph_snapshot,
    clone_route_snapshot,
)
from .tracing_sinks import JsonlQueryTraceSink, NullQueryTraceSink, QueryTraceSink
from .trace_privacy import TraceSanitizer

logger = logging.getLogger(__name__)


class QueryTracer:
    def __init__(self, config, sink: QueryTraceSink | None = None):
        self.config = config
        self.models = config.models
        self.observability = config.observability
        self.enabled = bool(self.observability.enable_query_tracing)
        self.trace_path = str(self.observability.query_trace_path)
        self.sanitizer = TraceSanitizer(
            getattr(self.observability, "query_trace_fingerprint_salt", "")
        )
        self.sink = sink or (
            JsonlQueryTraceSink(self.trace_path) if self.enabled else NullQueryTraceSink()
        )

    def record(
        self,
        query: str,
        analysis: Any,
        documents: List[EvidenceDocument] | RetrievalOutcome | AnswerContext,
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
            documents,
            evidence_documents,
            latency_ms,
            answer,
            error,
            route_trace,
            graph_trace,
            generation_trace,
        )
        event = self.sanitizer.sanitize_event(event)
        if not self.enabled:
            return event
        try:
            self.sink.write(event)
        except Exception as exc:
            logger.warning("Failed to write query trace: %s", exc)
        return event

    def close(self) -> None:
        try:
            self.sink.close()
        except Exception as exc:
            logger.warning("Failed to close query tracer sink: %s", exc)

    def stats(self) -> Dict[str, Any]:
        sink_stats: Dict[str, Any] = {}
        sink_stats_getter = getattr(self.sink, "stats", None)
        if callable(sink_stats_getter):
            try:
                sink_stats = dict(sink_stats_getter() or {})
            except Exception as exc:
                logger.debug("Failed to read query trace sink stats: %s", exc)
        return {
            "enabled": self.enabled,
            "path": self.trace_path,
            **sink_stats,
        }

    def _build_event(
        self,
        query: str,
        analysis: Any,
        documents: List[EvidenceDocument] | RetrievalOutcome | AnswerContext,
        evidence_documents: List[EvidenceDocument],
        latency_ms: float,
        answer: Optional[str],
        error: Optional[str],
        route_trace: Optional[Dict[str, Any] | RouteSnapshot],
        graph_trace: Optional[Dict[str, Any] | GraphRetrievalSnapshot],
        generation_trace: Optional[Dict[str, Any] | GenerationSnapshot],
    ) -> QueryTraceEvent:
        plan = self._extract_plan(documents, evidence_documents)
        strategy = analysis_strategy_name(analysis) or None
        route_snapshot = self._normalize_route_snapshot(route_trace)
        graph_snapshot = self._normalize_graph_snapshot(graph_trace)
        generation_snapshot = self._normalize_generation_snapshot(generation_trace)
        diagnostics = self._build_diagnostics(
            evidence_documents,
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
                llm=str(self.models.llm_model),
                embedding=str(self.models.embedding_model),
                rerank=str(self.models.rerank_model),
            ),
            retrieval=RetrievalTraceSnapshot(
                doc_count=len(evidence_documents or []),
                evidence=summarize_documents(evidence_documents or [], limit=10),
                route_trace=route_snapshot,
                graph_trace=graph_snapshot,
                failure_reasons=list(diagnostics.failure_reasons or []),
            ),
            generation=generation_snapshot,
            diagnostics=diagnostics,
            answer=AnswerTraceSnapshot(chars=len(answer or ""), preview=(answer or "")[:300]),
            error=error or "",
        )

    @staticmethod
    def _normalize_evidence_documents(
        documents: List[EvidenceDocument] | RetrievalOutcome | AnswerContext,
    ) -> List[EvidenceDocument]:
        if isinstance(documents, AnswerContext):
            return list(documents.evidence_documents)
        if isinstance(documents, RetrievalOutcome):
            return list(documents.evidence_documents)
        return ensure_evidence_documents(documents)

    @staticmethod
    def _extract_plan(
        documents: List[EvidenceDocument] | RetrievalOutcome | AnswerContext,
        evidence_documents: List[EvidenceDocument],
    ) -> Dict[str, Any]:
        if isinstance(documents, AnswerContext) and documents.understanding is not None:
            return documents.understanding.query_plan.to_dict()
        if isinstance(documents, RetrievalOutcome):
            metadata = dict(documents.metadata or {})
            understanding = metadata.get("query_understanding") or {}
            if understanding:
                return dict((understanding.get("query_plan") or {}))
            return dict(metadata.get("query_plan") or {})
        if evidence_documents:
            return dict(evidence_documents[0].metadata.get("query_plan") or {})
        return {}

    @staticmethod
    def _normalize_route_snapshot(route_trace: Optional[Dict[str, Any] | RouteSnapshot]) -> RouteSnapshot:
        return clone_route_snapshot(route_trace)

    @staticmethod
    def _normalize_graph_snapshot(
        graph_trace: Optional[Dict[str, Any] | GraphRetrievalSnapshot],
    ) -> GraphRetrievalSnapshot:
        return clone_graph_snapshot(graph_trace)

    @staticmethod
    def _normalize_generation_snapshot(
        generation_trace: Optional[Dict[str, Any] | GenerationSnapshot],
    ) -> GenerationSnapshot:
        return clone_generation_snapshot(generation_trace)

    def _build_diagnostics(
        self,
        documents: List[EvidenceDocument],
        error: Optional[str],
        route_trace: RouteSnapshot,
        generation_trace: GenerationSnapshot,
    ) -> QueryDiagnostics:
        retrieval_bucket = self._classify_retrieval_state(documents, route_trace, error)
        generation_bucket = self._classify_generation_state(generation_trace, error)
        failure_reasons = self._failure_reasons(documents, error, route_trace)
        if generation_trace.failure_code:
            failure_reasons.append(generation_trace.failure_code)
        return QueryDiagnostics(
            retrieval_bucket=retrieval_bucket,
            generation_bucket=generation_bucket,
            overall_bucket=self._combine_buckets(retrieval_bucket, generation_bucket, error),
            failure_reasons=failure_reasons,
        )

    @staticmethod
    def _failure_reasons(
        documents: List[EvidenceDocument],
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
        hybrid_stage = stages.get("hybrid") or stages.get("hybrid_fallback") or stages.get("combined")
        if hybrid_stage and hybrid_stage.doc_count == 0:
            reasons.append("hybrid_empty")
        return list(dict.fromkeys(reasons))

    @staticmethod
    def _classify_retrieval_state(
        documents: List[EvidenceDocument],
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
        if not generation_trace.is_recorded():
            return "generation_not_recorded"
        if error:
            return "application_error"
        if generation_trace.fallback_used:
            if generation_trace.failure_code in {
                "generation_provider_timeout",
                "generation_latency_budget_exceeded",
            }:
                return "generation_timeout_fallback"
            return "generation_fallback"
        if generation_trace.status == "failed":
            return "generation_failed"
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
        if generation_bucket == "generation_fallback":
            return "degraded_response"
        if generation_bucket == "generation_failed":
            return "query_failed"
        if retrieval_bucket in {"retrieval_empty", "retrieval_and_generation_failed"}:
            return "no_answerable_evidence"
        if retrieval_bucket == "retrieval_used_fallback" and generation_bucket == "generation_two_stage":
            return "graph_grounded_response"
        if generation_bucket == "generation_direct":
            return "simple_grounded_response"
        return "ok"
