from __future__ import annotations

import unittest

from rag_modules.contracts.query_constraints import QueryConstraints
from rag_modules.domains.recipe.constraint_matcher import RecipeConstraintMatcher
from rag_modules.kernel.documents import TextDocument


class RecipeConstraintMatcherTests(unittest.TestCase):
    def test_filter_and_rank_scores_matching_recipe_terms(self) -> None:
        docs = [
            TextDocument(
                content="Mapo tofu with tofu and chili",
                metadata={
                    "recipe_name": "Mapo Tofu",
                    "category": "main",
                    "cuisine_type": "Sichuan",
                    "cook_time": "20 min",
                    "prep_time": "10 min",
                },
            ),
            TextDocument(
                content="Home tofu with tofu",
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
                entity_terms=["chili"],
                extension={"ingredients": ["tofu"], "cuisine_terms": ["Sichuan"]},
            ).to_dict(),
            limit=5,
        )

        self.assertEqual(
            [doc.metadata["recipe_name"] for doc in results],
            ["Mapo Tofu", "Home Tofu"],
        )
        self.assertGreater(results[0].metadata["constraint_score"], 0)
        self.assertEqual(results[0].metadata["search_type"], "constraint_domain")
        self.assertTrue(results[0].metadata["constraint_reasons"])
        self.assertEqual(results[0].page_content, "Mapo tofu with tofu and chili")

    def test_filter_and_rank_excludes_blocked_terms_and_cuisine(self) -> None:
        docs = [
            TextDocument(
                content="Pork belly with garlic",
                metadata={"recipe_name": "Pork Belly", "cuisine_type": "Sichuan"},
            ),
            TextDocument(
                content="Light tofu soup",
                metadata={"recipe_name": "Tofu Soup", "cuisine_type": "Cantonese"},
            ),
        ]
        matcher = RecipeConstraintMatcher(docs)

        results = matcher.filter_and_rank(
            QueryConstraints(
                entity_terms=["tofu"],
                excluded_entity_terms=["pork"],
                extension={"excluded_cuisine_terms": ["Sichuan"]},
            ).to_dict(),
            limit=5,
        )

        self.assertEqual([doc.metadata["recipe_name"] for doc in results], ["Tofu Soup"])

    def test_filter_and_rank_applies_time_limits(self) -> None:
        docs = [
            TextDocument(
                content="Quick tofu",
                metadata={
                    "recipe_name": "Quick Tofu",
                    "prep_time": "5 min",
                    "cook_time": "10 min",
                },
            ),
            TextDocument(
                content="Slow stew tofu",
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
                entity_terms=["tofu"],
                temporal_filters={"max_duration_minutes": 30},
                extension={"max_prep_minutes": 10, "max_cook_minutes": 20},
            ).to_dict(),
            limit=5,
        )

        self.assertEqual([doc.metadata["recipe_name"] for doc in results], ["Quick Tofu"])
        self.assertIn("constraint_score", results[0].metadata)
        self.assertIn("constraint_reasons", results[0].metadata)


if __name__ == "__main__":
    unittest.main()
