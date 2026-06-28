"""
Generic query constraint extraction and recipe-level filtering helpers.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Dict, Iterable, List, Optional, Tuple

from langchain_core.documents import Document

if TYPE_CHECKING:
    from ...contracts import QuerySemanticRuntimeSettings

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
        semantic_settings: QuerySemanticRuntimeSettings | None = None,
    ):
        if semantic_settings is None:
            from ...contracts import QuerySemanticRuntimeSettings

            semantic_settings = QuerySemanticRuntimeSettings()
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


class RecipeConstraintMatcher:
    def __init__(self, documents: List[Document]):
        self.documents = documents

    @staticmethod
    def _haystack(doc: Document) -> str:
        metadata = doc.metadata or {}
        pieces = [
            doc.page_content or "",
            str(metadata.get("recipe_name", "")),
            str(metadata.get("category", "")),
            str(metadata.get("cuisine_type", "")),
            str(metadata.get("prep_time", "")),
            str(metadata.get("cook_time", "")),
            str(metadata.get("servings", "")),
            " ".join(metadata.get("flavor_tags") or []),
            " ".join(metadata.get("technique_tags") or []),
            " ".join(metadata.get("diet_tags") or []),
            " ".join(metadata.get("health_tags") or []),
            " ".join(metadata.get("cuisine_style_tags") or []),
            " ".join(metadata.get("ingredient_category_tags") or []),
            " ".join(metadata.get("time_profile_tags") or []),
            " ".join(metadata.get("difficulty_level_tags") or []),
            str(metadata.get("semantic_relations", "")),
        ]
        return "\n".join(pieces)

    @staticmethod
    def _contains_any(haystack: str, terms: List[str]) -> bool:
        return any(term and term in haystack for term in terms)

    @staticmethod
    def _contains_all(haystack: str, terms: List[str]) -> bool:
        return all(term in haystack for term in terms if term)

    @staticmethod
    def _recipe_minutes(
        doc: Document,
    ) -> Tuple[Optional[int], Optional[int], Optional[int]]:
        metadata = doc.metadata or {}
        prep = parse_minutes(metadata.get("prep_time"))
        cook = parse_minutes(metadata.get("cook_time"))
        total = None
        if prep is not None and cook is not None:
            total = prep + cook
        return prep, cook, total

    def score(
        self,
        doc: Document,
        constraints: QueryConstraints,
    ) -> Tuple[bool, float, List[str]]:
        if not constraints or not constraints.has_constraints():
            return True, 0.0, []

        text = self._haystack(doc)
        metadata = doc.metadata or {}
        cuisine = str(metadata.get("cuisine_type", ""))
        category = str(metadata.get("category", ""))
        prep, cook, total = self._recipe_minutes(doc)

        if self._contains_any(
            text,
            constraints.exclude_terms + constraints.excluded_ingredients,
        ):
            return False, 0.0, ["命中排除词"]
        if constraints.excluded_cuisine_terms and self._contains_any(
            cuisine,
            constraints.excluded_cuisine_terms,
        ):
            return False, 0.0, ["命中排除菜系"]
        if (
            constraints.max_prep_minutes is not None
            and prep is not None
            and prep > constraints.max_prep_minutes
        ):
            return False, 0.0, ["准备时间超限"]
        if (
            constraints.max_cook_minutes is not None
            and cook is not None
            and cook > constraints.max_cook_minutes
        ):
            return False, 0.0, ["烹饪时间超限"]
        if (
            constraints.max_total_minutes is not None
            and total is not None
            and total > constraints.max_total_minutes
        ):
            return False, 0.0, ["总时间超限"]

        score = 0.0
        reasons: List[str] = []
        weighted_terms = [
            (constraints.ingredients, 3.0, "食材匹配"),
            (constraints.cuisine_terms, 2.5, "菜系匹配"),
            (constraints.category_terms, 2.0, "类别匹配"),
            (constraints.include_terms, 1.5, "主题匹配"),
            (constraints.health_terms, 1.5, "健康偏好匹配"),
            (constraints.preference_terms, 1.0, "偏好匹配"),
        ]
        for terms, weight, label in weighted_terms:
            hits = [term for term in terms if term in text]
            if hits:
                score += weight * len(hits)
                reasons.append(f"{label}: {', '.join(hits[:4])}")

        if constraints.cuisine_terms and self._contains_any(
            cuisine,
            constraints.cuisine_terms,
        ):
            score += 1.0
        if constraints.category_terms and self._contains_any(
            category,
            constraints.category_terms,
        ):
            score += 1.0
        if constraints.max_total_minutes is not None:
            if total is not None:
                score += 2.0
                reasons.append(f"时间约束命中: {total}分钟")
            else:
                score -= 0.5
                reasons.append("时间信息不完整")

        return True, score, reasons

    def filter_and_rank(
        self,
        constraints: QueryConstraints,
        min_score: float = 0.0,
        limit: int = 20,
    ) -> List[Document]:
        scored = []
        for doc in self.documents:
            keep, score, reasons = self.score(doc, constraints)
            if not keep or score < min_score:
                continue
            metadata = dict(doc.metadata)
            metadata["constraint_score"] = score
            metadata["constraint_reasons"] = reasons
            metadata["search_type"] = metadata.get(
                "search_type",
                "constraint_recipe",
            )
            scored.append(Document(page_content=doc.page_content, metadata=metadata))

        scored.sort(
            key=lambda d: d.metadata.get("constraint_score", 0.0),
            reverse=True,
        )
        return scored[:limit]
