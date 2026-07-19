"""Recipe domain pack retained as an explicit optional domain."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ...kernel.documents import TextDocument
from ..contracts import (
    CitationProjection,
    DomainDocumentMapper,
    DomainExtraction,
    DomainOntology,
    DomainPack,
    ExtractedEntity,
    GraphNodeType,
    GraphRelationType,
)
from .semantic_schema import infer_recipe_semantics


class RecipeDocumentMapper(DomainDocumentMapper):
    """Map materialized recipes without leaking recipe fields into core DTOs."""

    def map_document(self, payload: Mapping[str, Any]) -> TextDocument:
        entity_id = str(
            payload.get("entity_id") or payload.get("recipe_id") or payload.get("id") or ""
        )
        entity_name = str(
            payload.get("entity_name") or payload.get("recipe_name") or payload.get("name") or ""
        )
        content = str(payload.get("content") or payload.get("description") or "")
        ingredients = [str(item) for item in payload.get("ingredients") or []]
        steps = [str(item) for item in payload.get("steps") or []]
        properties = dict(payload.get("properties") or {})
        semantics = infer_recipe_semantics(properties, ingredients, steps, content)
        return TextDocument(
            content=content,
            metadata={
                "domain": "recipe",
                "entity_id": entity_id,
                "entity_name": entity_name,
                "entity_type": "Recipe",
                "node_id": entity_id,
                "node_type": "Recipe",
                "doc_type": "recipe",
                **semantics,
            },
        )

    def extract(self, payload: Mapping[str, Any]) -> DomainExtraction:
        entity_id = str(
            payload.get("entity_id") or payload.get("recipe_id") or payload.get("id") or ""
        )
        entity_name = str(
            payload.get("entity_name") or payload.get("recipe_name") or payload.get("name") or ""
        )
        if not entity_id and not entity_name:
            return DomainExtraction()
        return DomainExtraction(
            entities=(
                ExtractedEntity(
                    entity_id=entity_id or entity_name,
                    entity_name=entity_name or entity_id,
                    entity_type="Recipe",
                ),
            )
        )


RECIPE_ONTOLOGY = DomainOntology(
    primary_labels=("Recipe",),
    node_types=(
        GraphNodeType("Recipe", ("nodeId", "id"), ("name",)),
        GraphNodeType("Ingredient", ("nodeId", "id"), ("name",)),
        GraphNodeType("CookingStep", ("nodeId", "id"), ("name", "description")),
        GraphNodeType("Category", ("nodeId", "id"), ("name",)),
    ),
    relation_types=(
        GraphRelationType("REQUIRES", ("Recipe",), ("Ingredient",)),
        GraphRelationType("CONTAINS_STEP", ("Recipe",), ("CookingStep",)),
        GraphRelationType("BELONGS_TO_CATEGORY", ("Recipe",), ("Category",)),
        GraphRelationType("HAS_FLAVOR", ("Recipe",), ("Recipe",)),
        GraphRelationType("USES_TECHNIQUE", ("Recipe",), ("CookingStep",)),
        GraphRelationType("CONTRIBUTES_TO", ("Ingredient", "CookingStep"), ("Recipe",)),
    ),
)

RECIPE_DOMAIN_PACK = DomainPack(
    name="recipe",
    version="recipe-domain-v1",
    ontology=RECIPE_ONTOLOGY,
    document_mapper=RecipeDocumentMapper(),
    query_policy_bundle="c9-default-v1",
    vector_collection_name="cooking_knowledge",
    citation_projection=CitationProjection(
        citation_label="菜谱证据",
        public_attribute_keys=("category", "cuisine_type", "difficulty", "prep_time", "cook_time"),
    ),
    evaluation_resource="evaluation.json",
)
DOMAIN_PACK = RECIPE_DOMAIN_PACK

__all__ = [
    "DOMAIN_PACK",
    "RECIPE_DOMAIN_PACK",
    "RECIPE_ONTOLOGY",
    "RecipeDocumentMapper",
    "infer_recipe_semantics",
]
