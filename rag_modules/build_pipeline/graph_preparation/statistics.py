"""Statistics helpers for graph-preparation state."""

from __future__ import annotations

from typing import Any, Dict

from .state import GraphPreparationState

UNKNOWN_VALUE = "未知"


class GraphPreparationStatisticsService:
    """Compute stable build-time diagnostics from preparation state."""

    def build(self, state: GraphPreparationState) -> Dict[str, Any]:
        stats: Dict[str, Any] = {
            "total_recipes": len(state.recipes),
            "total_ingredients": len(state.ingredients),
            "total_cooking_steps": len(state.cooking_steps),
            "total_documents": len(state.documents),
            "total_chunks": len(state.chunks),
        }
        if not state.documents:
            return stats

        categories: Dict[str, int] = {}
        cuisines: Dict[str, int] = {}
        difficulties: Dict[str, int] = {}

        for document in state.documents:
            category = str(document.metadata.get("category", UNKNOWN_VALUE) or UNKNOWN_VALUE)
            categories[category] = categories.get(category, 0) + 1

            cuisine = str(document.metadata.get("cuisine_type", UNKNOWN_VALUE) or UNKNOWN_VALUE)
            cuisines[cuisine] = cuisines.get(cuisine, 0) + 1

            difficulty = str(document.metadata.get("difficulty", 0))
            difficulties[difficulty] = difficulties.get(difficulty, 0) + 1

        stats.update(
            {
                "categories": categories,
                "cuisines": cuisines,
                "difficulties": difficulties,
                "avg_content_length": sum(
                    int(document.metadata.get("content_length", 0) or 0)
                    for document in state.documents
                )
                / len(state.documents),
                "avg_chunk_size": (
                    sum(int(chunk.metadata.get("chunk_size", 0) or 0) for chunk in state.chunks)
                    / len(state.chunks)
                    if state.chunks
                    else 0
                ),
            }
        )
        return stats
