"""Canonical semantic schema identifiers shared across subsystems."""

SEMANTIC_SCHEMA_VERSION = "semantic-schema-v5"

SEMANTIC_RELATION_TYPES = [
    "HAS_FLAVOR",
    "USES_TECHNIQUE",
    "HAS_DIET_TAG",
    "HAS_HEALTH_TAG",
    "HAS_CUISINE_STYLE",
    "HAS_INGREDIENT_CATEGORY",
    "HAS_TIME_PROFILE",
    "HAS_DIFFICULTY_LEVEL",
    "CONTRIBUTES_TO",
    "INGREDIENT_CONTRIBUTES_TO",
    "TECHNIQUE_MODIFIES_TEXTURE",
]

SEMANTIC_NODE_LABELS = {
    "HAS_FLAVOR": "Flavor",
    "USES_TECHNIQUE": "Technique",
    "HAS_DIET_TAG": "DietTag",
    "HAS_HEALTH_TAG": "HealthTag",
    "HAS_CUISINE_STYLE": "CuisineStyle",
    "HAS_INGREDIENT_CATEGORY": "IngredientCategory",
    "HAS_TIME_PROFILE": "TimeProfile",
    "HAS_DIFFICULTY_LEVEL": "DifficultyLevel",
    "CONTRIBUTES_TO": "SemanticEffect",
    "INGREDIENT_CONTRIBUTES_TO": "SemanticEffect",
    "TECHNIQUE_MODIFIES_TEXTURE": "TextureEffect",
}

SEMANTIC_NODE_LABELS_SET = set(SEMANTIC_NODE_LABELS.values())

__all__ = [
    "SEMANTIC_NODE_LABELS",
    "SEMANTIC_NODE_LABELS_SET",
    "SEMANTIC_RELATION_TYPES",
    "SEMANTIC_SCHEMA_VERSION",
]
