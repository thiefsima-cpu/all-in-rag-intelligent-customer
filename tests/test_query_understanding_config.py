from __future__ import annotations

import unittest

from rag_modules.configuration import ConfigurationError, load_config
from rag_modules.configuration.env import EnvConfigSource


class QueryUnderstandingConfigTests(unittest.TestCase):
    def test_query_understanding_domain_payload_is_nested(self) -> None:
        config = load_config()

        domain_payload = config.to_domain_dict()["query_understanding"]

        self.assertIn("policy", domain_payload)
        self.assertIn("planner", domain_payload)
        self.assertIn("semantics", domain_payload)
        self.assertNotIn("query_plan_cache_size", domain_payload)
        self.assertEqual(
            domain_payload["planner"]["cache_size"],
            config.query_understanding.planner.cache_size,
        )

    def test_flat_access_and_flat_serialization_are_retired(self) -> None:
        config = load_config()

        with self.assertRaises(AttributeError):
            getattr(config, "query_plan_cache_size")
        with self.assertRaises(AttributeError):
            getattr(config.query_understanding, "query_plan_cache_size")
        with self.assertRaises(AttributeError):
            getattr(
                config.query_understanding,
                "query_semantic_combined_strategy_complexity_threshold",
            )

        payload = config.to_dict()
        self.assertIn("query_understanding", payload)
        self.assertIn("planner", payload["query_understanding"])
        self.assertIn("semantics", payload["query_understanding"])
        self.assertNotIn("query_plan_cache_size", payload)
        self.assertNotIn("query_semantic_combined_strategy_complexity_threshold", payload)

    def test_only_nested_overrides_target_query_understanding_structure(self) -> None:
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
        self.assertEqual(nested_override.query_understanding.planner.cache_size, 64)
        self.assertEqual(
            (
                nested_override.query_understanding.semantics.routing.combined_strategy_complexity_threshold
            ),
            0.77,
        )

        with self.assertRaises(ConfigurationError) as flat_context:
            config.with_overrides({"query_plan_cache_size": 32})
        flat_message = str(flat_context.exception)
        self.assertIn("overrides", flat_message)
        self.assertIn("GraphRAGConfig.with_overrides", flat_message)
        self.assertIn("query_plan_cache_size", flat_message)
        self.assertIn("extra", flat_message)

        with self.assertRaises(ConfigurationError) as nested_context:
            config.with_overrides(
                {
                    "query_understanding": {
                        "query_semantic_combined_strategy_complexity_threshold": 0.81,
                    }
                }
            )
        nested_message = str(nested_context.exception)
        self.assertIn("overrides", nested_message)
        self.assertIn(
            "query_understanding.query_semantic_combined_strategy_complexity_threshold",
            nested_message,
        )
        self.assertIn("extra", nested_message)

    def test_milvus_dimension_must_match_embedding_dimension(self) -> None:
        config = load_config()

        with self.assertRaisesRegex(ValueError, "MILVUS_DIMENSION must match EMBEDDING_DIMENSION"):
            config.with_overrides(
                {
                    "storage": {"milvus_dimension": config.models.embedding_dimension + 1},
                }
            )

    def test_query_understanding_env_values_target_nested_structure(self) -> None:
        config = load_config(
            source=EnvConfigSource(
                environ={
                    "QUERY_PLAN_CACHE_SIZE": "21",
                    "QUERY_SEMANTIC_COMBINED_STRATEGY_COMPLEXITY_THRESHOLD": "0.73",
                    "QUERY_SEMANTIC_SOURCE_ENTITY_LIMIT": "5",
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

    def test_query_understanding_policy_selector_is_nested(self) -> None:
        config = load_config()

        payload = config.to_domain_dict()["query_understanding"]

        self.assertIn("policy", payload)
        self.assertEqual("c9-default-v1", payload["policy"]["bundle"])
        self.assertEqual("c9-default-v1", config.query_understanding.policy.bundle)
        self.assertEqual("", config.query_understanding.policy.bundle_path)

    def test_query_understanding_policy_selector_accepts_env_override(self) -> None:
        config = load_config(
            source=EnvConfigSource(environ={"QUERY_POLICY_BUNDLE": "c9-default-v1"})
        )

        self.assertEqual("c9-default-v1", config.query_understanding.policy.bundle)

    def test_query_understanding_policy_selector_rejects_flat_override(self) -> None:
        config = load_config()

        with self.assertRaises(ConfigurationError) as context:
            config.with_overrides({"query_policy_bundle": "c9-default-v1"})

        self.assertIn("query_policy_bundle", str(context.exception))


if __name__ == "__main__":
    unittest.main()
