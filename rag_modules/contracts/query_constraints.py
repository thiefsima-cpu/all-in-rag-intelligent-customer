"""
Generic query constraint extraction helpers.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, cast

from ..kernel.time_parsing import parse_minutes


def loads_json_object(text: str) -> Dict[str, Any]:
    text = (text or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        return cast(Dict[str, Any], json.loads(text))
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, flags=re.S)
        if not match:
            raise
        return cast(Dict[str, Any], json.loads(match.group(0)))


def _as_list(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value.strip() else []
    if isinstance(value, Iterable):
        return [str(item).strip() for item in value if str(item).strip()]
    return [str(value).strip()]


@dataclass
class QueryConstraints:
    include_terms: List[str] = field(default_factory=list)
    exclude_terms: List[str] = field(default_factory=list)
    ingredients: List[str] = field(default_factory=list)
    excluded_ingredients: List[str] = field(default_factory=list)
    cuisine_terms: List[str] = field(default_factory=list)
    excluded_cuisine_terms: List[str] = field(default_factory=list)
    category_terms: List[str] = field(default_factory=list)
    health_terms: List[str] = field(default_factory=list)
    preference_terms: List[str] = field(default_factory=list)
    max_total_minutes: Optional[int] = None
    max_prep_minutes: Optional[int] = None
    max_cook_minutes: Optional[int] = None
    needs_recipe_recommendation: bool = False

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "QueryConstraints":
        time_data = data.get("time") or {}
        return cls(
            include_terms=_as_list(data.get("include_terms")),
            exclude_terms=_as_list(data.get("exclude_terms")),
            ingredients=_as_list(data.get("ingredients")),
            excluded_ingredients=_as_list(data.get("excluded_ingredients")),
            cuisine_terms=_as_list(data.get("cuisine_terms")),
            excluded_cuisine_terms=_as_list(data.get("excluded_cuisine_terms")),
            category_terms=_as_list(data.get("category_terms")),
            health_terms=_as_list(data.get("health_terms")),
            preference_terms=_as_list(data.get("preference_terms")),
            max_total_minutes=parse_minutes(time_data.get("max_total_minutes")),
            max_prep_minutes=parse_minutes(time_data.get("max_prep_minutes")),
            max_cook_minutes=parse_minutes(time_data.get("max_cook_minutes")),
            needs_recipe_recommendation=bool(data.get("needs_recipe_recommendation", False)),
        )

    def has_constraints(self) -> bool:
        return any(
            [
                self.include_terms,
                self.exclude_terms,
                self.ingredients,
                self.excluded_ingredients,
                self.cuisine_terms,
                self.excluded_cuisine_terms,
                self.category_terms,
                self.health_terms,
                self.preference_terms,
                self.max_total_minutes is not None,
                self.max_prep_minutes is not None,
                self.max_cook_minutes is not None,
            ]
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "include_terms": self.include_terms,
            "exclude_terms": self.exclude_terms,
            "ingredients": self.ingredients,
            "excluded_ingredients": self.excluded_ingredients,
            "cuisine_terms": self.cuisine_terms,
            "excluded_cuisine_terms": self.excluded_cuisine_terms,
            "category_terms": self.category_terms,
            "health_terms": self.health_terms,
            "preference_terms": self.preference_terms,
            "time": {
                "max_total_minutes": self.max_total_minutes,
                "max_prep_minutes": self.max_prep_minutes,
                "max_cook_minutes": self.max_cook_minutes,
            },
            "needs_recipe_recommendation": self.needs_recipe_recommendation,
        }


__all__ = ["QueryConstraints", "loads_json_object", "parse_minutes"]
