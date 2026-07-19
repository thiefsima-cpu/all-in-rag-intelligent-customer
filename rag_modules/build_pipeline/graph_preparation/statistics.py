"""Statistics helpers for graph-preparation state."""

from __future__ import annotations

from ...contracts.graph_preparation import GraphPreparationStats as _GraphPreparationStats
from .state import GraphPreparationState

UNKNOWN_VALUE = "未知"


class GraphPreparationStatisticsService:
    """Compute stable build-time diagnostics from preparation state."""

    def __init__(self, *, domain_name: str = "recipe") -> None:
        self.domain_name = str(domain_name or "recipe")

    def build(self, state: GraphPreparationState) -> _GraphPreparationStats:
        if self.domain_name != "recipe":
            return self._build_domain_stats(state)
        if not state.documents:
            return _GraphPreparationStats(
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

        return _GraphPreparationStats(
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

    def _build_domain_stats(self, state: GraphPreparationState) -> _GraphPreparationStats:
        entities = state.recipes + state.ingredients + state.cooking_steps
        entity_types: dict[str, int] = {}
        for entity in entities:
            for label in entity.labels:
                entity_types[label] = entity_types.get(label, 0) + 1
        document_types: dict[str, int] = {}
        for document in state.documents:
            document_type = str(
                document.metadata.get("document_type")
                or document.metadata.get("doc_type")
                or UNKNOWN_VALUE
            )
            document_types[document_type] = document_types.get(document_type, 0) + 1
        return _GraphPreparationStats(
            domain_name=self.domain_name,
            total_entities=len(entities),
            total_documents=len(state.documents),
            total_chunks=len(state.chunks),
            entity_types=entity_types,
            document_types=document_types,
            avg_content_length=(
                sum(
                    int(document.metadata.get("content_length", 0) or 0)
                    for document in state.documents
                )
                / len(state.documents)
                if state.documents
                else 0.0
            ),
            avg_chunk_size=(
                sum(int(chunk.metadata.get("chunk_size", 0) or 0) for chunk in state.chunks)
                / len(state.chunks)
                if state.chunks
                else 0.0
            ),
            include_distributions=bool(state.documents),
        )
