"""Graph data models used by the build pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field

from ...runtime.json_types import JsonObject


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


@dataclass(slots=True)
class GraphRelation:
    """Structured graph relationship data loaded from Neo4j."""

    start_node_id: str
    end_node_id: str
    relation_type: str
    properties: JsonObject = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.start_node_id = str(self.start_node_id or "")
        self.end_node_id = str(self.end_node_id or "")
        self.relation_type = str(self.relation_type or "")
        self.properties = dict(self.properties or {})


@dataclass(slots=True, frozen=True)
class GraphLoadCounts:
    """Counts of graph nodes loaded into the preparation state."""

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
class PreparedIngredientInput:
    """Ingredient row prepared for recipe-document materialization."""

    recipe_id: str
    name: str = ""
    category: str = ""
    amount: str = ""
    unit: str = ""
    description: str = ""


@dataclass(slots=True, frozen=True)
class PreparedStepInput:
    """Cooking-step row prepared for recipe-document materialization."""

    recipe_id: str
    name: str = ""
    description: str = ""
    step_number: int = 0
    methods: str = ""
    tools: str = ""
    time_estimate: str = ""
    step_order: int = 0


GraphNode.__module__ = "rag_modules.graph.data_preparation"
GraphRelation.__module__ = "rag_modules.graph.data_preparation"
