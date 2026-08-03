"""Recipe domain pack retained as an explicit optional domain."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ...kernel.documents import TextDocument
from ...kernel.json_types import as_string_list
from ..contracts import (
    CitationProjection,
    DomainBuildDataView,
    DomainConstraintField,
    DomainDocumentMapper,
    DomainExtraction,
    DomainOntology,
    DomainPack,
    DomainQueryConstraintSchema,
    DomainReasoningVocabulary,
    ExtractedEntity,
    GraphNodeType,
    GraphRelationType,
)
from .build.document_builder import RecipeDocumentBuilder
from .build.loader import Neo4jGraphDataLoader
from .constraint_matcher import RecipeConstraintMatcher
from .semantic_graph_writer import SemanticGraphSchemaWriter
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
        matched_terms = as_string_list(payload.get("matched_terms"))
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
                "matched_terms": matched_terms,
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
    query_constraints=DomainQueryConstraintSchema(
        fields=(
            DomainConstraintField("ingredients"),
            DomainConstraintField("excluded_ingredients"),
            DomainConstraintField("cuisine_terms", "cuisine_style_terms"),
            DomainConstraintField("excluded_cuisine_terms"),
            DomainConstraintField("category_terms", "ingredient_category_terms"),
            DomainConstraintField("health_terms", "health_terms"),
            DomainConstraintField("preference_terms", "difficulty_terms"),
            DomainConstraintField("max_prep_minutes"),
            DomainConstraintField("max_cook_minutes"),
        ),
        excluded_term_fields=("excluded_ingredients",),
        maximum_duration_field="max_total_minutes",
    ),
    reasoning_vocabulary=DomainReasoningVocabulary(
        subject_fallback="the target recipes",
        comparison_labels=("Recipe",),
        compositional_labels=(("Technique", "techniques"), ("Flavor", "flavor nodes")),
        semantic_effect_label="semantic effect nodes",
        semantic_node_labels=(
            "Flavor",
            "Technique",
            "DietTag",
            "HealthTag",
            "CuisineStyle",
            "IngredientCategory",
            "TimeProfile",
            "DifficultyLevel",
            "SemanticEffect",
        ),
        constraint_labels=(
            ("TimeProfile", "time profiles"),
            ("DifficultyLevel", "difficulty levels"),
        ),
    ),
    build_data_view=DomainBuildDataView(
        primary_group="recipes",
        related_groups=("ingredients", "cooking_steps"),
        count_metrics=(
            ("recipes", "total_recipes"),
            ("ingredients", "total_ingredients"),
            ("cooking_steps", "total_cooking_steps"),
        ),
        distribution_metrics=(
            ("category", "categories"),
            ("cuisine_type", "cuisines"),
            ("difficulty", "difficulties"),
        ),
    ),
    build_adapter="recipe",
    build_loader_factory=Neo4jGraphDataLoader,
    build_document_builder_factory=RecipeDocumentBuilder,
    graph_import_resource="neo4j_import.cypher",
    graph_import_replacements=(
        ("file:///nodes.csv", "file:///cypher/nodes.csv"),
        ("file:///relationships.csv", "file:///cypher/relationships.csv"),
    ),
    semantic_graph_writer_factory=SemanticGraphSchemaWriter,
    semantic_schema_enabled=True,
    semantic_schema_count_field="recipes",
    constraint_matcher_type=RecipeConstraintMatcher,
    allow_domainless_graph_records=True,
)
DOMAIN_PACK = RECIPE_DOMAIN_PACK

__all__ = [
    "DOMAIN_PACK",
    "RECIPE_DOMAIN_PACK",
    "RECIPE_ONTOLOGY",
    "RecipeDocumentMapper",
    "Neo4jGraphDataLoader",
    "RecipeDocumentBuilder",
    "SemanticGraphSchemaWriter",
    "infer_recipe_semantics",
]
