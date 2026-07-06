from __future__ import annotations

import unittest

from rag_modules.build_pipeline.graph_preparation.loader import (
    COOKING_STEPS_QUERY,
    INGREDIENTS_QUERY,
    RECIPES_QUERY,
)


class GraphDataLoaderQueryTests(unittest.TestCase):
    def test_source_node_queries_exclude_derived_semantic_schema_nodes(self) -> None:
        for query, alias in (
            (RECIPES_QUERY, "r"),
            (INGREDIENTS_QUERY, "i"),
            (COOKING_STEPS_QUERY, "s"),
        ):
            with self.subTest(alias=alias):
                normalized = " ".join(query.split())
                self.assertIn(
                    f"coalesce({alias}.createdFrom, '') <> 'semantic_schema'",
                    normalized,
                )


if __name__ == "__main__":
    unittest.main()
