"""Planning logic for answer generation."""

from __future__ import annotations

from typing import Any, List

from ..answer_evidence_builder import AnswerEvidencePackage
from ..runtime_models import analysis_strategy_name
from .client import GenerationClientAdapter
from .models import AnswerPlan, GenerationSettings
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

    def build_answer_plan(
        self,
        question: str,
        package: AnswerEvidencePackage,
        analysis: Any = None,
    ) -> AnswerPlan:
        if self.settings.planner_mode == "rule":
            return self._build_rule_based_plan(question, package)
        if self.settings.planner_mode == "hybrid" and self._can_use_rule_plan(package, analysis):
            return self._build_rule_based_plan(question, package)

        response = self.client_adapter.create_completion(
            prompt=self.prompt_builder.build_plan_prompt(question, package),
            temperature=self.settings.planner_temperature,
            max_tokens=self.settings.planner_max_tokens,
            timeout=self.settings.timeout_seconds,
        )
        plan_data = self.client_adapter.load_json_payload(self.client_adapter.response_text(response))
        plan = AnswerPlan.from_dict(plan_data)
        if not plan.outline:
            plan.outline = ["先直接回答问题", "再解释依据与关键关系", "最后说明证据边界"]
        return plan

    def _can_use_rule_plan(self, package: AnswerEvidencePackage, analysis: Any = None) -> bool:
        strategy = analysis_strategy_name(analysis)
        if strategy in {"graph_rag", "hybrid_traditional"}:
            return True
        return len(package.items) <= self.settings.plan_max_evidence_items

    def _build_rule_based_plan(self, question: str, package: AnswerEvidencePackage) -> AnswerPlan:
        answer_type = self.prompt_builder.infer_answer_type(question)
        has_graph_claims = any(
            unit.get("is_graph_evidence")
            for item in package.items
            for unit in item.evidence_units
        )
        reasoning_mode = "grounded_with_limited_inference" if has_graph_claims else "grounded"
        outline = ["先给出直接答案", "再说明关键证据与关系", "最后交代证据边界"]
        key_points: List[dict] = []

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
            claim = graph_claim or text_claim or f"{item.recipe_name} 是当前问题的相关证据。"
            key_points.append(
                {
                    "title": item.recipe_name or item.citation,
                    "claim": claim,
                    "citations": [item.citation],
                    "use_graph_evidence": bool(graph_claim),
                }
            )

        missing_information: List[str] = []
        if self.prompt_builder.question_needs_relation_explanation(question) and not has_graph_claims:
            missing_information.append("当前证据缺少足够的图谱关系来完整解释关系链。")
        if len(package.items) < 2 and answer_type in {"recommendation", "comparison"}:
            missing_information.append("当前候选证据较少，覆盖面有限。")

        cautions = []
        if has_graph_claims:
            cautions.append("涉及图谱关系的结论应表述为有限推断，避免过度外延。")
        if missing_information:
            cautions.append("证据不足的部分需要显式说明，不要补充未检索到的事实。")

        return AnswerPlan(
            answer_type=answer_type,
            reasoning_mode=reasoning_mode,
            outline=outline,
            key_points=key_points,
            cautions=cautions,
            missing_information=missing_information,
        )
