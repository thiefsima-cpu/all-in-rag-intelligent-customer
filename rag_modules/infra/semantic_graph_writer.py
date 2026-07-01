"""
Persist derived semantic recipe schema into Neo4j.

The document builder infers lightweight semantic tags from recipe text. This
module turns those tags into idempotent graph nodes/edges so GraphRAG traversal
can use them directly instead of relying only on virtual in-memory relations.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Iterable, List

from ..domain.shared.semantic_schema import (
    SEMANTIC_NODE_LABELS,
    SEMANTIC_RELATION_TYPES,
    SEMANTIC_SCHEMA_VERSION,
)
from ..text_document import TextDocument
from .neo4j import Neo4jConnectionManager, create_neo4j_driver

logger = logging.getLogger(__name__)


def _dedupe_strings(values: Iterable[Any]) -> List[str]:
    seen = set()
    out = []
    for value in values or []:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        out.append(text)
    return out


class SemanticGraphSchemaWriter:
    """Write semantic schema nodes and relationships to Neo4j."""

    def __init__(self, config, neo4j_manager: Neo4jConnectionManager | None = None):
        self.config = config
        self.storage = config.storage
        self.graph = config.graph
        self.neo4j_manager = neo4j_manager
        self.driver: Any | None = None
        self._owns_driver = False

    def __enter__(self) -> "SemanticGraphSchemaWriter":
        if self.neo4j_manager is not None:
            self.driver = self.neo4j_manager.driver
        else:
            self.driver = create_neo4j_driver(
                self.storage.neo4j_uri,
                self.storage.neo4j_user,
                self.storage.neo4j_password,
            )
            self._owns_driver = True
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def close(self) -> None:
        if self._owns_driver and self.driver:
            self.driver.close()
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
                self.driver = self.neo4j_manager.driver
            else:
                self.driver = create_neo4j_driver(
                    self.storage.neo4j_uri,
                    self.storage.neo4j_user,
                    self.storage.neo4j_password,
                )
                self._owns_driver = True
                opened_here = True

        rows = self._build_rows(documents)
        if not rows:
            if opened_here:
                self.close()
            return {"recipes": 0, "nodes": 0, "relationships": 0}

        driver = self.driver
        if driver is None:
            raise RuntimeError("Neo4j driver is not initialized.")

        try:
            with driver.session(database=self.storage.neo4j_database) as session:
                self._ensure_constraints(session)
                result = session.execute_write(self._write_rows, rows)
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

            semantic_relations = metadata.get("semantic_relations") or {}
            relations = []
            for rel_type in SEMANTIC_RELATION_TYPES:
                if rel_type == "CONTRIBUTES_TO":
                    for item in semantic_relations.get(rel_type, []) or []:
                        effect = str((item or {}).get("effect") or "").strip()
                        if not effect:
                            continue
                        relations.append(
                            {
                                "rel_type": rel_type,
                                "label": SEMANTIC_NODE_LABELS[rel_type],
                                "name": effect,
                                "causes": _dedupe_strings((item or {}).get("causes") or []),
                            }
                        )
                    continue
                if rel_type in {"INGREDIENT_CONTRIBUTES_TO", "TECHNIQUE_MODIFIES_TEXTURE"}:
                    for item in semantic_relations.get(rel_type, []) or []:
                        source = str((item or {}).get("source") or "").strip()
                        effect = str((item or {}).get("effect") or "").strip()
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

                for target in _dedupe_strings(semantic_relations.get(rel_type) or []):
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
        flat_rows = [
            {
                "recipe_id": row["recipe_id"],
                "name": relation["name"],
                "rel_type": relation["rel_type"],
            }
            for row in rows
            for relation in row.get("relations", [])
            if relation.get("rel_type")
            not in {"CONTRIBUTES_TO", "INGREDIENT_CONTRIBUTES_TO", "TECHNIQUE_MODIFIES_TEXTURE"}
        ]

        simple_specs = [
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
        ]
        for rel_type, label, node_prefix, edge_type in simple_specs:
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
            counters["relationships"] += int((result or {}).get("relationships") or 0)

        contribution_query = """
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
        contribution_result = tx.run(
            contribution_query,
            rows=rows,
            schema_version=SEMANTIC_SCHEMA_VERSION,
        ).single()
        counters["relationships"] += int((contribution_result or {}).get("relationships") or 0)

        fine_grained_query = """
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
        fine_grained_result = tx.run(
            fine_grained_query,
            rows=rows,
            schema_version=SEMANTIC_SCHEMA_VERSION,
        ).single()
        counters["relationships"] += int((fine_grained_result or {}).get("relationships") or 0)

        node_count_query = """
        MATCH (n)
        WHERE n.createdFrom = 'semantic_schema' AND n.schemaVersion = $schema_version
        RETURN count(n) AS nodes
        """
        node_count = tx.run(node_count_query, schema_version=SEMANTIC_SCHEMA_VERSION).single()
        counters["nodes"] = int((node_count or {}).get("nodes") or 0)
        return counters
