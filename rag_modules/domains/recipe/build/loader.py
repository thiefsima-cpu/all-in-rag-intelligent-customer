"""Neo4j graph-loading routines for recipe build artifacts."""

from __future__ import annotations

import logging
from collections.abc import Sequence

from ....contracts.graph_preparation import GraphNode, LoadedGraphData
from ....kernel.json_types import coerce_json_object, coerce_json_value

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


class Neo4jGraphDataLoader:
    """Load recipe, ingredient, and cooking-step nodes from Neo4j."""

    def load(self, driver: object, *, database: str) -> LoadedGraphData:
        logger.info("Loading graph data from Neo4j...")
        with getattr(driver, "session")(database=database) as session:
            recipes = self._load_recipes(session)
            ingredients = self._load_ingredients(session)
            cooking_steps = self._load_cooking_steps(session)
        return LoadedGraphData(
            primary_entities=recipes,
            primary_group="recipes",
            related_entity_groups={
                "ingredients": ingredients,
                "cooking_steps": cooking_steps,
            },
        )

    def _load_recipes(self, session: object) -> list[GraphNode]:
        recipes: list[GraphNode] = []
        for record in getattr(session, "run")(RECIPES_QUERY):
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

    def _load_ingredients(self, session: object) -> list[GraphNode]:
        ingredients = [
            GraphNode(
                node_id=str(record.get("nodeId") or ""),
                labels=_string_list(record.get("labels")),
                name=str(record.get("name") or ""),
                properties=coerce_json_object(record.get("properties")),
            )
            for record in getattr(session, "run")(INGREDIENTS_QUERY)
        ]
        logger.info("Loaded %d ingredient nodes.", len(ingredients))
        return ingredients

    def _load_cooking_steps(self, session: object) -> list[GraphNode]:
        cooking_steps = [
            GraphNode(
                node_id=str(record.get("nodeId") or ""),
                labels=_string_list(record.get("labels")),
                name=str(record.get("name") or ""),
                properties=coerce_json_object(record.get("properties")),
            )
            for record in getattr(session, "run")(COOKING_STEPS_QUERY)
        ]
        logger.info("Loaded %d cooking-step nodes.", len(cooking_steps))
        return cooking_steps


def _string_list(value: object) -> list[str]:
    if isinstance(value, str):
        return [value] if value else []
    if isinstance(value, Sequence):
        return [str(item) for item in value if str(item)]
    return []
