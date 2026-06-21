"""Recipe-document materialization over loaded graph data."""

from __future__ import annotations

import logging
from collections import defaultdict
from typing import Any, Dict, Iterable, List

from neo4j import Driver

from ...semantic_schema import infer_recipe_semantics
from ...text_document import TextDocument
from .models import GraphNode

logger = logging.getLogger(__name__)

UNKNOWN_VALUE = "未知"

RECIPE_INGREDIENTS_QUERY = """
MATCH (r:Recipe)-[req:REQUIRES]->(i:Ingredient)
WHERE r.nodeId IN $recipe_ids
RETURN r.nodeId AS recipe_id,
       i.name AS name,
       i.category AS category,
       req.amount AS amount,
       req.unit AS unit,
       i.description AS description
ORDER BY r.nodeId, i.name
"""

RECIPE_STEPS_QUERY = """
MATCH (r:Recipe)-[c:CONTAINS_STEP]->(s:CookingStep)
WHERE r.nodeId IN $recipe_ids
RETURN r.nodeId AS recipe_id,
       s.name AS name,
       s.description AS description,
       s.stepNumber AS stepNumber,
       s.methods AS methods,
       s.tools AS tools,
       s.timeEstimate AS timeEstimate,
       c.stepOrder AS stepOrder
ORDER BY r.nodeId, COALESCE(c.stepOrder, s.stepNumber, 999)
"""


class RecipeDocumentBuilder:
    """Build retrieval-ready recipe documents and semantic metadata."""

    def build(
        self,
        *,
        driver: Driver,
        database: str,
        recipes: Iterable[GraphNode],
    ) -> List[TextDocument]:
        recipe_list = [recipe for recipe in recipes]
        if not recipe_list:
            return []

        recipe_ids = [recipe.node_id for recipe in recipe_list]
        recipe_map = {recipe.node_id: recipe for recipe in recipe_list}
        ingredients_by_recipe = self._load_ingredients_by_recipe(
            driver=driver,
            database=database,
            recipe_ids=recipe_ids,
        )
        steps_by_recipe = self._load_steps_by_recipe(
            driver=driver,
            database=database,
            recipe_ids=recipe_ids,
        )

        documents: List[TextDocument] = []
        for recipe_id in recipe_ids:
            recipe = recipe_map[recipe_id]
            try:
                documents.append(
                    self.build_document(
                        recipe=recipe,
                        raw_ingredients=ingredients_by_recipe.get(recipe_id, []),
                        raw_steps=steps_by_recipe.get(recipe_id, []),
                    )
                )
            except Exception as exc:
                logger.warning(
                    "Failed to build recipe document %s (ID: %s): %s",
                    recipe.name,
                    recipe_id,
                    exc,
                )
        return documents

    def _load_ingredients_by_recipe(
        self,
        *,
        driver: Driver,
        database: str,
        recipe_ids: List[str],
    ) -> Dict[str, List[Dict[str, Any]]]:
        ingredients_by_recipe: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        with driver.session(database=database) as session:
            for record in session.run(RECIPE_INGREDIENTS_QUERY, {"recipe_ids": recipe_ids}):
                ingredients_by_recipe[str(record["recipe_id"])].append(dict(record))
        return dict(ingredients_by_recipe)

    def _load_steps_by_recipe(
        self,
        *,
        driver: Driver,
        database: str,
        recipe_ids: List[str],
    ) -> Dict[str, List[Dict[str, Any]]]:
        steps_by_recipe: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        with driver.session(database=database) as session:
            for record in session.run(RECIPE_STEPS_QUERY, {"recipe_ids": recipe_ids}):
                steps_by_recipe[str(record["recipe_id"])].append(dict(record))
        return dict(steps_by_recipe)

    def build_document(
        self,
        *,
        recipe: GraphNode,
        raw_ingredients: List[Dict[str, Any]],
        raw_steps: List[Dict[str, Any]],
    ) -> TextDocument:
        recipe_name = recipe.name
        recipe_properties = dict(recipe.properties or {})
        ingredients_info = [self._format_ingredient_line(item) for item in raw_ingredients]
        steps_info = [self._format_step_text(item) for item in raw_steps]

        full_content = self._compose_recipe_content(
            recipe_name=recipe_name,
            recipe_properties=recipe_properties,
            ingredients_info=ingredients_info,
            steps_info=steps_info,
        )
        semantics = infer_recipe_semantics(
            recipe_properties=recipe_properties,
            ingredients=ingredients_info,
            steps=steps_info,
            full_content=full_content,
        )
        recipe_properties.update(semantics)
        full_content = self._append_semantic_section(
            full_content=full_content,
            semantics=semantics,
        )

        return TextDocument(
            content=full_content,
            metadata={
                "node_id": recipe.node_id,
                "recipe_name": recipe_name,
                "node_type": "Recipe",
                "category": recipe_properties.get("category", UNKNOWN_VALUE),
                "cuisine_type": recipe_properties.get("cuisineType", UNKNOWN_VALUE),
                "difficulty": recipe_properties.get("difficulty", 0),
                "prep_time": recipe_properties.get("prepTime", ""),
                "cook_time": recipe_properties.get("cookTime", ""),
                "servings": recipe_properties.get("servings", ""),
                "ingredients_count": len(ingredients_info),
                "steps_count": len(steps_info),
                "flavor_tags": semantics["flavor_tags"],
                "technique_tags": semantics["technique_tags"],
                "diet_tags": semantics["diet_tags"],
                "health_tags": semantics["health_tags"],
                "cuisine_style_tags": semantics["cuisine_style_tags"],
                "ingredient_category_tags": semantics["ingredient_category_tags"],
                "time_profile_tags": semantics["time_profile_tags"],
                "difficulty_level_tags": semantics["difficulty_level_tags"],
                "semantic_relations": semantics["semantic_relations"],
                "doc_type": "recipe",
                "content_length": len(full_content),
            },
        )

    @staticmethod
    def _format_ingredient_line(ingredient: Dict[str, Any]) -> str:
        text = str(ingredient.get("name") or "")
        category = ingredient.get("category")
        if category:
            text += f" [{category}]"
        amount = ingredient.get("amount")
        unit = ingredient.get("unit")
        if amount or unit:
            text += f" ({amount or ''}{unit or ''})"
        if ingredient.get("description"):
            text += f" - {ingredient['description']}"
        return text.strip()

    @staticmethod
    def _format_step_text(step: Dict[str, Any]) -> str:
        parts = [f"步骤: {step.get('name') or ''}"]
        if step.get("description"):
            parts.append(f"描述: {step['description']}")
        if step.get("methods"):
            parts.append(f"方法: {step['methods']}")
        if step.get("tools"):
            parts.append(f"工具: {step['tools']}")
        if step.get("timeEstimate"):
            parts.append(f"时间: {step['timeEstimate']}")
        return "\n".join(parts)

    def _compose_recipe_content(
        self,
        *,
        recipe_name: str,
        recipe_properties: Dict[str, Any],
        ingredients_info: List[str],
        steps_info: List[str],
    ) -> str:
        content_parts = [f"# {recipe_name}"]
        if recipe_properties.get("description"):
            content_parts.append(f"\n## 菜品描述\n{recipe_properties['description']}")
        if recipe_properties.get("cuisineType"):
            content_parts.append(f"\n菜系: {recipe_properties['cuisineType']}")
        if recipe_properties.get("difficulty") not in (None, ""):
            content_parts.append(f"难度: {recipe_properties['difficulty']}")
        if recipe_properties.get("prepTime") or recipe_properties.get("cookTime"):
            time_info = []
            if recipe_properties.get("prepTime"):
                time_info.append(f"准备时间: {recipe_properties['prepTime']}")
            if recipe_properties.get("cookTime"):
                time_info.append(f"烹饪时间: {recipe_properties['cookTime']}")
            content_parts.append(f"\n时间信息: {', '.join(time_info)}")
        if recipe_properties.get("servings"):
            content_parts.append(f"份量: {recipe_properties['servings']}")
        if ingredients_info:
            content_parts.append("\n## 所需食材")
            for index, ingredient in enumerate(ingredients_info, start=1):
                content_parts.append(f"{index}. {ingredient}")
        if steps_info:
            content_parts.append("\n## 制作步骤")
            for index, step in enumerate(steps_info, start=1):
                content_parts.append(f"\n### 第{index}步\n{step}")
        if recipe_properties.get("tags"):
            content_parts.append(f"\n## 标签\n{recipe_properties['tags']}")
        return "\n".join(content_parts)

    def _append_semantic_section(
        self,
        *,
        full_content: str,
        semantics: Dict[str, Any],
    ) -> str:
        semantic_lines = self._build_semantic_lines(semantics)
        if not semantic_lines:
            return full_content
        return full_content + "\n\n## 语义标签\n" + "\n".join(semantic_lines)

    @staticmethod
    def _build_semantic_lines(semantics: Dict[str, Any]) -> List[str]:
        semantic_lines: List[str] = []
        if semantics["flavor_tags"]:
            semantic_lines.append(f"风味标签: {', '.join(semantics['flavor_tags'])}")
        if semantics["technique_tags"]:
            semantic_lines.append(f"技法标签: {', '.join(semantics['technique_tags'])}")
        if semantics["diet_tags"]:
            semantic_lines.append(f"饮食标签: {', '.join(semantics['diet_tags'])}")
        if semantics["health_tags"]:
            semantic_lines.append(f"健康标签: {', '.join(semantics['health_tags'])}")
        if semantics["cuisine_style_tags"]:
            semantic_lines.append(f"菜系风格标签: {', '.join(semantics['cuisine_style_tags'])}")
        if semantics["ingredient_category_tags"]:
            semantic_lines.append(
                f"食材类别标签: {', '.join(semantics['ingredient_category_tags'])}"
            )
        if semantics["time_profile_tags"]:
            semantic_lines.append(f"时间轮廓标签: {', '.join(semantics['time_profile_tags'])}")
        if semantics["difficulty_level_tags"]:
            semantic_lines.append(f"难度标签: {', '.join(semantics['difficulty_level_tags'])}")
        contribution_items = semantics["semantic_relations"].get("CONTRIBUTES_TO") or []
        if contribution_items:
            relation_text = [
                f"{'/'.join(item['causes'])} -> {item['effect']}" for item in contribution_items
            ]
            semantic_lines.append(f"语义贡献: {'; '.join(relation_text)}")
        return semantic_lines
