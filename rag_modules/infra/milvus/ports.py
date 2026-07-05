"""Ports consumed by the Milvus infrastructure adapter."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol


class EmbeddingClientPort(Protocol):
    """Provider-neutral embedding behavior consumed by Milvus indexing/search."""

    def embed_query(self, text: str, *, timeout_seconds: float | None = None) -> list[float]: ...

    def embed_documents(
        self,
        texts: Sequence[str],
        *,
        timeout_seconds: float | None = None,
    ) -> list[list[float]]: ...


__all__ = ["EmbeddingClientPort"]
