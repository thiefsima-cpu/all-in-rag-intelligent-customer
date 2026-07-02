"""Neo4j graph-loading routines for recipe build artifacts."""

from __future__ import annotations

import logging
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol

from ...runtime.json_types import coerce_json_object, coerce_json_value
from ...runtime_contracts import Neo4jDriverPort
from .models import GraphLoadCounts, GraphNode

logger = logging.getLogger(__name__)

UNKNOWN_VALUE = "未知"

RECIPES_QUERY = """
MATCH (r:Recipe)
WHERE r.nodeId >= '200000000'
  AND coalesce(r.createdFrom, '') <> 'semantic_schema'
OPTIONAL MATCH (r)-[:BELONGS_TO_CATEGORY]->(c:Category)
WITH r, collect(c.name) AS categories
RETURN r.nodeId AS nodeId,
       labels(r) AS labels,
       r.name AS name,
       properties(r) AS originalProperties,
       CASE WHEN size(categories) > 0
            THEN categories[0]
            ELSE COALESCE(r.category, '未知') END AS mainCategory,
       CASE WHEN size(categories) > 0
            THEN categories
            ELSE [COALESCE(r.category, '未知')] END AS allCategories
ORDER BY r.nodeId
"""

INGREDIENTS_QUERY = """
MATCH (i:Ingredient)
WHERE i.nodeId >= '200000000'
  AND coalesce(i.createdFrom, '') <> 'semantic_schema'
RETURN i.nodeId AS nodeId,
       labels(i) AS labels,
       i.name AS name,
       properties(i) AS properties
ORDER BY i.nodeId
"""

COOKING_STEPS_QUERY = """
MATCH (s:CookingStep)
WHERE s.nodeId >= '200000000'
  AND coalesce(s.createdFrom, '') <> 'semantic_schema'
RETURN s.nodeId AS nodeId,
       labels(s) AS labels,
       s.name AS name,
       properties(s) AS properties
ORDER BY s.nodeId
"""


@dataclass(slots=True)
class LoadedGraphData:
    """Loaded graph node collections ready for document materialization."""

    recipes: list[GraphNode]
    ingredients: list[GraphNode]
    cooking_steps: list[GraphNode]

    def to_counts(self) -> GraphLoadCounts:
        return GraphLoadCounts(
            recipes=len(self.recipes),
            ingredients=len(self.ingredients),
            cooking_steps=len(self.cooking_steps),
        )


class Neo4jSessionLike(Protocol):
    """Neo4j session surface used by graph-preparation loaders."""

    def run(
        self,
        query: str,
        parameters: Mapping[str, object] | None = None,
    ) -> Iterable[Mapping[str, object]]: ...


class Neo4jGraphDataLoader:
    """Load recipe, ingredient, and cooking-step nodes from Neo4j."""

    def load(self, driver: Neo4jDriverPort, *, database: str) -> LoadedGraphData:
        logger.info("Loading graph data from Neo4j...")
        with driver.session(database=database) as session:
            recipes = self._load_recipes(session)
            ingredients = self._load_ingredients(session)
            cooking_steps = self._load_cooking_steps(session)
        return LoadedGraphData(
            recipes=recipes,
            ingredients=ingredients,
            cooking_steps=cooking_steps,
        )

    def _load_recipes(self, session: Neo4jSessionLike) -> list[GraphNode]:
        recipes: list[GraphNode] = []
        for record in session.run(RECIPES_QUERY):
            properties = coerce_json_object(record.get("originalProperties"))
            properties["category"] = str(record.get("mainCategory") or UNKNOWN_VALUE)
            properties["all_categories"] = coerce_json_value(
                _string_list(record.get("allCategories"))
            )
            recipes.append(
                GraphNode(
                    node_id=str(record.get("nodeId") or ""),
                    labels=_string_list(record.get("labels")),
                    name=str(record.get("name") or ""),
                    properties=properties,
                )
            )
        logger.info("Loaded %d recipe nodes.", len(recipes))
        return recipes

    def _load_ingredients(self, session: Neo4jSessionLike) -> list[GraphNode]:
        ingredients = [
            GraphNode(
                node_id=str(record.get("nodeId") or ""),
                labels=_string_list(record.get("labels")),
                name=str(record.get("name") or ""),
                properties=coerce_json_object(record.get("properties")),
            )
            for record in session.run(INGREDIENTS_QUERY)
        ]
        logger.info("Loaded %d ingredient nodes.", len(ingredients))
        return ingredients

    def _load_cooking_steps(self, session: Neo4jSessionLike) -> list[GraphNode]:
        cooking_steps = [
            GraphNode(
                node_id=str(record.get("nodeId") or ""),
                labels=_string_list(record.get("labels")),
                name=str(record.get("name") or ""),
                properties=coerce_json_object(record.get("properties")),
            )
            for record in session.run(COOKING_STEPS_QUERY)
        ]
        logger.info("Loaded %d cooking-step nodes.", len(cooking_steps))
        return cooking_steps


def _string_list(value: object) -> list[str]:
    if isinstance(value, str):
        return [value] if value else []
    if isinstance(value, Sequence):
        return [str(item) for item in value if str(item)]
    return []
