"""Recipe-document materialization over loaded graph data."""

from __future__ import annotations

import logging
from collections import defaultdict
from collections.abc import Iterable, Mapping

from ...domain.shared.semantic_schema import infer_recipe_semantics
from ...runtime.json_types import JsonObject, coerce_json_object
from ...runtime_contracts import Neo4jDriverPort
from ...safe_logging import log_failure
from ...text_document import TextDocument
from .models import GraphNode, PreparedIngredientInput, PreparedStepInput

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
        driver: Neo4jDriverPort,
        database: str,
        recipes: Iterable[GraphNode],
    ) -> list[TextDocument]:
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

        documents: list[TextDocument] = []
        for recipe_id in recipe_ids:
            recipe = recipe_map[recipe_id]
            try:
                documents.append(
                    self.build_document(
                        recipe=recipe,
                        ingredients=ingredients_by_recipe.get(recipe_id, []),
                        steps=steps_by_recipe.get(recipe_id, []),
                    )
                )
            except Exception as exc:
                log_failure(
                    logger,
                    logging.WARNING,
                    "build_failed",
                    code="BUILD_FAILED",
                    error=exc,
                )
        return documents

    def _load_ingredients_by_recipe(
        self,
        *,
        driver: Neo4jDriverPort,
        database: str,
        recipe_ids: list[str],
    ) -> dict[str, list[PreparedIngredientInput]]:
        ingredients_by_recipe: dict[str, list[PreparedIngredientInput]] = defaultdict(list)
        with driver.session(database=database) as session:
            for record in session.run(RECIPE_INGREDIENTS_QUERY, {"recipe_ids": recipe_ids}):
                recipe_id = str(record["recipe_id"])
                ingredients_by_recipe[recipe_id].append(
                    PreparedIngredientInput(
                        recipe_id=recipe_id,
                        name=str(record.get("name") or ""),
                        category=str(record.get("category") or ""),
                        amount=str(record.get("amount") or ""),
                        unit=str(record.get("unit") or ""),
                        description=str(record.get("description") or ""),
                    )
                )
        return dict(ingredients_by_recipe)

    def _load_steps_by_recipe(
        self,
        *,
        driver: Neo4jDriverPort,
        database: str,
        recipe_ids: list[str],
    ) -> dict[str, list[PreparedStepInput]]:
        steps_by_recipe: dict[str, list[PreparedStepInput]] = defaultdict(list)
        with driver.session(database=database) as session:
            for record in session.run(RECIPE_STEPS_QUERY, {"recipe_ids": recipe_ids}):
                recipe_id = str(record["recipe_id"])
                steps_by_recipe[recipe_id].append(
                    PreparedStepInput(
                        recipe_id=recipe_id,
                        name=str(record.get("name") or ""),
                        description=str(record.get("description") or ""),
                        step_number=_int_value(record.get("stepNumber")),
                        methods=str(record.get("methods") or ""),
                        tools=str(record.get("tools") or ""),
                        time_estimate=str(record.get("timeEstimate") or ""),
                        step_order=_int_value(record.get("stepOrder")),
                    )
                )
        return dict(steps_by_recipe)

    def build_document(
        self,
        *,
        recipe: GraphNode,
        ingredients: list[PreparedIngredientInput],
        steps: list[PreparedStepInput],
    ) -> TextDocument:
        recipe_name = recipe.name
        recipe_properties: JsonObject = dict(recipe.properties or {})
        ingredients_info = [self._format_ingredient_line(item) for item in ingredients]
        steps_info = [self._format_step_text(item) for item in steps]

        full_content = self._compose_recipe_content(
            recipe_name=recipe_name,
            recipe_properties=recipe_properties,
            ingredients_info=ingredients_info,
            steps_info=steps_info,
        )
        semantics = coerce_json_object(
            infer_recipe_semantics(
                recipe_properties=recipe_properties,
                ingredients=ingredients_info,
                steps=steps_info,
                full_content=full_content,
            )
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
                "flavor_tags": semantics.get("flavor_tags", []),
                "technique_tags": semantics.get("technique_tags", []),
                "diet_tags": semantics.get("diet_tags", []),
                "health_tags": semantics.get("health_tags", []),
                "cuisine_style_tags": semantics.get("cuisine_style_tags", []),
                "ingredient_category_tags": semantics.get("ingredient_category_tags", []),
                "time_profile_tags": semantics.get("time_profile_tags", []),
                "difficulty_level_tags": semantics.get("difficulty_level_tags", []),
                "semantic_relations": semantics.get("semantic_relations", {}),
                "doc_type": "recipe",
                "content_length": len(full_content),
            },
        )

    @staticmethod
    def _format_ingredient_line(ingredient: PreparedIngredientInput) -> str:
        text = ingredient.name
        category = ingredient.category
        if category:
            text += f" [{category}]"
        amount = ingredient.amount
        unit = ingredient.unit
        if amount or unit:
            text += f" ({amount or ''}{unit or ''})"
        if ingredient.description:
            text += f" - {ingredient.description}"
        return text.strip()

    @staticmethod
    def _format_step_text(step: PreparedStepInput) -> str:
        parts = [f"步骤: {step.name}"]
        if step.description:
            parts.append(f"描述: {step.description}")
        if step.methods:
            parts.append(f"方法: {step.methods}")
        if step.tools:
            parts.append(f"工具: {step.tools}")
        if step.time_estimate:
            parts.append(f"时间: {step.time_estimate}")
        return "\n".join(parts)

    def _compose_recipe_content(
        self,
        *,
        recipe_name: str,
        recipe_properties: Mapping[str, object],
        ingredients_info: list[str],
        steps_info: list[str],
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
        semantics: Mapping[str, object],
    ) -> str:
        semantic_lines = self._build_semantic_lines(semantics)
        if not semantic_lines:
            return full_content
        return full_content + "\n\n## 语义标签\n" + "\n".join(semantic_lines)

    @staticmethod
    def _build_semantic_lines(semantics: Mapping[str, object]) -> list[str]:
        semantic_lines: list[str] = []
        flavor_tags = _string_values(semantics.get("flavor_tags"))
        technique_tags = _string_values(semantics.get("technique_tags"))
        diet_tags = _string_values(semantics.get("diet_tags"))
        health_tags = _string_values(semantics.get("health_tags"))
        cuisine_style_tags = _string_values(semantics.get("cuisine_style_tags"))
        ingredient_category_tags = _string_values(semantics.get("ingredient_category_tags"))
        time_profile_tags = _string_values(semantics.get("time_profile_tags"))
        difficulty_level_tags = _string_values(semantics.get("difficulty_level_tags"))

        if flavor_tags:
            semantic_lines.append(f"风味标签: {', '.join(flavor_tags)}")
        if technique_tags:
            semantic_lines.append(f"技法标签: {', '.join(technique_tags)}")
        if diet_tags:
            semantic_lines.append(f"饮食标签: {', '.join(diet_tags)}")
        if health_tags:
            semantic_lines.append(f"健康标签: {', '.join(health_tags)}")
        if cuisine_style_tags:
            semantic_lines.append(f"菜系风格标签: {', '.join(cuisine_style_tags)}")
        if ingredient_category_tags:
            semantic_lines.append(f"食材类别标签: {', '.join(ingredient_category_tags)}")
        if time_profile_tags:
            semantic_lines.append(f"时间轮廓标签: {', '.join(time_profile_tags)}")
        if difficulty_level_tags:
            semantic_lines.append(f"难度标签: {', '.join(difficulty_level_tags)}")
        semantic_relations = coerce_json_object(semantics.get("semantic_relations"))
        contribution_items = semantic_relations.get("CONTRIBUTES_TO")
        if contribution_items:
            relation_text = [
                f"{'/'.join(_string_values(item_payload.get('causes')))} "
                f"-> {item_payload.get('effect') or ''}"
                for item_payload in (
                    coerce_json_object(item) for item in _object_values(contribution_items)
                )
            ]
            semantic_lines.append(f"语义贡献: {'; '.join(relation_text)}")
        return semantic_lines


def _int_value(value: object) -> int:
    if isinstance(value, (bool, int, float, str)):
        try:
            return int(value)
        except (TypeError, ValueError):
            return 0
    return 0


def _object_values(value: object) -> list[object]:
    if isinstance(value, list):
        return list(value)
    return []


def _string_values(value: object) -> list[str]:
    if isinstance(value, str):
        return [value] if value else []
    if isinstance(value, list):
        return [str(item) for item in value if str(item)]
    return []
