from __future__ import annotations

import unittest

from langchain_core.documents import Document

from rag_modules.domain.shared.query_constraints import QueryConstraints
from rag_modules.retrieval.evidence import RecipeConstraintMatcher


class RecipeConstraintMatcherTests(unittest.TestCase):
    def test_filter_and_rank_scores_matching_recipe_terms(self) -> None:
        docs = [
            Document(
                page_content="Mapo tofu with tofu and chili",
                metadata={
                    "recipe_name": "Mapo Tofu",
                    "category": "main",
                    "cuisine_type": "Sichuan",
                    "cook_time": "20 min",
                    "prep_time": "10 min",
                },
            ),
            Document(
                page_content="Home tofu with tofu",
                metadata={
                    "recipe_name": "Home Tofu",
                    "category": "main",
                    "cuisine_type": "Home",
                    "cook_time": "25 min",
                    "prep_time": "5 min",
                },
            ),
        ]
        matcher = RecipeConstraintMatcher(docs)

        results = matcher.filter_and_rank(
            QueryConstraints(
                ingredients=["tofu"],
                cuisine_terms=["Sichuan"],
                include_terms=["chili"],
            ),
            limit=5,
        )

        self.assertEqual(
            [doc.metadata["recipe_name"] for doc in results],
            ["Mapo Tofu", "Home Tofu"],
        )
        self.assertGreater(results[0].metadata["constraint_score"], 0)
        self.assertEqual(results[0].metadata["search_type"], "constraint_recipe")
        self.assertTrue(results[0].metadata["constraint_reasons"])
        self.assertEqual(results[0].page_content, "Mapo tofu with tofu and chili")

    def test_filter_and_rank_excludes_blocked_terms_and_cuisine(self) -> None:
        docs = [
            Document(
                page_content="Pork belly with garlic",
                metadata={"recipe_name": "Pork Belly", "cuisine_type": "Sichuan"},
            ),
            Document(
                page_content="Light tofu soup",
                metadata={"recipe_name": "Tofu Soup", "cuisine_type": "Cantonese"},
            ),
        ]
        matcher = RecipeConstraintMatcher(docs)

        results = matcher.filter_and_rank(
            QueryConstraints(
                include_terms=["tofu"],
                exclude_terms=["pork"],
                excluded_cuisine_terms=["Sichuan"],
            ),
            limit=5,
        )

        self.assertEqual([doc.metadata["recipe_name"] for doc in results], ["Tofu Soup"])

    def test_filter_and_rank_applies_time_limits(self) -> None:
        docs = [
            Document(
                page_content="Quick tofu",
                metadata={
                    "recipe_name": "Quick Tofu",
                    "prep_time": "5 min",
                    "cook_time": "10 min",
                },
            ),
            Document(
                page_content="Slow stew tofu",
                metadata={
                    "recipe_name": "Slow Tofu",
                    "prep_time": "20 min",
                    "cook_time": "60 min",
                },
            ),
        ]
        matcher = RecipeConstraintMatcher(docs)

        results = matcher.filter_and_rank(
            QueryConstraints(
                include_terms=["tofu"],
                max_total_minutes=30,
                max_prep_minutes=10,
                max_cook_minutes=20,
            ),
            limit=5,
        )

        self.assertEqual([doc.metadata["recipe_name"] for doc in results], ["Quick Tofu"])
        self.assertIn("constraint_score", results[0].metadata)
        self.assertIn("constraint_reasons", results[0].metadata)


if __name__ == "__main__":
    unittest.main()
