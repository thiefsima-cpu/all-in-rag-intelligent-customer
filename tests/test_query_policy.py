from __future__ import annotations

import unittest

from rag_modules.query_policy import get_planner_prompt_template, get_query_policy


class QueryPolicyTests(unittest.TestCase):
    def test_policy_uses_clean_utf8_terms(self) -> None:
        policy = get_query_policy()

        self.assertIn("麻辣", policy.term_group("flavor_terms"))
        self.assertIn("关系", policy.term_group("relation_markers"))
        self.assertNotIn("楹昏荆", policy.term_group("flavor_terms"))
        self.assertNotIn("鍏崇郴", policy.term_group("relation_markers"))

    def test_planner_prompt_template_has_required_placeholders(self) -> None:
        template = get_planner_prompt_template()

        self.assertIn("{graph_query_types_text}", template)
        self.assertIn("{relation_types_text}", template)
        self.assertIn("{preferred_relation_types_text}", template)
        self.assertIn("{query}", template)
        self.assertIn("graph_rag", template)
        self.assertNotIn("鍥捐氨", template)


if __name__ == "__main__":
    unittest.main()
