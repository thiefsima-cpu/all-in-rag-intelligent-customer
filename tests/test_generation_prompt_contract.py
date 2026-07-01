from __future__ import annotations

import unittest

from rag_modules.answer_evidence_builder import AnswerEvidenceItem, AnswerEvidencePackage
from rag_modules.generation import (
    AnswerPlan,
    GenerationPlanner,
    GenerationPromptBuilder,
    GenerationSettings,
)
from rag_modules.runtime import AnswerContext


class GenerationPromptContractTests(unittest.TestCase):
    def _build_context(self) -> AnswerContext:
        package = AnswerEvidencePackage(
            question="why does dish A work",
            items=[
                AnswerEvidenceItem(
                    citation="Recipe Evidence 1",
                    recipe_id="recipe-1",
                    recipe_name="dish A",
                    confidence=0.92,
                    evidence_units=[{"claim": "ingredient X balances ingredient Y"}],
                    content="dish A balances ingredient X and Y",
                )
            ],
        )
        return AnswerContext(question=package.question).with_evidence_package(package)

    def test_direct_prompt_render_exposes_contract_metadata(self) -> None:
        builder = GenerationPromptBuilder(
            settings=GenerationSettings(),
            evidence_max_chars=700,
        )

        rendered = builder.render_direct_answer_prompt_from_context(self._build_context())

        self.assertEqual(rendered.prompt_type, "direct")
        self.assertEqual(rendered.question, "why does dish A work")
        self.assertEqual(rendered.evidence_citations, ["Recipe Evidence 1"])
        self.assertEqual(rendered.evidence_item_count, 1)
        self.assertTrue(rendered.text)

    def test_direct_prompt_render_includes_policy_metadata(self) -> None:
        builder = GenerationPromptBuilder(settings=GenerationSettings(), evidence_max_chars=700)

        rendered = builder.render_direct_answer_prompt_from_context(self._build_context())

        self.assertEqual("c9-default-policy-v1", rendered.metadata["policy_version"])
        self.assertEqual("c9-default-prompts-v1", rendered.metadata["prompt_version"])
        self.assertTrue(rendered.metadata["policy_hash"].startswith("sha256:"))
        self.assertIn("Recipe Evidence 1", rendered.text)

    def test_rule_plan_uses_policy_missing_information_template(self) -> None:
        prompt_builder = GenerationPromptBuilder(
            settings=GenerationSettings(), evidence_max_chars=700
        )
        planner = GenerationPlanner(
            settings=GenerationSettings(planner_mode="rule"),
            client_adapter=object(),
            prompt_builder=prompt_builder,
        )

        plan = planner.build_answer_plan_from_context(self._build_context())

        self.assertTrue(plan.outline)
        self.assertIsInstance(plan.missing_information, list)

    def test_policy_markers_drive_answer_type_and_relation_detection(self) -> None:
        builder = GenerationPromptBuilder(settings=GenerationSettings(), evidence_max_chars=700)

        self.assertEqual("recommendation", builder.infer_answer_type("推荐两道清淡家常菜"))
        self.assertEqual("comparison", builder.infer_answer_type("比较两道菜的区别"))
        self.assertEqual("explanation", builder.infer_answer_type("为什么这道菜更鲜香"))
        self.assertTrue(builder.question_needs_relation_explanation("为什么食材之间会互相影响"))

    def test_compose_prompt_render_carries_plan_payload(self) -> None:
        builder = GenerationPromptBuilder(
            settings=GenerationSettings(),
            evidence_max_chars=700,
        )
        plan = AnswerPlan(
            answer_type="explanation",
            reasoning_mode="grounded",
            key_points=[{"title": "point", "claim": "claim", "citations": ["Recipe Evidence 1"]}],
        )

        rendered = builder.render_compose_prompt_from_context(self._build_context(), plan)

        self.assertEqual(rendered.prompt_type, "compose")
        self.assertEqual(rendered.plan["answer_type"], "explanation")
        self.assertEqual(rendered.evidence_item_count, 1)
        self.assertIn("Recipe Evidence 1", rendered.evidence_citations)


if __name__ == "__main__":
    unittest.main()
