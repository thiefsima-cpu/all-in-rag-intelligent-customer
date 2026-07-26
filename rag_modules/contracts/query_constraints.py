"""
Generic query constraint extraction helpers.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Optional

from ..kernel.json_types import JsonObject, as_string_list, coerce_json_object
from ..kernel.time_parsing import parse_minutes


def loads_json_object(text: str) -> JsonObject:
    text = (text or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        value: object = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, flags=re.S)
        if not match:
            raise
        value = json.loads(match.group(0))
    if not isinstance(value, Mapping):
        raise ValueError("JSON payload must be an object")
    return {str(key): item for key, item in value.items()}


@dataclass
class QueryConstraints:
    include_terms: list[str] = field(default_factory=list)
    exclude_terms: list[str] = field(default_factory=list)
    ingredients: list[str] = field(default_factory=list)
    excluded_ingredients: list[str] = field(default_factory=list)
    cuisine_terms: list[str] = field(default_factory=list)
    excluded_cuisine_terms: list[str] = field(default_factory=list)
    category_terms: list[str] = field(default_factory=list)
    health_terms: list[str] = field(default_factory=list)
    preference_terms: list[str] = field(default_factory=list)
    max_total_minutes: Optional[int] = None
    max_prep_minutes: Optional[int] = None
    max_cook_minutes: Optional[int] = None
    needs_recipe_recommendation: bool = False

    @classmethod
    def from_dict(cls, data: Mapping[str, object] | None) -> "QueryConstraints":
        payload = data or {}
        time_data = payload.get("time")
        time_payload = time_data if isinstance(time_data, Mapping) else {}
        return cls(
            include_terms=as_string_list(payload.get("include_terms")),
            exclude_terms=as_string_list(payload.get("exclude_terms")),
            ingredients=as_string_list(payload.get("ingredients")),
            excluded_ingredients=as_string_list(payload.get("excluded_ingredients")),
            cuisine_terms=as_string_list(payload.get("cuisine_terms")),
            excluded_cuisine_terms=as_string_list(payload.get("excluded_cuisine_terms")),
            category_terms=as_string_list(payload.get("category_terms")),
            health_terms=as_string_list(payload.get("health_terms")),
            preference_terms=as_string_list(payload.get("preference_terms")),
            max_total_minutes=parse_minutes(time_payload.get("max_total_minutes")),
            max_prep_minutes=parse_minutes(time_payload.get("max_prep_minutes")),
            max_cook_minutes=parse_minutes(time_payload.get("max_cook_minutes")),
            needs_recipe_recommendation=bool(payload.get("needs_recipe_recommendation", False)),
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

    def to_dict(self) -> JsonObject:
        return coerce_json_object(
            {
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
        )


__all__ = ["QueryConstraints", "loads_json_object", "parse_minutes"]
