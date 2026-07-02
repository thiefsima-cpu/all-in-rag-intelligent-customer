"""Planning logic for answer generation."""

from __future__ import annotations

from typing import Literal

from ..answer_evidence_builder import AnswerEvidencePackage
from ..runtime import AnalysisInput, AnswerContext, analysis_strategy_name
from ..runtime.json_types import JsonObject
from .clients import GenerationClientAdapter
from .models import AnswerPlan, GenerationPlannerMode, GenerationSettings
from .prompt_builder import GenerationPromptBuilder


class GenerationPlanner:
    """Build answer plans using either rules or an LLM planner."""

    def __init__(
        self,
        *,
        settings: GenerationSettings,
        client_adapter: GenerationClientAdapter,
        prompt_builder: GenerationPromptBuilder,
    ) -> None:
        self.settings = settings
        self.client_adapter = client_adapter
        self.prompt_builder = prompt_builder
        self.rule_plan_policy = self.prompt_builder.generation_policy.rule_plan

    def build_answer_plan_from_context(
        self,
        answer_context: AnswerContext,
        *,
        timeout_seconds: float | None = None,
    ) -> AnswerPlan:
        package = self.prompt_builder._package_from_context(answer_context)
        return self._build_answer_plan_for_package(
            answer_context.question,
            package,
            answer_context.analysis,
            timeout_seconds=timeout_seconds,
        )

    def _build_answer_plan_for_package(
        self,
        question: str,
        package: AnswerEvidencePackage,
        analysis: AnalysisInput = None,
        *,
        timeout_seconds: float | None = None,
    ) -> AnswerPlan:
        if self.settings.planner_mode is GenerationPlannerMode.RULE:
            return self._build_rule_based_plan(question, package)
        if self.settings.planner_mode is GenerationPlannerMode.HYBRID and self._can_use_rule_plan(
            package, analysis
        ):
            return self._build_rule_based_plan(question, package)

        rendered_prompt = self.prompt_builder.render_plan_prompt(question, package)
        response = self.client_adapter.create_completion(
            prompt=rendered_prompt.text,
            temperature=self.settings.planner_temperature,
            max_tokens=self.settings.planner_max_tokens,
            timeout=(self.settings.timeout_seconds if timeout_seconds is None else timeout_seconds),
        )
        plan_data = self.client_adapter.load_json_payload(
            self.client_adapter.response_text(response)
        )
        plan = AnswerPlan.from_dict(plan_data)
        if not plan.outline:
            plan.outline = self._rule_plan_list("fallback_outline")
        return plan

    def _can_use_rule_plan(
        self,
        package: AnswerEvidencePackage,
        analysis: AnalysisInput = None,
    ) -> bool:
        strategy = analysis_strategy_name(analysis)
        if strategy in {"graph_rag", "hybrid_traditional"}:
            return True
        return len(package.items) <= self.settings.plan_max_evidence_items

    def _rule_plan_list(self, key: Literal["default_outline", "fallback_outline"]) -> list[str]:
        values = (
            self.rule_plan_policy.default_outline
            if key == "default_outline"
            else self.rule_plan_policy.fallback_outline
        )
        return [str(item) for item in values if str(item).strip()]

    def _rule_plan_text(
        self,
        key: Literal[
            "graph_caution",
            "missing_relation_evidence",
            "sparse_evidence",
            "missing_information_caution",
            "fallback_claim_template",
        ],
    ) -> str:
        return str(getattr(self.rule_plan_policy, key))

    def _fallback_claim(self, *, recipe_name: str, citation: str) -> str:
        template = self._rule_plan_text("fallback_claim_template")
        return template.format(recipe_name=recipe_name or citation, citation=citation)

    def _build_rule_based_plan(
        self,
        question: str,
        package: AnswerEvidencePackage,
    ) -> AnswerPlan:
        answer_type = self.prompt_builder.infer_answer_type(question)
        has_graph_claims = any(
            unit.get("is_graph_evidence") for item in package.items for unit in item.evidence_units
        )
        reasoning_mode = "grounded_with_limited_inference" if has_graph_claims else "grounded"
        key_points: list[JsonObject] = []

        for item in package.items[: self.settings.plan_max_evidence_items]:
            graph_claim = next(
                (
                    unit.get("claim")
                    for unit in item.evidence_units
                    if unit.get("is_graph_evidence") and unit.get("claim")
                ),
                "",
            )
            text_claim = next(
                (
                    unit.get("claim")
                    for unit in item.evidence_units
                    if not unit.get("is_graph_evidence") and unit.get("claim")
                ),
                "",
            )
            claim = (
                graph_claim
                or text_claim
                or self._fallback_claim(
                    recipe_name=item.recipe_name,
                    citation=item.citation,
                )
            )
            key_points.append(
                {
                    "title": item.recipe_name or item.citation,
                    "claim": claim,
                    "citations": [item.citation],
                    "use_graph_evidence": bool(graph_claim),
                }
            )

        missing_information: list[str] = []
        if (
            self.prompt_builder.question_needs_relation_explanation(question)
            and not has_graph_claims
        ):
            missing_information.append(self._rule_plan_text("missing_relation_evidence"))
        if len(package.items) < 2 and answer_type in {"recommendation", "comparison"}:
            missing_information.append(self._rule_plan_text("sparse_evidence"))

        cautions: list[str] = []
        if has_graph_claims:
            cautions.append(self._rule_plan_text("graph_caution"))
        if missing_information:
            cautions.append(self._rule_plan_text("missing_information_caution"))

        return AnswerPlan(
            answer_type=answer_type,
            reasoning_mode=reasoning_mode,
            outline=self._rule_plan_list("default_outline"),
            key_points=key_points,
            cautions=cautions,
            missing_information=missing_information,
        )
