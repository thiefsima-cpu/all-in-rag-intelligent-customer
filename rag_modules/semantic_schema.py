"""
Semantic schema enrichment for recipes.

This stage derives stable semantic tags from recipe text and metadata so the
graph can answer cuisine-style, ingredient-category, and health-constrained
questions without relying only on loose text matching.
"""

from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List

from .query_constraints import parse_minutes

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


_FLAVOR_TERMS = [
    "麻辣",
    "香辣",
    "酸辣",
    "鲜香",
    "咸鲜",
    "清淡",
    "微辣",
    "甜香",
    "蒜香",
    "葱香",
    "酱香",
    "鱼香",
    "椒香",
    "焦香",
]

_TECHNIQUE_TERMS = [
    "炒",
    "爆炒",
    "炖",
    "焖",
    "蒸",
    "煮",
    "煎",
    "炸",
    "烤",
    "烘烤",
    "烧",
    "卤",
    "拌",
    "焯",
    "汆",
    "腌制",
    "上浆",
    "挂糊",
    "勾芡",
    "翻炒",
]

_DIET_TAG_TERMS = [
    "素食",
    "素菜",
    "清真",
    "家常",
    "快手",
    "低热量",
    "无糖",
    "少盐",
    "低盐",
    "低卡",
]

_HEALTH_TAG_TERMS = [
    "糖尿病",
    "低糖",
    "控糖",
    "少油",
    "清淡",
    "低脂",
    "减脂",
    "减肥",
    "高血压",
    "控盐",
    "低盐",
]

_CUISINE_STYLE_TERMS = [
    "川菜",
    "粤菜",
    "湘菜",
    "鲁菜",
    "苏菜",
    "浙菜",
    "闽菜",
    "徽菜",
    "东北菜",
    "京菜",
    "家常菜",
    "素菜",
    "荤菜",
]

_INGREDIENT_CATEGORY_TERMS = [
    "蔬菜",
    "肉类",
    "禽类",
    "蛋类",
    "豆制品",
    "水产",
    "海鲜",
    "菌菇",
    "主食",
    "谷物",
    "调味品",
    "乳制品",
    "水果",
    "根茎",
    "坚果",
    "香料",
]

_CONTRIBUTION_HINTS = {
    "麻辣": ["花椒", "辣椒", "豆瓣酱", "辣椒油", "麻椒"],
    "鲜香": ["葱", "姜", "蒜", "蚝油", "生抽", "高汤", "鸡汤"],
    "软嫩": ["上浆", "淀粉", "蛋清", "腌制", "滑油"],
    "酥脆": ["炸", "挂糊", "油温", "脆皮"],
    "清爽": ["黄瓜", "生菜", "凉拌", "少油", "焯水"],
}

_TECHNIQUE_EFFECT_HINTS = {
    "软嫩": ["上浆", "淀粉", "蛋清", "腌制", "滑油"],
    "酥脆": ["炸", "挂糊", "油温", "复炸"],
    "入味": ["腌制", "焖", "炖", "卤", "慢煮"],
    "增香": ["爆炒", "炝锅", "煸香", "煎", "烤"],
}


def _contains_terms(text: str, terms: Iterable[str]) -> List[str]:
    return [term for term in terms if term and term in text]


def _normalize_tags(value: Any) -> List[str]:
    if value in (None, ""):
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return [item for item in re.split(r"[,，、;\s]+", str(value)) if item]


def _unique(values: Iterable[str]) -> List[str]:
    return list(dict.fromkeys(str(value).strip() for value in values if str(value).strip()))


def _extract_ingredient_categories(ingredients: List[str], haystack: str) -> List[str]:
    matched = []
    for ingredient in ingredients:
        matched.extend(_contains_terms(ingredient, _INGREDIENT_CATEGORY_TERMS))
    matched.extend(_contains_terms(haystack, _INGREDIENT_CATEGORY_TERMS))
    return _unique(matched)


def _extract_cuisine_styles(recipe_properties: Dict[str, Any], haystack: str) -> List[str]:
    matched = []
    matched.extend(
        _contains_terms(str(recipe_properties.get("cuisineType", "")), _CUISINE_STYLE_TERMS)
    )
    matched.extend(
        _contains_terms(str(recipe_properties.get("category", "")), _CUISINE_STYLE_TERMS)
    )
    matched.extend(_contains_terms(haystack, _CUISINE_STYLE_TERMS))
    return _unique(matched)


def _infer_total_minutes(recipe_properties: Dict[str, Any]) -> int | None:
    minutes = []
    for key in ("prepTime", "cookTime"):
        parsed = parse_minutes(recipe_properties.get(key))
        if parsed is not None:
            minutes.append(parsed)
    if minutes:
        return sum(minutes)

    for key in ("timeEstimate", "duration", "cookingTime"):
        parsed = parse_minutes(recipe_properties.get(key))
        if parsed is not None:
            return parsed
    return None


def _extract_time_profiles(recipe_properties: Dict[str, Any], haystack: str) -> List[str]:
    total_minutes = _infer_total_minutes(recipe_properties)
    matched: List[str] = []

    if total_minutes is not None:
        if total_minutes <= 15:
            matched.extend(["快手", "15分钟内", "半小时内", "30分钟内", "1小时内", "60分钟内"])
        elif total_minutes <= 30:
            matched.extend(["快手", "半小时内", "30分钟内", "1小时内", "60分钟内"])
        elif total_minutes <= 60:
            matched.extend(["1小时内", "60分钟内"])
        else:
            matched.extend(["1小时以上", "60分钟以上"])

    matched.extend(
        _contains_terms(
            haystack,
            [
                "快手",
                "15分钟内",
                "半小时内",
                "30分钟内",
                "1小时内",
                "60分钟内",
                "1小时以上",
                "60分钟以上",
            ],
        )
    )
    return _unique(matched)


def _extract_difficulty_levels(recipe_properties: Dict[str, Any], haystack: str) -> List[str]:
    raw_difficulty = recipe_properties.get("difficulty")
    matched: List[str] = []

    numeric_difficulty = None
    try:
        if raw_difficulty not in (None, ""):
            numeric_difficulty = float(str(raw_difficulty))
    except (TypeError, ValueError):
        numeric_difficulty = None

    if numeric_difficulty is not None:
        if numeric_difficulty <= 2:
            matched.extend(["简单", "快手", "新手"])
        elif numeric_difficulty <= 3:
            matched.append("中等")
        else:
            matched.extend(["困难", "进阶"])
    else:
        matched.extend(
            _contains_terms(
                str(raw_difficulty or ""), ["简单", "快手", "新手", "中等", "困难", "进阶"]
            )
        )

    matched.extend(_contains_terms(haystack, ["简单", "快手", "新手", "中等", "困难", "进阶"]))
    return _unique(matched)


def infer_recipe_semantics(
    recipe_properties: Dict[str, Any],
    ingredients: List[str],
    steps: List[str],
    full_content: str,
) -> Dict[str, Any]:
    haystack = "\n".join(
        [
            full_content or "",
            str(recipe_properties.get("description", "")),
            str(recipe_properties.get("category", "")),
            str(recipe_properties.get("cuisineType", "")),
            " ".join(_normalize_tags(recipe_properties.get("tags"))),
            " ".join(ingredients),
            " ".join(steps),
        ]
    )

    flavor_tags = _unique(_contains_terms(haystack, _FLAVOR_TERMS))
    technique_tags = _unique(_contains_terms(haystack, _TECHNIQUE_TERMS))
    diet_tags = _unique(_contains_terms(haystack, _DIET_TAG_TERMS))
    health_tags = _unique(_contains_terms(haystack, _HEALTH_TAG_TERMS))
    cuisine_style_tags = _extract_cuisine_styles(recipe_properties, haystack)
    ingredient_category_tags = _extract_ingredient_categories(ingredients, haystack)
    time_profile_tags = _extract_time_profiles(recipe_properties, haystack)
    difficulty_level_tags = _extract_difficulty_levels(recipe_properties, haystack)

    contribution_hints = []
    ingredient_contributions = []
    for effect, causes in _CONTRIBUTION_HINTS.items():
        matched_causes = _contains_terms(haystack, causes)
        if matched_causes:
            contribution_hints.append(
                {
                    "effect": effect,
                    "causes": _unique(matched_causes),
                }
            )
            for cause in matched_causes:
                ingredient_contributions.append(
                    {
                        "source": cause,
                        "effect": effect,
                    }
                )

    technique_effects = []
    for effect, techniques in _TECHNIQUE_EFFECT_HINTS.items():
        matched_techniques = _contains_terms(haystack, techniques)
        if matched_techniques:
            for technique in _unique(matched_techniques):
                technique_effects.append(
                    {
                        "source": technique,
                        "effect": effect,
                    }
                )

    semantic_relations = {
        "HAS_FLAVOR": flavor_tags,
        "USES_TECHNIQUE": technique_tags,
        "HAS_DIET_TAG": diet_tags,
        "HAS_HEALTH_TAG": health_tags,
        "HAS_CUISINE_STYLE": cuisine_style_tags,
        "HAS_INGREDIENT_CATEGORY": ingredient_category_tags,
        "HAS_TIME_PROFILE": time_profile_tags,
        "HAS_DIFFICULTY_LEVEL": difficulty_level_tags,
        "CONTRIBUTES_TO": contribution_hints,
        "INGREDIENT_CONTRIBUTES_TO": ingredient_contributions,
        "TECHNIQUE_MODIFIES_TEXTURE": technique_effects,
    }

    return {
        "flavor_tags": flavor_tags,
        "technique_tags": technique_tags,
        "diet_tags": diet_tags,
        "health_tags": health_tags,
        "cuisine_style_tags": cuisine_style_tags,
        "ingredient_category_tags": ingredient_category_tags,
        "time_profile_tags": time_profile_tags,
        "difficulty_level_tags": difficulty_level_tags,
        "semantic_relations": semantic_relations,
    }
