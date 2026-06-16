"""Statistics collection for materialized document artifacts."""

from __future__ import annotations

from .models import DocumentArtifactStats


class DocumentArtifactStatsCollector:
    """Collect stable counts from the build-time document preparation state."""

    def collect(self, data_module) -> DocumentArtifactStats:
        stats = data_module.get_statistics() if hasattr(data_module, "get_statistics") else {}
        return DocumentArtifactStats(
            total_recipes=int(stats.get("total_recipes", len(getattr(data_module, "recipes", []) or []))),
            total_ingredients=int(
                stats.get("total_ingredients", len(getattr(data_module, "ingredients", []) or []))
            ),
            total_cooking_steps=int(
                stats.get("total_cooking_steps", len(getattr(data_module, "cooking_steps", []) or []))
            ),
            total_documents=int(stats.get("total_documents", len(getattr(data_module, "documents", []) or []))),
            total_chunks=int(stats.get("total_chunks", len(getattr(data_module, "chunks", []) or []))),
        )
