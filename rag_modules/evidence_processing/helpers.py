"""Shared helpers for evidence normalization."""

from __future__ import annotations

import hashlib
from collections.abc import Sequence

from ..contracts import EvidenceDocument, JsonObject


def stable_hash(text: str) -> str:
    return hashlib.sha1((text or "").encode("utf-8")).hexdigest()[:16]


def first_value(metadata: JsonObject, keys: Sequence[str], default: object = "") -> object:
    for key in keys:
        value = metadata.get(key)
        if value not in (None, "", [], {}):
            return value
    return default


def document_content(document: EvidenceDocument) -> str:
    return document.content


def document_metadata(
    document: EvidenceDocument,
    metadata: JsonObject | None = None,
) -> JsonObject:
    base = dict(document.metadata)
    base.update(
        {
            key: value
            for key, value in document.to_metadata().items()
            if value not in (None, "", [], {})
        }
    )
    base.update(metadata or {})
    return base


def infer_evidence_type(metadata: JsonObject) -> str:
    search_type = str(metadata.get("search_type") or "")
    node_type = str(metadata.get("node_type") or "")
    if "graph_path" in search_type:
        return "path"
    if "subgraph" in search_type:
        return "subgraph"
    if "constraint" in search_type:
        return "constraint"
    if node_type:
        return node_type.lower()
    return "text"


__all__ = [
    "document_content",
    "document_metadata",
    "first_value",
    "infer_evidence_type",
    "stable_hash",
]
