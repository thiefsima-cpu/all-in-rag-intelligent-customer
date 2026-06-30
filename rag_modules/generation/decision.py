"""Decision logic for direct vs two-stage answer generation."""

from __future__ import annotations

from ..answer_evidence_builder import AnswerEvidencePackage
from ..query_policy import get_query_policy
from ..runtime import AnalysisInput, analysis_strategy_name, analysis_value
from .models import GenerationDecision, GenerationMode, GenerationSettings


def decide_generation_mode(
    *,
    package: AnswerEvidencePackage,
    settings: GenerationSettings,
    analysis: AnalysisInput = None,
) -> GenerationDecision:
    decision_policy = get_query_policy().generation.decision
    reasons = decision_policy["reasons"]
    high_pressure_margin = float(decision_policy["high_pressure_margin"])

    if not settings.enable_two_stage:
        return GenerationDecision(
            mode=GenerationMode.DIRECT,
            reason=str(reasons["two_stage_disabled"]),
            evidence_limit=settings.direct_max_evidence_items,
        )

    if not analysis:
        has_graph_evidence = any(
            item.graph_paths or any(unit.get("is_graph_evidence") for unit in item.evidence_units)
            for item in package.items
        )
        if has_graph_evidence and len(package.items) > 1:
            return GenerationDecision(
                mode=GenerationMode.TWO_STAGE,
                reason=str(reasons["graph_without_analysis"]),
                evidence_limit=settings.two_stage_max_evidence_items,
            )
        return GenerationDecision(
            mode=GenerationMode.DIRECT,
            reason=str(reasons["no_route_analysis"]),
            evidence_limit=settings.direct_max_evidence_items,
        )

    strategy = analysis_strategy_name(analysis)
    complexity = float(analysis_value(analysis, "query_complexity", 0.0) or 0.0)
    relationship_intensity = float(analysis_value(analysis, "relationship_intensity", 0.0) or 0.0)
    reasoning_required = bool(analysis_value(analysis, "reasoning_required", False))

    if strategy == "graph_rag":
        return GenerationDecision(
            mode=GenerationMode.TWO_STAGE,
            reason=str(reasons["graph_rag"]),
            evidence_limit=settings.two_stage_max_evidence_items,
        )

    if strategy == "combined" and (
        complexity >= settings.two_stage_complexity_threshold
        or relationship_intensity >= settings.two_stage_relationship_threshold
        or reasoning_required
    ):
        return GenerationDecision(
            mode=GenerationMode.TWO_STAGE,
            reason=str(reasons["combined_pressure"]),
            evidence_limit=settings.two_stage_max_evidence_items,
        )

    if (
        complexity >= settings.two_stage_complexity_threshold + high_pressure_margin
        or relationship_intensity
        >= settings.two_stage_relationship_threshold + high_pressure_margin
    ):
        return GenerationDecision(
            mode=GenerationMode.TWO_STAGE,
            reason=str(reasons["high_pressure"]),
            evidence_limit=settings.two_stage_max_evidence_items,
        )

    return GenerationDecision(
        mode=GenerationMode.DIRECT,
        reason=str(reasons["simple"]),
        evidence_limit=settings.direct_max_evidence_items,
    )
