"""Schema sync decisions for knowledge-base build workflow."""

from __future__ import annotations

import logging

from .contracts import SemanticGraphSchemaSyncResult
from .stats_presenter import ProgressCallback

logger = logging.getLogger(__name__)


class _KnowledgeBaseSchemaSyncMixin:
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
        except Exception as exc:
            logger.warning("Semantic graph schema sync failed: %s", exc)
            self._emit(
                progress, f"[WARN] Semantic graph schema sync failed. Continuing startup: {exc}"
            )
            return SemanticGraphSchemaSyncResult(enabled=True, error=str(exc))

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
