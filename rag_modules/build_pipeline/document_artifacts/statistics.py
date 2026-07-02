"""Statistics collection for materialized document artifacts."""

from __future__ import annotations

from ...runtime.json_types import coerce_json_object
from .models import DocumentArtifactStats


class DocumentArtifactStatsCollector:
    """Collect stable counts from the build-time document preparation state."""

    def collect(self, data_module) -> DocumentArtifactStats:
        raw_stats = data_module.get_statistics() if hasattr(data_module, "get_statistics") else {}
        stats = coerce_json_object(raw_stats)
        return DocumentArtifactStats(
            total_recipes=_count_value(
                stats.get("total_recipes"),
                len(getattr(data_module, "recipes", []) or []),
            ),
            total_ingredients=_count_value(
                stats.get("total_ingredients"),
                len(getattr(data_module, "ingredients", []) or []),
            ),
            total_cooking_steps=_count_value(
                stats.get(
                    "total_cooking_steps",
                ),
                len(getattr(data_module, "cooking_steps", []) or []),
            ),
            total_documents=_count_value(
                stats.get("total_documents"),
                len(getattr(data_module, "documents", []) or []),
            ),
            total_chunks=_count_value(
                stats.get("total_chunks"),
                len(getattr(data_module, "chunks", []) or []),
            ),
        )


def _count_value(value: object, default: int) -> int:
    if isinstance(value, (bool, int, float, str)):
        try:
            return int(value)
        except (TypeError, ValueError):
            return default
    return default
