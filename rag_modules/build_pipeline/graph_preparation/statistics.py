"""Statistics helpers for graph-preparation state."""

from __future__ import annotations

from dataclasses import dataclass, field

from ...runtime.json_types import JsonObject
from .state import GraphPreparationState

UNKNOWN_VALUE = "未知"


@dataclass(slots=True, frozen=True)
class GraphPreparationStats:
    """Stable graph-preparation statistics with JSON serialization."""

    total_recipes: int = 0
    total_ingredients: int = 0
    total_cooking_steps: int = 0
    total_documents: int = 0
    total_chunks: int = 0
    categories: dict[str, int] = field(default_factory=dict)
    cuisines: dict[str, int] = field(default_factory=dict)
    difficulties: dict[str, int] = field(default_factory=dict)
    avg_content_length: float = 0.0
    avg_chunk_size: float = 0.0
    include_distributions: bool = False

    def to_dict(self) -> JsonObject:
        payload: JsonObject = {
            "total_recipes": self.total_recipes,
            "total_ingredients": self.total_ingredients,
            "total_cooking_steps": self.total_cooking_steps,
            "total_documents": self.total_documents,
            "total_chunks": self.total_chunks,
        }
        if not self.include_distributions:
            return payload
        payload.update(
            {
                "categories": dict(self.categories),
                "cuisines": dict(self.cuisines),
                "difficulties": dict(self.difficulties),
                "avg_content_length": self.avg_content_length,
                "avg_chunk_size": self.avg_chunk_size,
            }
        )
        return payload


class GraphPreparationStatisticsService:
    """Compute stable build-time diagnostics from preparation state."""

    def build(self, state: GraphPreparationState) -> GraphPreparationStats:
        if not state.documents:
            return GraphPreparationStats(
                total_recipes=len(state.recipes),
                total_ingredients=len(state.ingredients),
                total_cooking_steps=len(state.cooking_steps),
                total_documents=len(state.documents),
                total_chunks=len(state.chunks),
            )

        categories: dict[str, int] = {}
        cuisines: dict[str, int] = {}
        difficulties: dict[str, int] = {}

        for document in state.documents:
            category = str(document.metadata.get("category", UNKNOWN_VALUE) or UNKNOWN_VALUE)
            categories[category] = categories.get(category, 0) + 1

            cuisine = str(document.metadata.get("cuisine_type", UNKNOWN_VALUE) or UNKNOWN_VALUE)
            cuisines[cuisine] = cuisines.get(cuisine, 0) + 1

            difficulty = str(document.metadata.get("difficulty", 0))
            difficulties[difficulty] = difficulties.get(difficulty, 0) + 1

        return GraphPreparationStats(
            total_recipes=len(state.recipes),
            total_ingredients=len(state.ingredients),
            total_cooking_steps=len(state.cooking_steps),
            total_documents=len(state.documents),
            total_chunks=len(state.chunks),
            categories=categories,
            cuisines=cuisines,
            difficulties=difficulties,
            avg_content_length=sum(
                int(document.metadata.get("content_length", 0) or 0) for document in state.documents
            )
            / len(state.documents),
            avg_chunk_size=(
                sum(int(chunk.metadata.get("chunk_size", 0) or 0) for chunk in state.chunks)
                / len(state.chunks)
                if state.chunks
                else 0.0
            ),
            include_distributions=True,
        )
