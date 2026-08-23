"""
Persist derived semantic recipe schema into Neo4j.

The document builder infers lightweight semantic tags from recipe text. This
module turns those tags into idempotent graph nodes/edges so GraphRAG traversal
can use them directly instead of relying only on virtual in-memory relations.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from typing import Any, Dict, Iterable, List, cast

from ...kernel.documents import TextDocument
from ...kernel.json_types import JsonObject, coerce_int, coerce_json_object
from ...kernel.semantic_schema import SEMANTIC_SCHEMA_VERSION
from .semantic_schema import SEMANTIC_NODE_LABELS, SEMANTIC_RELATION_TYPES

logger = logging.getLogger(__name__)


def _dedupe_strings(values: Iterable[object]) -> List[str]:
    seen = set()
    out = []
    for value in values or []:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        out.append(text)
    return out


def _json_object_items(value: object) -> list[JsonObject]:
    if not isinstance(value, list):
        return []
    return [coerce_json_object(item) for item in value if isinstance(item, Mapping)]


def _json_value_items(value: object) -> list[object]:
    if not isinstance(value, list):
        return []
    return list(value)


class SemanticGraphSchemaWriter:
    """Write semantic schema nodes and relationships to Neo4j."""

    def __init__(
        self,
        config,
        neo4j_manager: object | None = None,
        driver_factory: Callable[..., object] | None = None,
    ):
        self.config = config
        self.storage = config.storage
        self.graph = config.graph
        self.neo4j_manager = neo4j_manager
        self.driver_factory = driver_factory
        self.driver: object | None = None
        self._owns_driver = False

    def __enter__(self) -> "SemanticGraphSchemaWriter":
        if self.neo4j_manager is not None:
            self.driver = getattr(self.neo4j_manager, "driver")
        elif self.driver_factory is not None:
            self.driver = self.driver_factory(
                self.storage.neo4j_uri,
                self.storage.neo4j_user,
                self.storage.neo4j_password,
            )
            self._owns_driver = True
        else:
            raise RuntimeError("Semantic graph writer requires a Neo4j manager or driver factory.")
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def close(self) -> None:
        if self._owns_driver and self.driver:
            getattr(self.driver, "close")()
            self.driver = None
            self._owns_driver = False

    def persist_from_documents(self, documents: List[TextDocument]) -> Dict[str, int]:
        if not self.graph.enable_semantic_graph_schema:
            logger.info("Semantic graph schema sync is disabled.")
            return {"recipes": 0, "nodes": 0, "relationships": 0}
        if not documents:
            return {"recipes": 0, "nodes": 0, "relationships": 0}

        opened_here = False
        if self.driver is None:
            if self.neo4j_manager is not None:
                self.driver = getattr(self.neo4j_manager, "driver")
            elif self.driver_factory is not None:
                self.driver = self.driver_factory(
                    self.storage.neo4j_uri,
                    self.storage.neo4j_user,
                    self.storage.neo4j_password,
                )
                self._owns_driver = True
                opened_here = True
            else:
                raise RuntimeError(
                    "Semantic graph writer requires a Neo4j manager or driver factory."
                )

        rows = self._build_rows(documents)
        if not rows:
            if opened_here:
                self.close()
            return {"recipes": 0, "nodes": 0, "relationships": 0}

        driver = self.driver
        if driver is None:
            raise RuntimeError("Neo4j driver is not initialized.")

        try:
            with getattr(driver, "session")(database=self.storage.neo4j_database) as session:
                self._ensure_constraints(session)
                result = cast(Dict[str, int], session.execute_write(self._write_rows, rows))
            logger.info("Semantic graph schema sync complete: %s", result)
            return result
        finally:
            if opened_here:
                self.close()

    def _build_rows(self, documents: List[TextDocument]) -> List[Dict[str, Any]]:
        rows = []
        for doc in documents:
            metadata = doc.metadata or {}
            recipe_id = str(metadata.get("node_id") or metadata.get("recipe_id") or "").strip()
            recipe_name = str(metadata.get("recipe_name") or "").strip()
            if not recipe_id:
                continue

            semantic_relations = coerce_json_object(metadata.get("semantic_relations"))
            relations = []
            for rel_type in SEMANTIC_RELATION_TYPES:
                if rel_type == "CONTRIBUTES_TO":
                    for item in _json_object_items(semantic_relations.get(rel_type)):
                        effect = str(item.get("effect") or "").strip()
                        if not effect:
                            continue
                        relations.append(
                            {
                                "rel_type": rel_type,
                                "label": SEMANTIC_NODE_LABELS[rel_type],
                                "name": effect,
                                "causes": _dedupe_strings(_json_value_items(item.get("causes"))),
                            }
                        )
                    continue
                if rel_type in {"INGREDIENT_CONTRIBUTES_TO", "TECHNIQUE_MODIFIES_TEXTURE"}:
                    for item in _json_object_items(semantic_relations.get(rel_type)):
                        source = str(item.get("source") or "").strip()
                        effect = str(item.get("effect") or "").strip()
                        if not source or not effect:
                            continue
                        relations.append(
                            {
                                "rel_type": rel_type,
                                "label": SEMANTIC_NODE_LABELS[rel_type],
                                "name": effect,
                                "source": source,
                                "causes": [source],
                            }
                        )
                    continue

                for target in _dedupe_strings(_json_value_items(semantic_relations.get(rel_type))):
                    relations.append(
                        {
                            "rel_type": rel_type,
                            "label": SEMANTIC_NODE_LABELS[rel_type],
                            "name": target,
                            "causes": [],
                        }
                    )

            if relations:
                rows.append(
                    {
                        "recipe_id": recipe_id,
                        "recipe_name": recipe_name,
                        "relations": relations,
                    }
                )
        return rows

    @staticmethod
    def _ensure_constraints(session) -> None:
        statements = [
            "CREATE CONSTRAINT flavor_name IF NOT EXISTS FOR (n:Flavor) REQUIRE n.name IS UNIQUE",
            "CREATE CONSTRAINT technique_name IF NOT EXISTS FOR (n:Technique) REQUIRE n.name IS UNIQUE",
            "CREATE CONSTRAINT diet_tag_name IF NOT EXISTS FOR (n:DietTag) REQUIRE n.name IS UNIQUE",
            "CREATE CONSTRAINT health_tag_name IF NOT EXISTS FOR (n:HealthTag) REQUIRE n.name IS UNIQUE",
            "CREATE CONSTRAINT cuisine_style_name IF NOT EXISTS FOR (n:CuisineStyle) REQUIRE n.name IS UNIQUE",
            "CREATE CONSTRAINT ingredient_category_name IF NOT EXISTS FOR (n:IngredientCategory) REQUIRE n.name IS UNIQUE",
            "CREATE CONSTRAINT time_profile_name IF NOT EXISTS FOR (n:TimeProfile) REQUIRE n.name IS UNIQUE",
            "CREATE CONSTRAINT difficulty_level_name IF NOT EXISTS FOR (n:DifficultyLevel) REQUIRE n.name IS UNIQUE",
            "CREATE CONSTRAINT semantic_effect_name IF NOT EXISTS FOR (n:SemanticEffect) REQUIRE n.name IS UNIQUE",
            "CREATE CONSTRAINT texture_effect_name IF NOT EXISTS FOR (n:TextureEffect) REQUIRE n.name IS UNIQUE",
        ]
        for statement in statements:
            session.run(statement)

    @staticmethod
    def _write_rows(tx, rows: List[Dict[str, Any]]) -> Dict[str, int]:
        counters = {"recipes": len(rows), "nodes": 0, "relationships": 0}
        counters["relationships"] += _write_simple_semantic_relations(tx, rows)
        counters["relationships"] += _write_contribution_relations(tx, rows)
        counters["relationships"] += _write_fine_grained_relations(tx, rows)
        counters["nodes"] = _count_semantic_schema_nodes(tx)
        return counters


_SIMPLE_RELATION_SPECS = (
    ("HAS_FLAVOR", "Flavor", "semantic:flavor:", "HAS_FLAVOR"),
    ("USES_TECHNIQUE", "Technique", "semantic:technique:", "USES_TECHNIQUE"),
    ("HAS_DIET_TAG", "DietTag", "semantic:diet:", "HAS_DIET_TAG"),
    ("HAS_HEALTH_TAG", "HealthTag", "semantic:health:", "HAS_HEALTH_TAG"),
    ("HAS_CUISINE_STYLE", "CuisineStyle", "semantic:cuisine:", "HAS_CUISINE_STYLE"),
    (
        "HAS_INGREDIENT_CATEGORY",
        "IngredientCategory",
        "semantic:ingredient-category:",
        "HAS_INGREDIENT_CATEGORY",
    ),
    ("HAS_TIME_PROFILE", "TimeProfile", "semantic:time-profile:", "HAS_TIME_PROFILE"),
    (
        "HAS_DIFFICULTY_LEVEL",
        "DifficultyLevel",
        "semantic:difficulty:",
        "HAS_DIFFICULTY_LEVEL",
    ),
)

_SIMPLE_RELATION_EXCLUDED_TYPES = frozenset(
    {"CONTRIBUTES_TO", "INGREDIENT_CONTRIBUTES_TO", "TECHNIQUE_MODIFIES_TEXTURE"}
)

_CONTRIBUTION_RELATION_QUERY = """
UNWIND $rows AS row
MATCH (recipe:Recipe {nodeId: row.recipe_id})
UNWIND row.relations AS rel
WITH recipe, rel
WHERE rel.rel_type = 'CONTRIBUTES_TO'
MERGE (target:SemanticEffect {name: rel.name})
ON CREATE SET target.nodeId = 'semantic:effect:' + rel.name
SET target.schemaVersion = $schema_version,
    target.createdFrom = 'semantic_schema'
MERGE (recipe)-[edge:CONTRIBUTES_TO]->(target)
SET edge.causes = rel.causes,
    edge.schemaVersion = $schema_version,
    edge.createdFrom = 'semantic_schema'
RETURN count(edge) AS relationships
"""

_FINE_GRAINED_RELATION_QUERY = """
UNWIND $rows AS row
MATCH (recipe:Recipe {nodeId: row.recipe_id})
UNWIND row.relations AS rel
WITH recipe, row, rel
WHERE rel.rel_type IN ['INGREDIENT_CONTRIBUTES_TO', 'TECHNIQUE_MODIFIES_TEXTURE']
CALL (recipe, row, rel) {
  WITH recipe, row, rel WHERE rel.rel_type = 'INGREDIENT_CONTRIBUTES_TO'
  OPTIONAL MATCH (existing:Ingredient)<-[:REQUIRES]-(recipe)
  WHERE existing.name = rel.source
  WITH recipe, row, rel, collect(existing)[0] AS matched_source
  CALL (matched_source, rel) {
    WITH matched_source, rel WHERE matched_source IS NULL
    MERGE (source:Ingredient {nodeId: 'semantic:ingredient:' + rel.source})
    ON CREATE SET source.name = rel.source
    SET source.schemaVersion = $schema_version,
        source.createdFrom = 'semantic_schema'
    RETURN source
    UNION ALL
    WITH matched_source, rel WHERE matched_source IS NOT NULL
    RETURN matched_source AS source
  }
  WITH recipe, row, rel, source
  MERGE (effect:SemanticEffect {name: rel.name})
  ON CREATE SET effect.nodeId = 'semantic:effect:' + rel.name
  SET effect.schemaVersion = $schema_version,
      effect.createdFrom = 'semantic_schema'
  MERGE (recipe)-[context:USES_SEMANTIC_SOURCE]->(source)
  SET context.schemaVersion = $schema_version,
      context.createdFrom = 'semantic_schema'
  MERGE (source)-[edge:INGREDIENT_CONTRIBUTES_TO]->(effect)
  SET edge.causes = rel.causes,
      edge.recipeId = row.recipe_id,
      edge.recipeName = row.recipe_name,
      edge.schemaVersion = $schema_version,
      edge.createdFrom = 'semantic_schema'
  RETURN count(edge) + count(context) AS relationships
  UNION ALL
  WITH recipe, row, rel
  WITH recipe, row, rel WHERE rel.rel_type = 'TECHNIQUE_MODIFIES_TEXTURE'
  MERGE (source:Technique {name: rel.source})
  ON CREATE SET source.nodeId = 'semantic:technique:' + rel.source
  SET source.schemaVersion = $schema_version,
      source.createdFrom = 'semantic_schema'
  MERGE (effect:TextureEffect {name: rel.name})
  ON CREATE SET effect.nodeId = 'semantic:texture:' + rel.name
  SET effect.schemaVersion = $schema_version,
      effect.createdFrom = 'semantic_schema'
  MERGE (recipe)-[context:USES_TECHNIQUE]->(source)
  SET context.schemaVersion = $schema_version,
      context.createdFrom = 'semantic_schema'
  MERGE (source)-[edge:TECHNIQUE_MODIFIES_TEXTURE]->(effect)
  SET edge.causes = rel.causes,
      edge.recipeId = row.recipe_id,
      edge.recipeName = row.recipe_name,
      edge.schemaVersion = $schema_version,
      edge.createdFrom = 'semantic_schema'
  RETURN count(edge) + count(context) AS relationships
}
RETURN sum(relationships) AS relationships
"""

_SEMANTIC_NODE_COUNT_QUERY = """
MATCH (n)
WHERE n.createdFrom = 'semantic_schema' AND n.schemaVersion = $schema_version
RETURN count(n) AS nodes
"""


def _simple_relation_rows(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [
        {
            "recipe_id": row["recipe_id"],
            "name": relation["name"],
            "rel_type": relation["rel_type"],
        }
        for row in rows
        for relation in row.get("relations", [])
        if relation.get("rel_type") not in _SIMPLE_RELATION_EXCLUDED_TYPES
    ]


def _write_simple_semantic_relations(tx, rows: List[Dict[str, Any]]) -> int:
    relationships = 0
    flat_rows = _simple_relation_rows(rows)
    for rel_type, label, node_prefix, edge_type in _SIMPLE_RELATION_SPECS:
        rel_rows = [row for row in flat_rows if row["rel_type"] == rel_type]
        if not rel_rows:
            continue
        query = f"""
        UNWIND $rows AS row
        MATCH (recipe:Recipe {{nodeId: row.recipe_id}})
        MERGE (target:{label} {{name: row.name}})
        ON CREATE SET target.nodeId = $node_prefix + row.name
        SET target.schemaVersion = $schema_version,
            target.createdFrom = 'semantic_schema'
        MERGE (recipe)-[edge:{edge_type}]->(target)
        SET edge.schemaVersion = $schema_version,
            edge.createdFrom = 'semantic_schema'
        RETURN count(edge) AS relationships
        """
        result = tx.run(
            query,
            rows=rel_rows,
            node_prefix=node_prefix,
            schema_version=SEMANTIC_SCHEMA_VERSION,
        ).single()
        relationships += _count_result_value(result, "relationships")
    return relationships


def _write_contribution_relations(tx, rows: List[Dict[str, Any]]) -> int:
    result = tx.run(
        _CONTRIBUTION_RELATION_QUERY,
        rows=rows,
        schema_version=SEMANTIC_SCHEMA_VERSION,
    ).single()
    return _count_result_value(result, "relationships")


def _write_fine_grained_relations(tx, rows: List[Dict[str, Any]]) -> int:
    result = tx.run(
        _FINE_GRAINED_RELATION_QUERY,
        rows=rows,
        schema_version=SEMANTIC_SCHEMA_VERSION,
    ).single()
    return _count_result_value(result, "relationships")


def _count_semantic_schema_nodes(tx) -> int:
    result = tx.run(_SEMANTIC_NODE_COUNT_QUERY, schema_version=SEMANTIC_SCHEMA_VERSION).single()
    return _count_result_value(result, "nodes")


def _count_result_value(result: object, key: str) -> int:
    if not isinstance(result, Mapping):
        return 0
    return coerce_int(result.get(key))
