"""Canonical cross-subsystem contract kernel."""

from .langchain_compat import (
    PageDocumentLike,
    ensure_evidence_documents,
    from_langchain_documents,
    to_langchain_documents,
)
from .query import QueryPlan, QuerySemanticProfile, QuerySemanticScoreBreakdown
from .query_settings import QueryPlannerRuntimeSettings, QuerySemanticRuntimeSettings
from .retrieval import EvidenceDocument, RetrievalRequest

__all__ = [
    "EvidenceDocument",
    "PageDocumentLike",
    "QueryPlan",
    "QueryPlannerRuntimeSettings",
    "QuerySemanticProfile",
    "QuerySemanticRuntimeSettings",
    "QuerySemanticScoreBreakdown",
    "RetrievalRequest",
    "ensure_evidence_documents",
    "from_langchain_documents",
    "to_langchain_documents",
]
