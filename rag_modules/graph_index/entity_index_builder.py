"""Entity KV materialization for graph index retrieval."""

from __future__ import annotations

import logging
from typing import Any, Dict, List

from ..query_understanding.registry import dedupe_preserve_order
from .models import EntityKeyValue
from .store import GraphIndexStore

logger = logging.getLogger(__name__)


def _domain_property_values(props: Dict[str, Any]) -> List[str]:
    values: List[str] = []
    for value in props.values():
        if isinstance(value, (str, int, float, bool)) and str(value).strip():
            values.append(str(value))
        elif isinstance(value, (list, tuple, set)):
            values.extend(str(item) for item in value if str(item).strip())
    return dedupe_preserve_order(values)


def _add_domain_entity(entity: Any, store: GraphIndexStore) -> None:
    entity_id = str(entity.node_id)
    entity_name = str(entity.name or entity_id)
    labels = [str(label) for label in (getattr(entity, "labels", None) or []) if label]
    props = getattr(entity, "properties", {}) or {}
    domain_name = str(props.get("domain") or "").strip()
    entity_type = labels[0] if labels else str(props.get("entity_type") or "Entity")
    property_values = _domain_property_values(props)
    content_parts = [f"entity_name: {entity_name}", f"entity_type: {entity_type}"]
    for key, value in props.items():
        if value not in (None, "", [], {}):
            content_parts.append(f"{key}: {value}")
    store.add_entity(
        entity_id,
        EntityKeyValue(
            entity_name=entity_name,
            index_keys=dedupe_preserve_order([entity_name, entity_id, *property_values]),
            value_content="\n".join(content_parts),
            entity_type=entity_type,
            metadata={
                "node_id": entity_id,
                "labels": labels,
                "domain": domain_name,
                "properties": props,
            },
        ),
        extra_keys=[entity_name],
    )


def _recipe_content_parts(entity_name: str, props: Dict[str, Any]) -> List[str]:
    parts = [f"菜品名称: {entity_name}"]
    scalar_fields = (
        ("description", "描述"),
        ("category", "分类"),
        ("cuisineType", "菜系"),
        ("difficulty", "难度"),
        ("cookingTime", "烹饪时间"),
    )
    tag_fields = (
        ("health_tags", "健康标签"),
        ("cuisine_style_tags", "菜系风格标签"),
        ("ingredient_category_tags", "食材类别标签"),
        ("time_profile_tags", "时间轮廓标签"),
        ("difficulty_level_tags", "难度标签"),
    )
    for field, label in scalar_fields:
        if props.get(field):
            parts.append(f"{label}: {props[field]}")
    for field, label in tag_fields:
        if props.get(field):
            parts.append(f"{label}: {', '.join(props.get(field) or [])}")
    return parts


def _recipe_index_keys(entity_name: str, props: Dict[str, Any]) -> List[str]:
    return dedupe_preserve_order(
        [
            entity_name,
            props.get("category"),
            props.get("cuisineType"),
            *list(props.get("flavor_tags", []) or []),
            *list(props.get("technique_tags", []) or []),
            *list(props.get("diet_tags", []) or []),
            *list(props.get("health_tags", []) or []),
            *list(props.get("cuisine_style_tags", []) or []),
            *list(props.get("ingredient_category_tags", []) or []),
            *list(props.get("time_profile_tags", []) or []),
            *list(props.get("difficulty_level_tags", []) or []),
        ]
    )


def _add_recipe_entity(recipe: Any, store: GraphIndexStore) -> None:
    entity_id = str(recipe.node_id)
    entity_name = recipe.name or f"菜谱_{entity_id}"
    props = getattr(recipe, "properties", {}) or {}
    store.add_entity(
        entity_id,
        EntityKeyValue(
            entity_name=entity_name,
            index_keys=_recipe_index_keys(entity_name, props),
            value_content="\n".join(_recipe_content_parts(entity_name, props)),
            entity_type="Recipe",
            metadata={"node_id": entity_id, "domain": "recipe", "properties": props},
        ),
        extra_keys=[entity_name],
    )


def _add_ingredient_entity(ingredient: Any, store: GraphIndexStore) -> None:
    entity_id = str(ingredient.node_id)
    entity_name = ingredient.name or f"食材_{entity_id}"
    props = getattr(ingredient, "properties", {}) or {}
    content_parts = [f"食材名称: {entity_name}"]
    for field, label in (
        ("category", "类别"),
        ("nutrition", "营养信息"),
        ("storage", "储存方式"),
    ):
        if props.get(field):
            content_parts.append(f"{label}: {props[field]}")
    store.add_entity(
        entity_id,
        EntityKeyValue(
            entity_name=entity_name,
            index_keys=dedupe_preserve_order(
                [entity_name, props.get("category"), props.get("nutrition"), props.get("storage")]
            ),
            value_content="\n".join(content_parts),
            entity_type="Ingredient",
            metadata={"node_id": entity_id, "domain": "recipe", "properties": props},
        ),
        extra_keys=[entity_name],
    )


def _add_cooking_step_entity(step: Any, store: GraphIndexStore) -> None:
    entity_id = str(step.node_id)
    entity_name = f"步骤_{entity_id}"
    props = getattr(step, "properties", {}) or {}
    content_parts = [f"烹饪步骤: {entity_name}"]
    for field, label in (
        ("description", "步骤描述"),
        ("order", "步骤顺序"),
        ("technique", "技巧"),
        ("time", "时间"),
    ):
        if props.get(field):
            content_parts.append(f"{label}: {props[field]}")
    store.add_entity(
        entity_id,
        EntityKeyValue(
            entity_name=entity_name,
            index_keys=dedupe_preserve_order(
                [entity_name, props.get("technique"), props.get("time")]
            ),
            value_content="\n".join(content_parts),
            entity_type="CookingStep",
            metadata={"node_id": entity_id, "domain": "recipe", "properties": props},
        ),
        extra_keys=[entity_name],
    )


class EntityIndexBuilder:
    """Build entity key-value payloads from graph nodes."""

    def build(
        self,
        *,
        recipes: List[Any],
        ingredients: List[Any],
        cooking_steps: List[Any],
        store: GraphIndexStore,
    ) -> Dict[str, EntityKeyValue]:
        logger.info("开始构建实体键值索引...")
        for recipe in recipes:
            _add_recipe_entity(recipe, store)
        for ingredient in ingredients:
            _add_ingredient_entity(ingredient, store)
        for step in cooking_steps:
            _add_cooking_step_entity(step, store)
        logger.info("实体键值索引构建完成，共 %s 个实体", len(store.entity_kv_store))
        return store.entity_kv_store

    def build_domain_entities(
        self,
        *,
        entities: List[Any],
        store: GraphIndexStore,
    ) -> Dict[str, EntityKeyValue]:
        """Build a graph index without assuming recipe/ingredient/step node families."""

        logger.info("Building domain entity key-value index...")
        for entity in entities:
            _add_domain_entity(entity, store)
        logger.info("Domain entity index built with %s entities.", len(store.entity_kv_store))
        return store.entity_kv_store
