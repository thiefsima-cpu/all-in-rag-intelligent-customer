from __future__ import annotations

import unittest

from rag_modules.answer_evidence_builder import AnswerEvidenceItem, AnswerEvidencePackage
from rag_modules.generation import AnswerPlan, GenerationPromptBuilder, GenerationSettings
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
