"""Adapters between internal text documents and LangChain documents."""

from __future__ import annotations

from collections.abc import Iterable

from langchain_core.documents import Document

from .contracts.retrieval_documents import EvidenceDocument, evidence_document_from_text_document
from .kernel.documents import TextDocument


def to_langchain_text_document(document: TextDocument | Document) -> Document:
    if isinstance(document, Document):
        return document
    return Document(
        page_content=document.content,
        metadata=dict(document.metadata or {}),
    )


def to_langchain_text_documents(documents: Iterable[TextDocument | Document]) -> list[Document]:
    return [to_langchain_text_document(document) for document in documents or []]


def to_text_document(document: TextDocument | Document) -> TextDocument:
    if isinstance(document, TextDocument):
        return document
    return TextDocument(
        content=document.page_content,
        metadata=dict(document.metadata or {}),
    )


def to_text_documents(documents: Iterable[TextDocument | Document]) -> list[TextDocument]:
    return [to_text_document(document) for document in documents or []]


def to_evidence_document(document: TextDocument | Document) -> EvidenceDocument:
    return evidence_document_from_text_document(to_text_document(document))


def to_evidence_documents(documents: Iterable[TextDocument | Document]) -> list[EvidenceDocument]:
    return [to_evidence_document(document) for document in documents or []]


def to_langchain_evidence_document(document: EvidenceDocument) -> Document:
    metadata = dict(document.metadata)
    metadata.update(
        {
            key: value
            for key, value in document.to_metadata().items()
            if value not in (None, "", [], {})
        }
    )
    if document.node_id:
        metadata.setdefault("node_id", document.node_id)
    if document.node_type:
        metadata.setdefault("node_type", document.node_type)
    if document.retrieval_level:
        metadata.setdefault("retrieval_level", document.retrieval_level)
    if document.search_type:
        metadata.setdefault("search_type", document.search_type)
    if document.search_method:
        metadata.setdefault("search_method", document.search_method)
    metadata.setdefault("score", document.score)
    return Document(page_content=document.content, metadata=metadata)


def to_langchain_evidence_documents(documents: Iterable[EvidenceDocument]) -> list[Document]:
    return [to_langchain_evidence_document(document) for document in documents or []]
