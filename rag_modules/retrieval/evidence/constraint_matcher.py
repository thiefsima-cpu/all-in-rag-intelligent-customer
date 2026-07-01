"""Constraint matching over retrieval evidence documents."""

from __future__ import annotations

from typing import List, Optional, Tuple

from ...domain.shared.query_constraints import QueryConstraints, parse_minutes
from ...text_document import TextDocument


class RecipeConstraintMatcher:
    def __init__(self, documents: List[TextDocument]):
        self.documents = documents

    @staticmethod
    def _haystack(doc: TextDocument) -> str:
        metadata = doc.metadata or {}
        pieces = [
            doc.content or "",
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
        doc: TextDocument,
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
        doc: TextDocument,
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
            return False, 0.0, ["\u547d\u4e2d\u6392\u9664\u8bcd"]
        if constraints.excluded_cuisine_terms and self._contains_any(
            cuisine,
            constraints.excluded_cuisine_terms,
        ):
            return False, 0.0, ["\u547d\u4e2d\u6392\u9664\u83dc\u7cfb"]
        if (
            constraints.max_prep_minutes is not None
            and prep is not None
            and prep > constraints.max_prep_minutes
        ):
            return False, 0.0, ["\u51c6\u5907\u65f6\u95f4\u8d85\u9650"]
        if (
            constraints.max_cook_minutes is not None
            and cook is not None
            and cook > constraints.max_cook_minutes
        ):
            return False, 0.0, ["\u70f9\u996a\u65f6\u95f4\u8d85\u9650"]
        if (
            constraints.max_total_minutes is not None
            and total is not None
            and total > constraints.max_total_minutes
        ):
            return False, 0.0, ["\u603b\u65f6\u95f4\u8d85\u9650"]

        score = 0.0
        reasons: List[str] = []
        weighted_terms = [
            (constraints.ingredients, 3.0, "\u98df\u6750\u5339\u914d"),
            (constraints.cuisine_terms, 2.5, "\u83dc\u7cfb\u5339\u914d"),
            (constraints.category_terms, 2.0, "\u7c7b\u522b\u5339\u914d"),
            (constraints.include_terms, 1.5, "\u4e3b\u9898\u5339\u914d"),
            (constraints.health_terms, 1.5, "\u5065\u5eb7\u504f\u597d\u5339\u914d"),
            (constraints.preference_terms, 1.0, "\u504f\u597d\u5339\u914d"),
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
                reasons.append(f"\u65f6\u95f4\u7ea6\u675f\u547d\u4e2d: {total}\u5206\u949f")
            else:
                score -= 0.5
                reasons.append("\u65f6\u95f4\u4fe1\u606f\u4e0d\u5b8c\u6574")

        return True, score, reasons

    def filter_and_rank(
        self,
        constraints: QueryConstraints,
        min_score: float = 0.0,
        limit: int = 20,
    ) -> List[TextDocument]:
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
            scored.append(doc.copy_with(metadata=metadata))

        scored.sort(
            key=lambda d: d.metadata.get("constraint_score", 0.0),
            reverse=True,
        )
        return scored[:limit]
