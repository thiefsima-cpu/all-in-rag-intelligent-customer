"""Fallback behavior for generation failures."""

from __future__ import annotations

from ..answer_evidence_builder import AnswerEvidencePackage
from ..query_policy import get_query_policy
from .clients import generation_failure_code


def build_evidence_only_fallback_answer(
    *,
    package: AnswerEvidencePackage,
    error: Exception,
    max_items: int,
) -> str:
    templates = get_query_policy().generation.fallback_answer
    if not package.items:
        return templates["empty_evidence"]

    lines = [templates["heading"]]
    for index, item in enumerate(package.items[:max_items], start=1):
        lines.append(
            templates["item_line"].format(
                index=index,
                title=item.recipe_name or item.citation,
                citation=item.citation,
            )
        )
        matched_terms = "、".join(item.matched_terms[:6])
        if matched_terms:
            lines.append(
                "   - " + templates["matched_terms"].format(matched_terms=matched_terms)
            )
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
            lines.append("   - " + templates["graph_claim"].format(claim=graph_claim))
        if text_claim:
            lines.append("   - " + templates["text_claim"].format(claim=text_claim))
        if item.constraint_reasons:
            lines.append(
                "   - "
                + templates["constraint_reasons"].format(
                    constraint_reasons="、".join(item.constraint_reasons[:3])
                )
            )

    del error
    lines.append(templates["boundary"])
    lines.append(templates["model_unavailable"])
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
