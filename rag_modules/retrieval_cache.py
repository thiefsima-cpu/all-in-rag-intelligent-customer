"""Integrity-checked JSON persistence for hybrid retrieval indexes."""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
from typing import Any, Dict, List, Mapping, Optional

from .domain.shared.semantic_schema import SEMANTIC_SCHEMA_VERSION
from .graph_index.snapshot import GRAPH_INDEX_VERSION
from .runtime.artifacts import write_json_atomic
from .safe_logging import log_failure
from .text_document import TextDocument

logger = logging.getLogger(__name__)

HYBRID_CACHE_SCHEMA_VERSION = "hybrid-index-cache-v1"
_MAX_CACHE_BYTES = 128 * 1024 * 1024


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, set):
        return sorted((_json_safe(item) for item in value), key=repr)
    raise TypeError(f"Hybrid cache value is not JSON serializable: {type(value).__name__}")


def _canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        _json_safe(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_json_bytes(value)).hexdigest()


def _serialize_document(document: TextDocument) -> Dict[str, Any]:
    return {
        "page_content": str(document.content or ""),
        "metadata": _json_safe(document.metadata or {}),
    }


class RetrievalCacheStore:
    """Load and save data-only hybrid index snapshots."""

    def __init__(self, config):
        self.config = config
        self.storage = config.storage
        self.models = config.models
        self.graph = config.graph

    def signature(self, chunks: List[TextDocument]) -> str:
        return _sha256(
            {
                "schema_version": HYBRID_CACHE_SCHEMA_VERSION,
                "semantic_schema_version": SEMANTIC_SCHEMA_VERSION,
                "graph_index_version": GRAPH_INDEX_VERSION,
                "models": {
                    "embedding_model": str(self.models.embedding_model),
                    "embedding_dimension": int(self.models.embedding_dimension),
                    "llm_model": str(self.models.llm_model),
                    "rerank_model": str(self.models.rerank_model),
                },
                "chunking": {
                    "chunk_size": int(self.graph.chunk_size),
                    "chunk_overlap": int(self.graph.chunk_overlap),
                },
                "chunks": [_serialize_document(document) for document in chunks or []],
            }
        )

    def path(self) -> str:
        cache_dir = str(self.storage.index_cache_dir)
        os.makedirs(cache_dir, exist_ok=True)
        return os.path.join(cache_dir, "hybrid_index.json")

    def load(self, chunks: List[TextDocument]) -> Optional[Dict[str, Any]]:
        path = self.path()
        if not os.path.isfile(path):
            return None
        try:
            if os.path.getsize(path) > _MAX_CACHE_BYTES:
                raise ValueError("hybrid cache exceeds the maximum supported size")
            with open(path, "r", encoding="utf-8") as file:
                envelope = json.load(file)
            if not isinstance(envelope, dict):
                raise ValueError("hybrid cache envelope must be a JSON object")
            if envelope.get("schema_version") != HYBRID_CACHE_SCHEMA_VERSION:
                logger.info("Hybrid cache schema changed; rebuilding indexes.")
                return None

            expected_source_signature = self.signature(chunks)
            source_signature = str(envelope.get("source_signature") or "")
            if not hmac.compare_digest(source_signature, expected_source_signature):
                logger.info("Hybrid cache source signature mismatch; rebuilding indexes.")
                return None

            artifacts = envelope.get("artifacts")
            if not isinstance(artifacts, dict):
                raise ValueError("hybrid cache artifacts must be a JSON object")
            expected_artifact_digest = str(envelope.get("artifacts_sha256") or "")
            actual_artifact_digest = _sha256(artifacts)
            if not hmac.compare_digest(expected_artifact_digest, actual_artifact_digest):
                logger.warning("Hybrid cache content digest mismatch; rebuilding indexes.")
                return None
            return artifacts
        except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
            log_failure(
                logger,
                logging.WARNING,
                "retrieval_operation_failed",
                code="RETRIEVAL_FAILED",
                error=exc,
            )
            return None

    def save(self, chunks: List[TextDocument], payload: Dict[str, Any]) -> None:
        path = self.path()
        try:
            artifacts = _json_safe(dict(payload or {}))
            envelope = {
                "schema_version": HYBRID_CACHE_SCHEMA_VERSION,
                "source_signature": self.signature(chunks),
                "artifacts_sha256": _sha256(artifacts),
                "artifacts": artifacts,
            }
            write_json_atomic(path, envelope)
            logger.info("Hybrid index cache saved")
        except (OSError, TypeError, ValueError) as exc:
            log_failure(
                logger,
                logging.WARNING,
                "retrieval_operation_failed",
                code="RETRIEVAL_FAILED",
                error=exc,
            )


__all__ = ["HYBRID_CACHE_SCHEMA_VERSION", "RetrievalCacheStore"]
