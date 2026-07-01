"""LangChain compatibility adapters for contract evidence documents."""

from __future__ import annotations

from typing import Iterable, List

from langchain_core.documents import Document

from .retrieval import EvidenceDocument, evidence_document_from_page_like


def evidence_document_from_langchain(doc: Document) -> EvidenceDocument:
    return evidence_document_from_page_like(doc)


def evidence_document_to_langchain(doc: EvidenceDocument) -> Document:
    metadata = dict(doc.metadata or {})
    metadata.update(
        {key: value for key, value in doc.to_metadata().items() if value not in (None, "", [], {})}
    )
    if doc.node_id:
        metadata.setdefault("node_id", doc.node_id)
    if doc.recipe_name:
        metadata.setdefault("recipe_name", doc.recipe_name)
    if doc.node_type:
        metadata.setdefault("node_type", doc.node_type)
    if doc.retrieval_level:
        metadata.setdefault("retrieval_level", doc.retrieval_level)
    if doc.search_type:
        metadata.setdefault("search_type", doc.search_type)
    if doc.search_method:
        metadata.setdefault("search_method", doc.search_method)
    metadata.setdefault("score", doc.score)
    return Document(page_content=doc.content, metadata=metadata)


def to_langchain_documents(documents: Iterable[EvidenceDocument]) -> List[Document]:
    return [evidence_document_to_langchain(doc) for doc in documents or []]


def from_langchain_documents(documents: Iterable[Document]) -> List[EvidenceDocument]:
    return [evidence_document_from_langchain(doc) for doc in documents or []]


__all__ = [
    "evidence_document_from_langchain",
    "evidence_document_to_langchain",
    "from_langchain_documents",
    "to_langchain_documents",
]
