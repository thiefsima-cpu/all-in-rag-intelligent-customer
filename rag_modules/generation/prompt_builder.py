"""Prompt construction helpers for answer generation."""

from __future__ import annotations

import json

from ..answer_evidence_builder import AnswerEvidencePackage
from ..runtime import AnswerContext
from .models import AnswerPlan, GenerationSettings, RenderedPrompt


class GenerationPromptBuilder:
    """Build prompts for planning, direct answering, and final composition."""

    def __init__(self, settings: GenerationSettings, *, evidence_max_chars: int) -> None:
        self.settings = settings
        self.evidence_max_chars = evidence_max_chars

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
            metadata={"max_plan_items": self.settings.plan_max_evidence_items},
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
            metadata={"include_content": True},
        )

    def build_plan_prompt(self, question: str, package: AnswerEvidencePackage) -> str:
        evidence_summary = json.dumps(
            package.summarize_for_plan(max_items=self.settings.plan_max_evidence_items),
            ensure_ascii=False,
            indent=2,
        )
        return f"""
你是一个中式烹饪问答系统的“回答规划器”。请先阅读证据摘要，再为最终回答生成一个严格依证的回答计划。
用户问题：{question}

证据摘要：{evidence_summary}

要求：
- 只能基于给定证据规划，不要补充证据外事实。
- 如果问题涉及关系解释、因果链、食材与步骤之间的作用，请优先指出哪些结论要依赖图谱证据。
- 如果证据不足，要明确写出信息缺口。
- `citations` 只能引用给定的“菜谱证据 N”。
- 只返回 JSON，不要输出额外说明。

JSON 结构：
{{
  "answer_type": "direct_answer | recommendation | explanation | comparison",
  "reasoning_mode": "grounded | grounded_with_limited_inference",
  "outline": ["回答结构1", "回答结构2"],
  "key_points": [
    {{
      "title": "小标题",
      "claim": "要表达的核心结论",
      "citations": ["菜谱证据 1"],
      "use_graph_evidence": true
    }}
  ],
  "cautions": ["需要提醒用户的边界"],
  "missing_information": ["证据缺口"]
}}
"""

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
        return f"""
你是一位专业的中式烹饪检索问答助手。请根据“回答计划”和“检索证据”生成最终答案。
用户问题：{question}

回答计划：{json.dumps(plan.to_dict(), ensure_ascii=False, indent=2)}

检索证据：
{evidence_text}

回答要求：
- 先直接回答用户问题，再展开解释。
- 只能根据证据作答，不要编造证据中不存在的事实。
- 如果结论依赖图谱关系，请明确说明这是“图谱关系支持的有限推断”。
- 每个关键结论后尽量标注依据，例如“依据：菜谱证据 1”或“依据：菜谱证据 1 的图谱关系”。
- 如果证据不足，明确指出不足，不要强行补齐。
- 用自然、清晰、专业的中文作答。
"""

    def build_direct_answer_prompt(self, question: str, package: AnswerEvidencePackage) -> str:
        evidence_text = package.to_context_text(
            include_content=True,
            include_document_evidence=False,
            max_graph_paths=self.settings.max_graph_paths_per_item,
            max_evidence_units=self.settings.max_evidence_units_per_item,
            max_content_chars=self.evidence_max_chars,
        )
        return f"""
你是一位专业的中式烹饪检索问答助手。请只根据下面的检索证据回答问题。
检索证据：
{evidence_text}

用户问题：{question}

回答要求：
- 先给出直接答案，再补充必要解释。
- 结论必须能在证据中找到依据。
- 尽量在关键结论后标注“依据：菜谱证据 N”。
- 如果涉及关系解释，可以引用图谱关系，但不要超出证据做过度推断。
- 如果证据不足，请明确说明。
- 用简洁、自然的中文回答。
"""

    @staticmethod
    def package_has_structured_claims(package: AnswerEvidencePackage) -> bool:
        return any(item.evidence_units or item.graph_paths for item in package.items)

    @staticmethod
    def infer_answer_type(question: str) -> str:
        question = (question or "").strip()
        if any(token in question for token in ("推荐", "适合", "可以做什么", "有哪些")):
            return "recommendation"
        if any(token in question for token in ("区别", "比较", "差异", "对比")):
            return "comparison"
        if any(token in question for token in ("为什么", "关系", "影响", "原因", "如何形成")):
            return "explanation"
        return "direct_answer"

    @staticmethod
    def question_needs_relation_explanation(question: str) -> bool:
        question = (question or "").strip()
        return any(token in question for token in ("为什么", "关系", "影响", "如何形成", "之间"))
