"""Neutral graph-preparation data contracts shared across subsystems."""

from __future__ import annotations

from dataclasses import dataclass, field

from ..kernel.json_types import JsonObject


@dataclass(slots=True)
class GraphNode:
    """Structured graph node data loaded from Neo4j."""

    node_id: str
    labels: list[str] = field(default_factory=list)
    name: str = ""
    properties: JsonObject = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.node_id = str(self.node_id or "")
        self.labels = [str(label) for label in (self.labels or []) if str(label)]
        self.name = str(self.name or "")
        self.properties = dict(self.properties or {})


@dataclass(slots=True, frozen=True)
class GraphLoadCounts:
    """Counts of graph nodes loaded into preparation state."""

    recipes: int = 0
    ingredients: int = 0
    cooking_steps: int = 0

    def to_dict(self) -> JsonObject:
        return {
            "recipes": self.recipes,
            "ingredients": self.ingredients,
            "cooking_steps": self.cooking_steps,
        }


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


__all__ = ["GraphLoadCounts", "GraphNode", "GraphPreparationStats"]
