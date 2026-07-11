"""Parent-document lifecycle and enrichment for hybrid retrieval."""

from __future__ import annotations

from typing import Dict, List, Optional, Protocol

from ..contracts import EvidenceDocument
from ..kernel.documents import TextDocument


class ParentDocumentStatePort(Protocol):
    parent_doc_map: Dict[str, TextDocument]


class ParentDocumentIndexServicePort(Protocol):
    def _build_parent_doc_map(self) -> Dict[str, TextDocument]: ...


class ParentDocumentEnricherPort(Protocol):
    parent_doc_map: Dict[str, TextDocument]

    def attach(
        self,
        docs: List[TextDocument],
        top_n: Optional[int] = None,
    ) -> List[TextDocument]: ...

    def enrich_graph_documents(
        self,
        docs: List[TextDocument],
        top_n: Optional[int] = None,
    ) -> List[TextDocument]: ...

    def attach_evidence(
        self,
        docs: List[EvidenceDocument],
        top_n: Optional[int] = None,
    ) -> List[EvidenceDocument]: ...

    def enrich_graph_evidence_documents(
        self,
        docs: List[EvidenceDocument],
        top_n: Optional[int] = None,
    ) -> List[EvidenceDocument]: ...


class HybridParentDocumentService:
    """Own parent-document map synchronization and enrichment operations."""

    def __init__(
        self,
        *,
        index_service: ParentDocumentIndexServicePort,
        parent_enricher: ParentDocumentEnricherPort,
    ) -> None:
        self.index_service = index_service
        self.parent_enricher = parent_enricher

    def apply_parent_doc_map(
        self, state: ParentDocumentStatePort, parent_doc_map: Dict[str, TextDocument] | None
    ) -> Dict[str, TextDocument]:
        state.parent_doc_map = dict(parent_doc_map or {})
        self.parent_enricher.parent_doc_map = state.parent_doc_map
        return state.parent_doc_map

    def build_parent_doc_map(self, state: ParentDocumentStatePort) -> Dict[str, TextDocument]:
        return self.apply_parent_doc_map(
            state,
            self.index_service._build_parent_doc_map(),
        )

    def ensure_parent_doc_map(self, state: ParentDocumentStatePort) -> Dict[str, TextDocument]:
        if not state.parent_doc_map:
            return self.build_parent_doc_map(state)
        self.parent_enricher.parent_doc_map = state.parent_doc_map
        return state.parent_doc_map

    def attach_documents(
        self,
        state: ParentDocumentStatePort,
        docs: List[TextDocument],
        *,
        top_n: Optional[int] = None,
    ) -> List[TextDocument]:
        self.ensure_parent_doc_map(state)
        return self.parent_enricher.attach(docs, top_n=top_n)

    def enrich_documents(
        self,
        state: ParentDocumentStatePort,
        docs: List[TextDocument],
        *,
        top_n: Optional[int] = None,
    ) -> List[TextDocument]:
        if not docs:
            return docs
        self.ensure_parent_doc_map(state)
        return self.parent_enricher.enrich_graph_documents(docs, top_n=top_n)

    def attach_evidence_documents(
        self,
        state: ParentDocumentStatePort,
        docs: List[EvidenceDocument],
        *,
        top_n: Optional[int] = None,
    ) -> List[EvidenceDocument]:
        self.ensure_parent_doc_map(state)
        return self.parent_enricher.attach_evidence(docs, top_n=top_n)

    def enrich_evidence_documents(
        self,
        state: ParentDocumentStatePort,
        docs: List[EvidenceDocument],
        *,
        top_n: Optional[int] = None,
    ) -> List[EvidenceDocument]:
        if not docs:
            return docs
        self.ensure_parent_doc_map(state)
        return self.parent_enricher.enrich_graph_evidence_documents(docs, top_n=top_n)


__all__ = ["HybridParentDocumentService"]
