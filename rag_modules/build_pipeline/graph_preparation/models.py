"""Graph data models used by the build pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field

from ...kernel.json_types import JsonObject


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
