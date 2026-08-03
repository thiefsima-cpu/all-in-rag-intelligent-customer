"""Stable content signatures for graph, document, embedding, and index artifacts."""

from __future__ import annotations

import hashlib
from typing import Any, Dict, Mapping

from .json import canonical_json_bytes, json_safe


def compute_graph_signature(data_module: object) -> str:
    domain_name = str(getattr(data_module, "domain_name", "") or "")
    domain_version = str(getattr(data_module, "domain_version", "") or "")
    entities = getattr(data_module, "entities", []) or []
    payload: Dict[str, Any] = {
        "schema": "graph-content-v4",
        "domain": domain_name,
        "domain_version": domain_version,
        "entities": sorted(
            (
                {
                    "node_id": str(getattr(node, "node_id", "")),
                    "name": str(getattr(node, "name", "")),
                    "labels": sorted(str(label) for label in (getattr(node, "labels", []) or [])),
                    "properties": json_safe(getattr(node, "properties", {}) or {}),
                }
                for node in entities
            ),
            key=lambda item: (
                item["node_id"],
                item["name"],
                canonical_json_bytes(item["properties"]),
            ),
        ),
    }
    return hashlib.sha256(canonical_json_bytes(payload)).hexdigest()


def _signature(namespace: str, payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        canonical_json_bytes(
            {
                "namespace": namespace,
                **dict(payload),
            }
        )
    ).hexdigest()


def compute_document_signature(
    *,
    graph_signature: str,
    chunk_size: int,
    chunk_overlap: int,
    domain_version: str = "",
) -> str:
    return _signature(
        "document-artifacts-v2",
        {
            "graph_signature": graph_signature,
            "domain_version": str(domain_version),
            "chunk_size": int(chunk_size),
            "chunk_overlap": int(chunk_overlap),
        },
    )


def compute_embedding_signature(*, model_name: str, dimension: int, base_url: str) -> str:
    return _signature(
        "embedding-runtime-v2",
        {
            "model_name": str(model_name),
            "dimension": int(dimension),
            "base_url": str(base_url),
        },
    )


def compute_index_signature(
    *,
    document_signature: str,
    embedding_signature: str,
    collection_name: str,
) -> str:
    return _signature(
        "vector-index-v2",
        {
            "document_signature": document_signature,
            "embedding_signature": embedding_signature,
            "collection_name": str(collection_name),
        },
    )


__all__ = [
    "compute_document_signature",
    "compute_embedding_signature",
    "compute_graph_signature",
    "compute_index_signature",
]
