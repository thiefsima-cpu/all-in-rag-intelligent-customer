"""Schema sync decisions for knowledge-base build workflow."""

from __future__ import annotations

import logging
from typing import Protocol

from ..configuration.models import GraphRAGConfig
from ..runtime_contracts import GraphDataModulePort
from .contracts import SemanticGraphSchemaSyncPort, SemanticGraphSchemaSyncResult
from .stats_presenter import ProgressCallback

logger = logging.getLogger(__name__)


class _KnowledgeBaseSchemaSyncHost(Protocol):
    config: GraphRAGConfig
    data_module: GraphDataModulePort
    semantic_graph_schema_sync: SemanticGraphSchemaSyncPort

    @staticmethod
    def _emit(progress: ProgressCallback, message: str) -> None: ...


class _KnowledgeBaseSchemaSyncMixin(_KnowledgeBaseSchemaSyncHost):
    """Own semantic schema sync and build metadata construction."""

    def _sync_semantic_graph_schema(
        self,
        progress: ProgressCallback = None,
    ) -> SemanticGraphSchemaSyncResult:
        if not self.config.graph.enable_semantic_graph_schema:
            return SemanticGraphSchemaSyncResult(enabled=False)
        self._emit(progress, "Syncing semantic graph schema...")
        try:
            result = self.semantic_graph_schema_sync.sync_from_documents(
                self.data_module.documents or []
            )
            self._emit(
                progress,
                "[OK] Semantic graph schema synced: "
                f"recipes={result.recipes}, "
                f"semantic_nodes={result.nodes}, "
                f"semantic_relationships={result.relationships}",
            )
            return result
        except Exception:
            logger.warning("Semantic graph schema sync failed.")
            self._emit(progress, "[WARN] Semantic graph schema sync failed. Continuing startup.")
            return SemanticGraphSchemaSyncResult(
                enabled=True,
                error="SEMANTIC_SCHEMA_SYNC_FAILED",
            )

    def _build_metadata(
        self, document_result, schema_sync_result: SemanticGraphSchemaSyncResult
    ) -> dict:
        return {
            "config_profile": {
                "name": getattr(self.config, "profile_name", ""),
                "path": getattr(self.config, "profile_path", ""),
                "hash": getattr(self.config, "profile_hash", ""),
            },
            "document_cache_hit": document_result.cache_hit,
            "semantic_graph_schema": schema_sync_result.to_metadata(),
        }


__all__ = ["_KnowledgeBaseSchemaSyncMixin"]
