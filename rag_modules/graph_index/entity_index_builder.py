"""Entity KV materialization for graph index retrieval."""

from __future__ import annotations

import logging
from typing import Any, Dict, List

from ..query_understanding import dedupe_preserve_order
from .models import EntityKeyValue
from .store import GraphIndexStore

logger = logging.getLogger(__name__)


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
            entity_id = str(recipe.node_id)
            entity_name = recipe.name or f"菜谱_{entity_id}"
            props = getattr(recipe, "properties", {}) or {}
            content_parts = [f"菜品名称: {entity_name}"]
            if props.get("description"):
                content_parts.append(f"描述: {props['description']}")
            if props.get("category"):
                content_parts.append(f"分类: {props['category']}")
            if props.get("cuisineType"):
                content_parts.append(f"菜系: {props['cuisineType']}")
            if props.get("difficulty"):
                content_parts.append(f"难度: {props['difficulty']}")
            if props.get("cookingTime"):
                content_parts.append(f"烹饪时间: {props['cookingTime']}")
            if props.get("health_tags"):
                content_parts.append(f"健康标签: {', '.join(props.get('health_tags') or [])}")
            if props.get("cuisine_style_tags"):
                content_parts.append(f"菜系风格标签: {', '.join(props.get('cuisine_style_tags') or [])}")
            if props.get("ingredient_category_tags"):
                content_parts.append(
                    f"食材类别标签: {', '.join(props.get('ingredient_category_tags') or [])}"
                )
            if props.get("time_profile_tags"):
                content_parts.append(f"时间轮廓标签: {', '.join(props.get('time_profile_tags') or [])}")
            if props.get("difficulty_level_tags"):
                content_parts.append(f"难度标签: {', '.join(props.get('difficulty_level_tags') or [])}")

            entity_kv = EntityKeyValue(
                entity_name=entity_name,
                index_keys=dedupe_preserve_order(
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
                ),
                value_content="\n".join(content_parts),
                entity_type="Recipe",
                metadata={
                    "node_id": entity_id,
                    "properties": props,
                },
            )
            store.add_entity(entity_id, entity_kv, extra_keys=[entity_name])

        for ingredient in ingredients:
            entity_id = str(ingredient.node_id)
            entity_name = ingredient.name or f"食材_{entity_id}"
            props = getattr(ingredient, "properties", {}) or {}
            content_parts = [f"食材名称: {entity_name}"]
            if props.get("category"):
                content_parts.append(f"类别: {props['category']}")
            if props.get("nutrition"):
                content_parts.append(f"营养信息: {props['nutrition']}")
            if props.get("storage"):
                content_parts.append(f"储存方式: {props['storage']}")

            entity_kv = EntityKeyValue(
                entity_name=entity_name,
                index_keys=dedupe_preserve_order(
                    [
                        entity_name,
                        props.get("category"),
                        props.get("nutrition"),
                        props.get("storage"),
                    ]
                ),
                value_content="\n".join(content_parts),
                entity_type="Ingredient",
                metadata={
                    "node_id": entity_id,
                    "properties": props,
                },
            )
            store.add_entity(entity_id, entity_kv, extra_keys=[entity_name])

        for step in cooking_steps:
            entity_id = str(step.node_id)
            entity_name = f"步骤_{entity_id}"
            props = getattr(step, "properties", {}) or {}
            content_parts = [f"烹饪步骤: {entity_name}"]
            if props.get("description"):
                content_parts.append(f"步骤描述: {props['description']}")
            if props.get("order"):
                content_parts.append(f"步骤顺序: {props['order']}")
            if props.get("technique"):
                content_parts.append(f"技巧: {props['technique']}")
            if props.get("time"):
                content_parts.append(f"时间: {props['time']}")

            entity_kv = EntityKeyValue(
                entity_name=entity_name,
                index_keys=dedupe_preserve_order(
                    [
                        entity_name,
                        props.get("technique"),
                        props.get("time"),
                    ]
                ),
                value_content="\n".join(content_parts),
                entity_type="CookingStep",
                metadata={
                    "node_id": entity_id,
                    "properties": props,
                },
            )
            store.add_entity(entity_id, entity_kv, extra_keys=[entity_name])

        logger.info("实体键值索引构建完成，共 %s 个实体", len(store.entity_kv_store))
        return store.entity_kv_store
