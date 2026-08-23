"""Build-side orchestration wrapper for semantic graph schema persistence."""

from __future__ import annotations

from typing import Sequence

from ..domains import get_domain_pack
from ..kernel.documents import TextDocument
from .contracts import SemanticGraphSchemaSyncResult


class SemanticGraphSchemaSyncService:
    """Persist semantic graph schema through the graph-domain writer boundary."""

    def __init__(self, config, *, neo4j_manager=None) -> None:
        self.config = config
        self.neo4j_manager = neo4j_manager

    def sync_from_documents(
        self,
        documents: Sequence[TextDocument],
    ) -> SemanticGraphSchemaSyncResult:
        pack = get_domain_pack(self.config.domain.name)
        writer_factory = pack.semantic_graph_writer_factory
        if not pack.semantic_schema_enabled or writer_factory is None:
            return SemanticGraphSchemaSyncResult(enabled=False)
        writer = writer_factory(self.config, neo4j_manager=self.neo4j_manager)
        persist = getattr(writer, "persist_from_documents")
        stats = persist(list(documents or []))
        return SemanticGraphSchemaSyncResult(
            enabled=True,
            source_entities=int(stats.get(pack.semantic_schema_count_field, 0) or 0),
            nodes=int(stats.get("nodes", 0) or 0),
            relationships=int(stats.get("relationships", 0) or 0),
        )


__all__ = ["SemanticGraphSchemaSyncService"]
