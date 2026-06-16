"""Adapters between internal text documents and LangChain documents."""

from __future__ import annotations

from typing import Iterable, List

from langchain_core.documents import Document

from .text_document import TextDocument


def to_langchain_text_document(document: TextDocument | Document) -> Document:
    if isinstance(document, Document):
        return document
    return Document(
        page_content=document.content,
        metadata=dict(document.metadata or {}),
    )


def to_langchain_text_documents(documents: Iterable[TextDocument | Document]) -> List[Document]:
    return [to_langchain_text_document(document) for document in documents or []]


def to_text_document(document: TextDocument | Document) -> TextDocument:
    if isinstance(document, TextDocument):
        return document
    return TextDocument(
        content=document.page_content,
        metadata=dict(document.metadata or {}),
    )


def to_text_documents(documents: Iterable[TextDocument | Document]) -> List[TextDocument]:
    return [to_text_document(document) for document in documents or []]
