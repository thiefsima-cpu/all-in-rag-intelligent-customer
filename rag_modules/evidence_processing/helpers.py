"""Shared helpers for evidence normalization."""

from __future__ import annotations

import hashlib
from typing import Any, Dict, List, Optional

from ..retrieval.contracts import EvidenceDocument
from .models import PageDocumentLike


def stable_hash(text: str) -> str:
    return hashlib.sha1((text or "").encode("utf-8")).hexdigest()[:16]


def first_value(metadata: Dict[str, Any], keys: List[str], default: Any = "") -> Any:
    for key in keys:
        value = metadata.get(key)
        if value not in (None, "", [], {}):
            return value
    return default


def document_content(doc: PageDocumentLike | EvidenceDocument) -> str:
    if isinstance(doc, EvidenceDocument):
        return doc.content
    return str(getattr(doc, "page_content", "") or "")


def document_metadata(
    doc: PageDocumentLike | EvidenceDocument,
    metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    merged = dict(metadata or {})
    if isinstance(doc, EvidenceDocument):
        base = dict(doc.metadata or {})
        base.update(
            {
                key: value
                for key, value in doc.to_metadata().items()
                if value not in (None, "", [], {})
            }
        )
        base.update(merged)
        return base

    base = dict(getattr(doc, "metadata", {}) or {})
    base.update(merged)
    return base


def infer_evidence_type(metadata: Dict[str, Any]) -> str:
    search_type = str(metadata.get("search_type") or "")
    node_type = str(metadata.get("node_type") or "")
    if "graph_path" in search_type:
        return "path"
    if "subgraph" in search_type:
        return "subgraph"
    if "constraint" in search_type:
        return "recipe"
    if node_type:
        return node_type.lower()
    return "recipe" if metadata.get("recipe_name") else "text"


__all__ = [
    "document_content",
    "document_metadata",
    "first_value",
    "infer_evidence_type",
    "stable_hash",
]
