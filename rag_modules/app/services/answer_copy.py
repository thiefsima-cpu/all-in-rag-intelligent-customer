"""Answer workflow product-copy contract owned by application services."""

from __future__ import annotations

from typing import Protocol


class AnswerWorkflowCopy(Protocol):
    no_evidence_answer: str
    answer_failed: str
    user_question_template: str
    query_routing_started: str
    answer_generation_started: str
    streaming_interrupted_fallback: str
    answer_complete_template: str
    strategy_summary_template: str
    strategy_icon_hybrid_traditional: str
    strategy_icon_graph_rag: str
    strategy_icon_combined: str
    strategy_icon_default: str
    document_summary_template: str
    document_summary_total_template: str
    unknown_recipe_name: str
    unknown_search_type: str


__all__ = ["AnswerWorkflowCopy"]
