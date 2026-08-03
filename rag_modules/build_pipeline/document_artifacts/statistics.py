"""Statistics collection for materialized document artifacts."""

from __future__ import annotations

from ...contracts.graph_preparation import GraphPreparationStats
from ...kernel.artifacts import DocumentArtifactStats
from ...kernel.json_types import coerce_json_object


class DocumentArtifactStatsCollector:
    """Collect stable counts from the build-time document preparation state."""

    def collect(self, data_module) -> DocumentArtifactStats:
        raw_stats = data_module.get_statistics() if hasattr(data_module, "get_statistics") else {}
        stats = coerce_json_object(
            raw_stats.to_dict() if isinstance(raw_stats, GraphPreparationStats) else raw_stats
        )
        return DocumentArtifactStats(
            total_entities=_count_value(
                stats.get("total_entities"),
                len(getattr(data_module, "entities", []) or []),
            ),
            total_documents=_count_value(
                stats.get("total_documents"),
                len(getattr(data_module, "documents", []) or []),
            ),
            total_chunks=_count_value(
                stats.get("total_chunks"),
                len(getattr(data_module, "chunks", []) or []),
            ),
            domain_metrics=coerce_json_object(stats.get("domain_metrics")),
        )


def _count_value(value: object, default: int) -> int:
    if isinstance(value, (bool, int, float, str)):
        try:
            return int(value)
        except (TypeError, ValueError):
            return default
    return default
