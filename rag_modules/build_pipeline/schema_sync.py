"""Build-side orchestration wrapper for semantic graph schema persistence."""

from __future__ import annotations

from typing import Sequence

from ..infra.semantic_graph_writer import SemanticGraphSchemaWriter
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
        domain = getattr(self.config, "domain", None)
        domain_name = str(getattr(domain, "name", "recipe") or "recipe")
        if domain_name != "recipe":
            # Non-recipe graphs already conform to the selected DomainPack ontology.
            # The legacy writer below derives recipe-only Flavor/Technique nodes.
            return SemanticGraphSchemaSyncResult(enabled=False)
        writer = SemanticGraphSchemaWriter(self.config, neo4j_manager=self.neo4j_manager)
        stats = writer.persist_from_documents(list(documents or []))
        return SemanticGraphSchemaSyncResult(
            enabled=True,
            recipes=int(stats.get("recipes", 0) or 0),
            nodes=int(stats.get("nodes", 0) or 0),
            relationships=int(stats.get("relationships", 0) or 0),
        )


__all__ = ["SemanticGraphSchemaSyncService"]
