from __future__ import annotations

import unittest

from rag_modules.configuration.env import EnvConfigSource
from rag_modules.configuration import load_config


class QueryUnderstandingConfigTests(unittest.TestCase):
    def test_query_understanding_domain_payload_is_nested(self) -> None:
        config = load_config()

        domain_payload = config.to_domain_dict()["query_understanding"]

        self.assertIn("planner", domain_payload)
        self.assertIn("semantics", domain_payload)
        self.assertNotIn("query_plan_cache_size", domain_payload)
        self.assertEqual(
            domain_payload["planner"]["cache_size"],
            config.query_understanding.planner.cache_size,
        )

    def test_legacy_flat_access_and_flat_serialization_still_work(self) -> None:
        config = load_config()

        self.assertEqual(
            config.query_understanding.planner.cache_size,
            config.query_understanding.query_plan_cache_size,
        )
        self.assertEqual(
            config.query_understanding.semantics.routing.combined_strategy_complexity_threshold,
            config.query_understanding.query_semantic_combined_strategy_complexity_threshold,
        )

        flat_payload = config.to_dict()
        self.assertIn("query_plan_cache_size", flat_payload)
        self.assertIn("query_semantic_combined_strategy_complexity_threshold", flat_payload)
        self.assertNotIn("planner", flat_payload)
        self.assertNotIn("semantics", flat_payload)

    def test_nested_and_legacy_overrides_both_target_new_structure(self) -> None:
        config = load_config()

        nested_override = config.with_overrides(
            {
                "query_understanding": {
                    "planner": {"cache_size": 64},
                    "semantics": {
                        "routing": {"combined_strategy_complexity_threshold": 0.77},
                    },
                }
            }
        )
        legacy_override = config.with_overrides(
            {
                "query_plan_cache_size": 32,
                "query_semantic_combined_strategy_complexity_threshold": 0.81,
            }
        )

        self.assertEqual(nested_override.query_understanding.planner.cache_size, 64)
        self.assertEqual(
            nested_override.query_understanding.semantics.routing.combined_strategy_complexity_threshold,
            0.77,
        )
        self.assertEqual(legacy_override.query_understanding.planner.cache_size, 32)
        self.assertEqual(
            legacy_override.query_understanding.semantics.routing.combined_strategy_complexity_threshold,
            0.81,
        )

    def test_milvus_dimension_must_match_embedding_dimension(self) -> None:
        config = load_config()

        with self.assertRaisesRegex(ValueError, "MILVUS_DIMENSION must match EMBEDDING_DIMENSION"):
            config.with_overrides(
                {
                    "storage": {"milvus_dimension": config.models.embedding_dimension + 1},
                }
            )

    def test_query_understanding_env_aliases_target_nested_structure(self) -> None:
        config = load_config(
            source=EnvConfigSource(
                environ={
                    "QUERY_PLAN_CACHE_SIZE": "21",
                    "QUERY_SEMANTIC_COMBINED_STRATEGY_COMPLEXITY_THRESHOLD": "0.73",
                    "QUERY_PLAN_SOURCE_ENTITY_LIMIT": "5",
                }
            )
        )

        self.assertEqual(config.query_understanding.planner.cache_size, 21)
        self.assertEqual(
            config.query_understanding.semantics.routing.combined_strategy_complexity_threshold,
            0.73,
        )
        self.assertEqual(
            config.query_understanding.semantics.extraction.source_entity_limit,
            5,
        )


if __name__ == "__main__":
    unittest.main()
