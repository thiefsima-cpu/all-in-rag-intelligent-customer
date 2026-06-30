"""Prompt construction helpers for answer generation."""

from __future__ import annotations

import json
from typing import Any

from ..answer_evidence_builder import AnswerEvidencePackage
from ..query_policy import get_query_policy
from ..runtime import AnswerContext, PolicySnapshot
from .models import AnswerPlan, GenerationSettings, RenderedPrompt


class GenerationPromptBuilder:
    """Build prompts for planning, direct answering, and final composition."""

    def __init__(self, settings: GenerationSettings, *, evidence_max_chars: int) -> None:
        self.settings = settings
        self.evidence_max_chars = evidence_max_chars
        self.policy_bundle = get_query_policy()
        self.generation_policy = self.policy_bundle.generation
        self.prompts = self.policy_bundle.prompts
        self.policy_snapshot = PolicySnapshot.from_metadata(self.policy_bundle.metadata)

    @staticmethod
    def _package_from_context(answer_context: AnswerContext) -> AnswerEvidencePackage:
        if answer_context.has_evidence_package:
            return AnswerEvidencePackage.from_dict(answer_context.evidence_package)
        raise ValueError(
            "AnswerContext is missing evidence_package. Build evidence packing before prompt rendering."
        )

    def build_plan_prompt_from_context(self, answer_context: AnswerContext) -> str:
        return self.render_plan_prompt_from_context(answer_context).text

    def build_compose_prompt_from_context(
        self,
        answer_context: AnswerContext,
        plan: AnswerPlan,
    ) -> str:
        return self.render_compose_prompt_from_context(answer_context, plan).text

    def build_direct_answer_prompt_from_context(self, answer_context: AnswerContext) -> str:
        return self.render_direct_answer_prompt_from_context(answer_context).text

    def render_plan_prompt_from_context(self, answer_context: AnswerContext) -> RenderedPrompt:
        package = self._package_from_context(answer_context)
        return self.render_plan_prompt(
            answer_context.question,
            package,
        )

    def render_compose_prompt_from_context(
        self,
        answer_context: AnswerContext,
        plan: AnswerPlan,
    ) -> RenderedPrompt:
        package = self._package_from_context(answer_context)
        return self.render_compose_prompt(
            answer_context.question,
            package,
            plan,
        )

    def render_direct_answer_prompt_from_context(
        self,
        answer_context: AnswerContext,
    ) -> RenderedPrompt:
        package = self._package_from_context(answer_context)
        return self.render_direct_answer_prompt(
            answer_context.question,
            package,
        )

    def render_plan_prompt(self, question: str, package: AnswerEvidencePackage) -> RenderedPrompt:
        return RenderedPrompt(
            prompt_type="plan",
            question=question,
            text=self.build_plan_prompt(question, package),
            evidence_citations=package.citation_list,
            evidence_item_count=len(package.items),
            metadata={
                **self._policy_metadata(),
                "max_plan_items": self.settings.plan_max_evidence_items,
            },
        )

    def render_compose_prompt(
        self,
        question: str,
        package: AnswerEvidencePackage,
        plan: AnswerPlan,
    ) -> RenderedPrompt:
        return RenderedPrompt(
            prompt_type="compose",
            question=question,
            text=self.build_compose_prompt(question, package, plan),
            evidence_citations=package.citation_list,
            evidence_item_count=len(package.items),
            plan=plan.to_dict(),
            metadata={
                **self._policy_metadata(),
                "include_document_evidence": self.settings.include_document_evidence,
                "compose_include_content": self.settings.compose_include_content,
            },
        )

    def render_direct_answer_prompt(
        self,
        question: str,
        package: AnswerEvidencePackage,
    ) -> RenderedPrompt:
        return RenderedPrompt(
            prompt_type="direct",
            question=question,
            text=self.build_direct_answer_prompt(question, package),
            evidence_citations=package.citation_list,
            evidence_item_count=len(package.items),
            metadata={**self._policy_metadata(), "include_content": True},
        )

    def _policy_metadata(self) -> dict[str, Any]:
        return self.policy_snapshot.to_dict()

    def build_plan_prompt(self, question: str, package: AnswerEvidencePackage) -> str:
        evidence_summary = json.dumps(
            package.summarize_for_plan(max_items=self.settings.plan_max_evidence_items),
            ensure_ascii=False,
            indent=2,
        )
        return self.prompts.answer_plan.format(
            question=question,
            evidence_summary=evidence_summary,
        )

    def build_compose_prompt(
        self,
        question: str,
        package: AnswerEvidencePackage,
        plan: AnswerPlan,
    ) -> str:
        evidence_text = package.to_context_text(
            include_content=self.settings.compose_include_content
            or not self.package_has_structured_claims(package),
            include_document_evidence=self.settings.include_document_evidence,
            max_graph_paths=self.settings.max_graph_paths_per_item,
            max_evidence_units=self.settings.max_evidence_units_per_item,
            max_content_chars=self.evidence_max_chars,
        )
        return self.prompts.answer_compose.format(
            question=question,
            plan_json=json.dumps(plan.to_dict(), ensure_ascii=False, indent=2),
            evidence_text=evidence_text,
        )

    def build_direct_answer_prompt(self, question: str, package: AnswerEvidencePackage) -> str:
        evidence_text = package.to_context_text(
            include_content=True,
            include_document_evidence=False,
            max_graph_paths=self.settings.max_graph_paths_per_item,
            max_evidence_units=self.settings.max_evidence_units_per_item,
            max_content_chars=self.evidence_max_chars,
        )
        return self.prompts.answer_direct.format(question=question, evidence_text=evidence_text)

    @staticmethod
    def package_has_structured_claims(package: AnswerEvidencePackage) -> bool:
        return any(item.evidence_units or item.graph_paths for item in package.items)

    def infer_answer_type(self, question: str) -> str:
        question = (question or "").strip()
        for answer_type, config in self.generation_policy.answer_types.items():
            markers = tuple(str(marker) for marker in config.get("markers", ()))
            if markers and any(marker in question for marker in markers):
                return answer_type
        return str(self.generation_policy.decision["default_answer_type"])

    def question_needs_relation_explanation(self, question: str) -> bool:
        question = (question or "").strip()
        return any(
            marker in question for marker in self.generation_policy.relation_explanation_markers
        )
