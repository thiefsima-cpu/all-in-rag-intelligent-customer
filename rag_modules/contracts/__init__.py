"""Canonical cross-subsystem contract kernel."""

from .query import (
    GraphQueryType,
    QueryPlan,
    QueryPlannerMode,
    QuerySemanticProfile,
    QuerySemanticScoreBreakdown,
    SearchStrategy,
)
from .query_settings import QueryPlannerRuntimeSettings, QuerySemanticRuntimeSettings
from .retrieval import (
    EvidenceDocument,
    PageDocumentLike,
    RetrievalRequest,
    ensure_evidence_documents,
)

__all__ = [
    "EvidenceDocument",
    "GraphQueryType",
    "PageDocumentLike",
    "QueryPlan",
    "QueryPlannerMode",
    "QueryPlannerRuntimeSettings",
    "QuerySemanticProfile",
    "QuerySemanticRuntimeSettings",
    "QuerySemanticScoreBreakdown",
    "RetrievalRequest",
    "SearchStrategy",
    "ensure_evidence_documents",
]
