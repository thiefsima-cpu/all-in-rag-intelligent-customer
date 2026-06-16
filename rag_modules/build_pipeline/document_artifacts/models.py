"""Runtime models for document artifact caching and build orchestration."""

from __future__ import annotations

from dataclasses import dataclass
from typing import List

from ...artifacts import ArtifactManifest
from ...text_document import TextDocument


@dataclass(slots=True)
class DocumentArtifactResult:
    documents: List[TextDocument]
    chunks: List[TextDocument]
    manifest: ArtifactManifest
    cache_hit: bool


@dataclass(slots=True)
class DocumentArtifactSignatures:
    graph_signature: str
    document_signature: str
    embedding_signature: str
    index_signature: str


@dataclass(slots=True)
class DocumentArtifactStats:
    total_recipes: int
    total_ingredients: int
    total_cooking_steps: int
    total_documents: int
    total_chunks: int
