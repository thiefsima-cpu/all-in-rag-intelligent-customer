"""Document cache serialization helpers."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, Iterable, List, Mapping

from .artifact_json import canonical_json_bytes, json_safe, write_json_atomic
from .text_document import TextDocument


def serialize_document(document: TextDocument) -> Dict[str, Any]:
    content = getattr(document, "content", None)
    if content is None:
        content = getattr(document, "page_content", "")
    return {
        "content": str(content or ""),
        "metadata": json_safe(getattr(document, "metadata", {}) or {}),
    }


def compute_documents_digest(documents: Iterable[TextDocument]) -> str:
    payload = [serialize_document(document) for document in documents]
    return hashlib.sha256(canonical_json_bytes(payload)).hexdigest()


def deserialize_document(payload: Mapping[str, Any]) -> TextDocument:
    return TextDocument(
        content=str(payload.get("content") or payload.get("page_content") or ""),
        metadata=dict(payload.get("metadata") or {}),
    )


def write_documents(path: str, documents: Iterable[TextDocument]) -> None:
    payload = [serialize_document(document) for document in documents]
    write_json_atomic(path, payload)


def read_documents(path: str) -> List[TextDocument]:
    with open(path, "r", encoding="utf-8") as file:
        payload = json.load(file)
    if not isinstance(payload, list):
        raise ValueError(f"Document cache payload at {path!r} must be a list.")
    if not all(isinstance(item, Mapping) for item in payload):
        raise ValueError(f"Document cache payload at {path!r} contains invalid items.")
    return [deserialize_document(item) for item in payload]


__all__ = [
    "compute_documents_digest",
    "deserialize_document",
    "read_documents",
    "serialize_document",
    "write_documents",
]
