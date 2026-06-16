"""Signature collection for document artifact manifests."""

from __future__ import annotations

from ...artifacts import (
    compute_document_signature,
    compute_embedding_signature,
    compute_graph_signature,
    compute_index_signature,
)
from .models import DocumentArtifactSignatures
from .settings import DocumentArtifactSettings


class DocumentArtifactSignatureCollector:
    """Collect the signatures that bind graph, documents, and vector index."""

    def __init__(self, settings: DocumentArtifactSettings) -> None:
        self.settings = settings

    def collect(self, data_module) -> DocumentArtifactSignatures:
        graph_signature = compute_graph_signature(data_module)
        document_signature = compute_document_signature(
            graph_signature=graph_signature,
            chunk_size=self.settings.chunk_size,
            chunk_overlap=self.settings.chunk_overlap,
        )
        embedding_signature = compute_embedding_signature(
            model_name=self.settings.embedding_model,
            dimension=self.settings.embedding_dimension,
            base_url=self.settings.embedding_base_url,
        )
        index_signature = compute_index_signature(
            document_signature=document_signature,
            embedding_signature=embedding_signature,
            collection_name=self.settings.collection_name,
        )
        return DocumentArtifactSignatures(
            graph_signature=graph_signature,
            document_signature=document_signature,
            embedding_signature=embedding_signature,
            index_signature=index_signature,
        )
