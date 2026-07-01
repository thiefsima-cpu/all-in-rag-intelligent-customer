"""Neo4j graph-loading routines for recipe build artifacts."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict, List

from ...runtime_contracts import Neo4jDriverPort
from .models import GraphNode

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

    recipes: List[GraphNode]
    ingredients: List[GraphNode]
    cooking_steps: List[GraphNode]

    def to_counts(self) -> Dict[str, int]:
        return {
            "recipes": len(self.recipes),
            "ingredients": len(self.ingredients),
            "cooking_steps": len(self.cooking_steps),
        }


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

    def _load_recipes(self, session: Any) -> List[GraphNode]:
        recipes: List[GraphNode] = []
        for record in session.run(RECIPES_QUERY):
            properties = dict(record["originalProperties"] or {})
            properties["category"] = record["mainCategory"]
            properties["all_categories"] = record["allCategories"]
            recipes.append(
                GraphNode(
                    node_id=str(record["nodeId"]),
                    labels=list(record["labels"] or []),
                    name=str(record["name"] or ""),
                    properties=properties,
                )
            )
        logger.info("Loaded %d recipe nodes.", len(recipes))
        return recipes

    def _load_ingredients(self, session: Any) -> List[GraphNode]:
        ingredients = [
            GraphNode(
                node_id=str(record["nodeId"]),
                labels=list(record["labels"] or []),
                name=str(record["name"] or ""),
                properties=dict(record["properties"] or {}),
            )
            for record in session.run(INGREDIENTS_QUERY)
        ]
        logger.info("Loaded %d ingredient nodes.", len(ingredients))
        return ingredients

    def _load_cooking_steps(self, session: Any) -> List[GraphNode]:
        cooking_steps = [
            GraphNode(
                node_id=str(record["nodeId"]),
                labels=list(record["labels"] or []),
                name=str(record["name"] or ""),
                properties=dict(record["properties"] or {}),
            )
            for record in session.run(COOKING_STEPS_QUERY)
        ]
        logger.info("Loaded %d cooking-step nodes.", len(cooking_steps))
        return cooking_steps
