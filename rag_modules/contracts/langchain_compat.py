"""LangChain compatibility adapters for contract evidence documents."""

from __future__ import annotations

from typing import Any, Iterable, List, Mapping, Protocol, TypeVar, cast

from langchain_core.documents import Document

from ._common import coerce_float, coerce_str
from .retrieval import EvidenceDocument

EvidenceDocumentT = TypeVar("EvidenceDocumentT", bound=EvidenceDocument)


class PageDocumentLike(Protocol):
    @property
    def page_content(self) -> str: ...

    @property
    def metadata(self) -> Mapping[str, Any]: ...


def _matched_terms_from_metadata(metadata: dict) -> List[str]:
    matched_terms = list(metadata.get("matched_terms") or [])
    if matched_terms:
        return list(dict.fromkeys(str(item) for item in matched_terms if str(item).strip()))

    collected: List[str] = []
    for key in ("matched_keyword", "matched_ingredients", "matched_steps"):
        value = metadata.get(key)
        if isinstance(value, list):
            collected.extend(str(item) for item in value if item)
        elif value:
            collected.append(str(value))
    return list(dict.fromkeys(item for item in collected if item.strip()))


def evidence_document_from_langchain(
    doc: PageDocumentLike,
    *,
    cls: type[EvidenceDocumentT] | None = None,
) -> EvidenceDocumentT:
    metadata = dict(doc.metadata or {})
    document_cls = cls or cast(type[EvidenceDocumentT], EvidenceDocument)
    return document_cls(
        content=doc.page_content or "",
        node_id=coerce_str(
            metadata.get("node_id") or metadata.get("parent_id") or metadata.get("recipe_id")
        ),
        recipe_name=coerce_str(metadata.get("recipe_name") or metadata.get("name")),
        node_type=coerce_str(metadata.get("node_type") or metadata.get("entity_type")),
        score=coerce_float(
            metadata.get("final_score")
            or metadata.get("relevance_score")
            or metadata.get("constraint_score")
            or metadata.get("score")
            or metadata.get("bm25_score")
        ),
        search_type=coerce_str(metadata.get("search_type")),
        search_method=coerce_str(metadata.get("search_method") or metadata.get("search_source")),
        retrieval_level=coerce_str(metadata.get("retrieval_level")),
        doc_id=coerce_str(metadata.get("doc_id")),
        recipe_id=coerce_str(
            metadata.get("recipe_id") or metadata.get("node_id") or metadata.get("parent_id")
        ),
        source=coerce_str(
            metadata.get("source")
            or metadata.get("search_source")
            or metadata.get("search_method")
            or metadata.get("search_type")
            or "unknown"
        ),
        evidence_type=coerce_str(
            metadata.get("evidence_type")
            or metadata.get("search_type")
            or ("recipe" if metadata.get("recipe_name") else "text")
        ),
        matched_terms=_matched_terms_from_metadata(metadata),
        graph_evidence=dict(metadata.get("graph_evidence") or {}),
        recipe_graph_evidence=dict(metadata.get("recipe_graph_evidence") or {}),
        constraint_evidence=dict(metadata.get("constraint_evidence") or {}),
        evidence_units=[
            dict(item) for item in (metadata.get("evidence_units") or []) if isinstance(item, dict)
        ],
        route_strategy=coerce_str(metadata.get("route_strategy")),
        metadata=metadata,
    )


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


def ensure_evidence_documents(
    documents: Iterable[PageDocumentLike | EvidenceDocument],
) -> List[EvidenceDocument]:
    evidence_documents: List[EvidenceDocument] = []
    for doc in documents or []:
        if isinstance(doc, EvidenceDocument):
            evidence_documents.append(doc)
        else:
            evidence_documents.append(evidence_document_from_langchain(doc))
    return evidence_documents


def to_langchain_documents(documents: Iterable[EvidenceDocument]) -> List[Document]:
    return [evidence_document_to_langchain(doc) for doc in documents or []]


def from_langchain_documents(documents: Iterable[Document]) -> List[EvidenceDocument]:
    return [evidence_document_from_langchain(doc) for doc in documents or []]


__all__ = [
    "PageDocumentLike",
    "ensure_evidence_documents",
    "evidence_document_from_langchain",
    "evidence_document_to_langchain",
    "from_langchain_documents",
    "to_langchain_documents",
]

