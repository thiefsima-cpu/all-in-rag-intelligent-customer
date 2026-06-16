"""Config-derived settings for document artifact caching."""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(slots=True)
class DocumentArtifactSettings:
    enable_index_cache: bool
    cache_dir: str
    chunk_size: int
    chunk_overlap: int
    embedding_model: str
    embedding_dimension: int
    embedding_base_url: str
    collection_name: str

    @property
    def documents_path(self) -> str:
        return os.path.join(self.cache_dir, "documents.json")

    @property
    def chunks_path(self) -> str:
        return os.path.join(self.cache_dir, "chunks.json")

    @classmethod
    def from_config(cls, config) -> "DocumentArtifactSettings":
        storage = config.storage
        graph = config.graph
        models = config.models
        return cls(
            enable_index_cache=bool(storage.enable_index_cache),
            cache_dir=str(storage.index_cache_dir),
            chunk_size=int(graph.chunk_size),
            chunk_overlap=int(graph.chunk_overlap),
            embedding_model=str(models.embedding_model),
            embedding_dimension=int(models.embedding_dimension),
            embedding_base_url=str(models.embedding_base_url),
            collection_name=str(storage.milvus_collection_name),
        )
