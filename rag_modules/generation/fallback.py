"""Fallback behavior for generation failures."""

from __future__ import annotations

from ..answer_evidence_builder import AnswerEvidencePackage
from .clients import generation_failure_code


def build_evidence_only_fallback_answer(
    *,
    package: AnswerEvidencePackage,
    error: Exception,
    max_items: int,
) -> str:
    if not package.items:
        return "抱歉，当前既没有足够证据，也无法调用生成模型完成回答。"

    lines = [
        "基于当前检索证据，我先给出一个保底回答：",
    ]
    for index, item in enumerate(package.items[:max_items], start=1):
        lines.append(f"{index}. {item.recipe_name or item.citation}（依据：{item.citation}）")
        matched_terms = "、".join(item.matched_terms[:6])
        if matched_terms:
            lines.append(f"   - 匹配到的问题要点：{matched_terms}")
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
        if graph_claim:
            lines.append(f"   - 图谱关系证据：{graph_claim}")
        if text_claim:
            lines.append(f"   - 文本证据：{text_claim}")
        if item.constraint_reasons:
            lines.append(f"   - 约束提示：{'、'.join(item.constraint_reasons[:3])}")

    lines.append("当前回答为证据保底版，未补充证据之外的信息。")
    del error
    lines.append("生成模型暂时不可用，已自动切换为证据保底回答。")
    return "\n".join(lines)


def should_skip_model_fallback(error: Exception, *, fallback_on_timeout: bool) -> bool:
    failure_code = generation_failure_code(error)
    if failure_code in {
        "generation_provider_empty_choices",
        "generation_provider_empty_content",
        "generation_latency_budget_exceeded",
    }:
        return True
    if fallback_on_timeout:
        return False
    return failure_code == "generation_provider_timeout"
