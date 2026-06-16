"""Compatibility re-export for split retrieval contracts."""

from __future__ import annotations

from .contracts import (
    EvidenceDocument,
    RetrievalRequest,
    ensure_evidence_documents,
    from_langchain_documents,
    to_langchain_documents,
)

__all__ = [
    "EvidenceDocument",
    "RetrievalRequest",
    "ensure_evidence_documents",
    "from_langchain_documents",
    "to_langchain_documents",
]
