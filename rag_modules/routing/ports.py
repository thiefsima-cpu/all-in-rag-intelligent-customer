"""Ports consumed by routing orchestration."""

from __future__ import annotations

from typing import Protocol

from ..contracts import EvidenceDocument, QueryPlan, RetrievalRequest
from ..contracts.graph import GraphQuery
from ..contracts.runtime import GraphRetrievalSnapshot
from ..contracts.runtime.retrieval import HybridRetrievalOutcome


class HybridRetrievalPort(Protocol):
    """Hybrid retrieval behavior consumed by routing."""

    def hybrid_evidence_search(
        self,
        request: RetrievalRequest,
    ) -> HybridRetrievalOutcome: ...

    def enrich_to_parent_evidence_documents(
        self,
        request: RetrievalRequest,
        docs: list[EvidenceDocument],
        top_n: int | None = None,
    ) -> list[EvidenceDocument]: ...


class GraphRAGRetrievalPort(Protocol):
    """Graph retrieval behavior consumed by routing."""

    def graph_rag_evidence_search_with_trace(
        self,
        request: RetrievalRequest,
    ) -> tuple[list[EvidenceDocument], GraphRetrievalSnapshot]: ...

    def graph_query_from_plan(self, plan: QueryPlan) -> GraphQuery: ...


__all__ = ["GraphRAGRetrievalPort", "HybridRetrievalPort"]
