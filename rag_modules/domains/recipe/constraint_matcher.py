"""Recipe-owned structured constraint matching."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from ...kernel.documents import TextDocument
from ...kernel.json_types import (
    as_string_list,
    coerce_float,
    coerce_json_object,
    coerce_json_value,
)
from ...kernel.time_parsing import parse_minutes


@dataclass(frozen=True, slots=True)
class _RecipeConstraintValues:
    ingredients: list[str]
    excluded_ingredients: list[str]
    cuisine_terms: list[str]
    excluded_cuisine_terms: list[str]
    category_terms: list[str]
    health_terms: list[str]
    preference_terms: list[str]
    max_prep_minutes: int | None
    max_cook_minutes: int | None
    max_total_minutes: int | None

    @classmethod
    def from_constraints(cls, constraints: Mapping[str, object]) -> _RecipeConstraintValues:
        extension = coerce_json_object(constraints.get("extension"))
        temporal_filters = coerce_json_object(constraints.get("temporal_filters"))
        return cls(
            ingredients=as_string_list(extension.get("ingredients")),
            excluded_ingredients=as_string_list(extension.get("excluded_ingredients")),
            cuisine_terms=as_string_list(extension.get("cuisine_terms")),
            excluded_cuisine_terms=as_string_list(extension.get("excluded_cuisine_terms")),
            category_terms=as_string_list(extension.get("category_terms")),
            health_terms=as_string_list(extension.get("health_terms")),
            preference_terms=as_string_list(extension.get("preference_terms")),
            max_prep_minutes=parse_minutes(extension.get("max_prep_minutes")),
            max_cook_minutes=parse_minutes(extension.get("max_cook_minutes")),
            max_total_minutes=parse_minutes(temporal_filters.get("max_duration_minutes")),
        )


class RecipeConstraintMatcher:
    def __init__(self, documents: list[TextDocument]) -> None:
        self.documents = documents

    @staticmethod
    def _haystack(doc: TextDocument) -> str:
        metadata = doc.metadata or {}
        values = [
            doc.content or "",
            *(
                str(metadata.get(key, ""))
                for key in (
                    "recipe_name",
                    "category",
                    "cuisine_type",
                    "prep_time",
                    "cook_time",
                    "servings",
                )
            ),
            *(
                " ".join(as_string_list(metadata.get(key)))
                for key in (
                    "flavor_tags",
                    "technique_tags",
                    "diet_tags",
                    "health_tags",
                    "cuisine_style_tags",
                    "ingredient_category_tags",
                    "time_profile_tags",
                    "difficulty_level_tags",
                )
            ),
            str(metadata.get("semantic_relations", "")),
        ]
        return "\n".join(values)

    @staticmethod
    def _contains_any(haystack: str, terms: list[str]) -> bool:
        return any(term and term in haystack for term in terms)

    @staticmethod
    def _recipe_minutes(doc: TextDocument) -> tuple[int | None, int | None, int | None]:
        metadata = doc.metadata or {}
        prep = parse_minutes(metadata.get("prep_time"))
        cook = parse_minutes(metadata.get("cook_time"))
        total = prep + cook if prep is not None and cook is not None else None
        return prep, cook, total

    def _reject_reason(
        self,
        *,
        text: str,
        cuisine: str,
        excluded_entity_terms: list[str],
        values: _RecipeConstraintValues,
        minutes: tuple[int | None, int | None, int | None],
    ) -> str:
        prep, cook, total = minutes
        if self._contains_any(text, excluded_entity_terms + values.excluded_ingredients):
            return "命中排除词"
        if self._contains_any(cuisine, values.excluded_cuisine_terms):
            return "命中排除菜系"
        if (
            values.max_prep_minutes is not None
            and prep is not None
            and prep > values.max_prep_minutes
        ):
            return "准备时间超限"
        if (
            values.max_cook_minutes is not None
            and cook is not None
            and cook > values.max_cook_minutes
        ):
            return "烹饪时间超限"
        if (
            values.max_total_minutes is not None
            and total is not None
            and total > values.max_total_minutes
        ):
            return "总时间超限"
        return ""

    def _weighted_score(
        self,
        *,
        text: str,
        cuisine: str,
        category: str,
        entity_terms: list[str],
        values: _RecipeConstraintValues,
        total_minutes: int | None,
    ) -> tuple[float, list[str]]:
        weighted_terms = (
            (values.ingredients, 3.0, "食材匹配"),
            (values.cuisine_terms, 2.5, "菜系匹配"),
            (values.category_terms, 2.0, "类别匹配"),
            (entity_terms, 1.5, "主题匹配"),
            (values.health_terms, 1.5, "健康偏好匹配"),
            (values.preference_terms, 1.0, "偏好匹配"),
        )
        score = 0.0
        reasons: list[str] = []
        for terms, weight, label in weighted_terms:
            hits = [term for term in terms if term in text]
            if hits:
                score += weight * len(hits)
                reasons.append(f"{label}: {', '.join(hits[:4])}")
        score += 1.0 if self._contains_any(cuisine, values.cuisine_terms) else 0.0
        score += 1.0 if self._contains_any(category, values.category_terms) else 0.0
        if values.max_total_minutes is not None:
            score += 2.0 if total_minutes is not None else -0.5
            reasons.append(
                f"时间约束命中: {total_minutes}分钟"
                if total_minutes is not None
                else "时间信息不完整"
            )
        return score, reasons

    def score(
        self,
        doc: TextDocument,
        constraints: object,
    ) -> tuple[bool, float, list[str]]:
        if not isinstance(constraints, Mapping) or not any(constraints.values()):
            return True, 0.0, []
        payload = {str(key): value for key, value in constraints.items()}
        text = self._haystack(doc)
        metadata = doc.metadata or {}
        cuisine = str(metadata.get("cuisine_type", ""))
        category = str(metadata.get("category", ""))
        minutes = self._recipe_minutes(doc)
        values = _RecipeConstraintValues.from_constraints(payload)
        reject_reason = self._reject_reason(
            text=text,
            cuisine=cuisine,
            excluded_entity_terms=as_string_list(payload.get("excluded_entity_terms")),
            values=values,
            minutes=minutes,
        )
        if reject_reason:
            return False, 0.0, [reject_reason]
        score, reasons = self._weighted_score(
            text=text,
            cuisine=cuisine,
            category=category,
            entity_terms=as_string_list(payload.get("entity_terms")),
            values=values,
            total_minutes=minutes[2],
        )
        return True, score, reasons

    def filter_and_rank(
        self,
        constraints: object,
        min_score: float = 0.0,
        limit: int = 20,
    ) -> list[TextDocument]:
        scored = []
        for doc in self.documents:
            keep, score, reasons = self.score(doc, constraints)
            if not keep or score < min_score:
                continue
            metadata = dict(doc.metadata)
            metadata["constraint_score"] = score
            metadata["constraint_reasons"] = coerce_json_value(reasons)
            metadata.setdefault("search_type", "constraint_domain")
            scored.append(TextDocument(content=doc.content, metadata=metadata))
        scored.sort(
            key=lambda item: coerce_float(item.metadata.get("constraint_score"), 0.0),
            reverse=True,
        )
        return scored[:limit]


__all__ = ["RecipeConstraintMatcher"]
