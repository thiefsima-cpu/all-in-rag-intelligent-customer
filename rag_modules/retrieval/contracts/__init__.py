"""Split retrieval contracts: native models plus compat adapters."""

from .evidence_models import EvidenceDocument
from .langchain_compat import (
    ensure_evidence_documents,
    from_langchain_documents,
    to_langchain_documents,
)
from .request_models import RetrievalRequest

__all__ = [
    "EvidenceDocument",
    "RetrievalRequest",
    "ensure_evidence_documents",
    "from_langchain_documents",
    "to_langchain_documents",
]
