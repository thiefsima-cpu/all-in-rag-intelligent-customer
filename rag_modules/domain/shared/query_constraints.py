"""
Generic query constraint extraction helpers.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional

logger = logging.getLogger(__name__)


def loads_json_object(text: str) -> Dict[str, Any]:
    text = (text or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, flags=re.S)
        if not match:
            raise
        return json.loads(match.group(0))


def _as_list(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value.strip() else []
    if isinstance(value, Iterable):
        return [str(item).strip() for item in value if str(item).strip()]
    return [str(value).strip()]


def parse_minutes(value: Any) -> Optional[int]:
    """Parse loose Chinese/English duration text into minutes."""
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        return int(value)

    text = str(value)
    nums = [float(x) for x in re.findall(r"\d+(?:\.\d+)?", text)]
    if not nums:
        return None

    total = 0.0
    hour_matches = re.findall(
        r"(\d+(?:\.\d+)?)\s*(?:小时|小時|h|hr|hour)",
        text,
        flags=re.I,
    )
    minute_matches = re.findall(
        r"(\d+(?:\.\d+)?)\s*(?:分钟|分鍾|min|minute)",
        text,
        flags=re.I,
    )
    if hour_matches or minute_matches:
        total += sum(float(x) * 60 for x in hour_matches)
        total += sum(float(x) for x in minute_matches)
        return int(round(total)) if total > 0 else None

    # For ranges like "15-20", use the upper bound to avoid violating max-time constraints.
    return int(round(max(nums)))


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


class QueryConstraintExtractor:
    def __init__(
        self,
        llm_client,
        model_name: str,
        semantic_settings: Any | None = None,
    ):
        self.llm_client = llm_client
        self.model_name = model_name
        self.semantic_settings = semantic_settings

    def extract(self, query: str) -> QueryConstraints:
        from ...query_understanding import infer_query_semantic_profile

        profile = infer_query_semantic_profile(
            query,
            settings=self.semantic_settings,
        )
        constraints = QueryConstraints.from_dict(profile.constraints)
        has_constraints = constraints.has_constraints()
        logger.info("Query constraints parsed: present=%s", has_constraints)
        return constraints
