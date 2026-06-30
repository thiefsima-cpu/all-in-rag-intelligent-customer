"""Trace event construction helpers."""

from __future__ import annotations

import time
import uuid
from collections.abc import Mapping
from typing import Any, Dict, List, Optional, Protocol

from ..contracts import EvidenceDocument, ensure_evidence_documents
from ..retrieval_observability import summarize_documents
from ..runtime import (
    AnswerContext,
    AnswerTraceSnapshot,
    GenerationSnapshot,
    GraphRetrievalSnapshot,
    ModelSuiteSnapshot,
    PolicySnapshot,
    QueryDiagnostics,
    QueryTraceEvent,
    RetrievalOutcome,
    RetrievalTraceSnapshot,
    RouteSnapshot,
    analysis_strategy_name,
)
from ..runtime.snapshot_utils import (
    clone_generation_snapshot,
    clone_graph_snapshot,
    clone_route_snapshot,
)


class _TraceModelSettings(Protocol):
    llm_model: str
    embedding_model: str
    rerank_model: str


class _TraceEventBuilderHost(Protocol):
    models: _TraceModelSettings

    def _build_diagnostics(
        self,
        documents: List[EvidenceDocument],
        error: Optional[str],
        route_trace: RouteSnapshot,
        generation_trace: GenerationSnapshot,
    ) -> QueryDiagnostics: ...


class _TraceEventBuilderMixin(_TraceEventBuilderHost):
    """Build normalized query trace events."""

    def _build_event(
        self,
        query: str,
        analysis: Any,
        documents: List[EvidenceDocument] | RetrievalOutcome | AnswerContext,
        evidence_documents: List[EvidenceDocument],
        latency_ms: float,
        answer: Optional[str],
        error: Optional[str],
        route_trace: Mapping[str, Any] | RouteSnapshot | None,
        graph_trace: Mapping[str, Any] | GraphRetrievalSnapshot | None,
        generation_trace: Mapping[str, Any] | GenerationSnapshot | None,
    ) -> QueryTraceEvent:
        plan = self._extract_plan(documents, evidence_documents)
        strategy = analysis_strategy_name(analysis) or None
        route_snapshot = self._normalize_route_snapshot(route_trace)
        graph_snapshot = self._normalize_graph_snapshot(graph_trace)
        generation_snapshot = self._normalize_generation_snapshot(generation_trace)
        policy_snapshot = self._select_policy_snapshot(
            route_snapshot,
            graph_snapshot,
            generation_snapshot,
        )
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
            policy=policy_snapshot,
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
            understanding = metadata.get("query_understanding")
            if isinstance(understanding, Mapping):
                query_plan = understanding.get("query_plan")
                return dict(query_plan) if isinstance(query_plan, Mapping) else {}
            query_plan = metadata.get("query_plan")
            return dict(query_plan) if isinstance(query_plan, Mapping) else {}
        if evidence_documents:
            return dict(evidence_documents[0].metadata.get("query_plan") or {})
        return {}

    @staticmethod
    def _normalize_route_snapshot(
        route_trace: Mapping[str, Any] | RouteSnapshot | None,
    ) -> RouteSnapshot:
        return clone_route_snapshot(route_trace)

    @staticmethod
    def _normalize_graph_snapshot(
        graph_trace: Mapping[str, Any] | GraphRetrievalSnapshot | None,
    ) -> GraphRetrievalSnapshot:
        return clone_graph_snapshot(graph_trace)

    @staticmethod
    def _normalize_generation_snapshot(
        generation_trace: Mapping[str, Any] | GenerationSnapshot | None,
    ) -> GenerationSnapshot:
        return clone_generation_snapshot(generation_trace)

    @staticmethod
    def _select_policy_snapshot(
        route_snapshot: RouteSnapshot,
        graph_snapshot: GraphRetrievalSnapshot,
        generation_snapshot: GenerationSnapshot,
    ) -> PolicySnapshot:
        for policy in (
            route_snapshot.policy,
            graph_snapshot.policy,
            generation_snapshot.policy,
        ):
            if policy.is_recorded():
                return PolicySnapshot.from_dict(policy.to_dict())
        return PolicySnapshot()


__all__ = ["_TraceEventBuilderMixin"]
