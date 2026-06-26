"""Generation configuration section model."""

from __future__ import annotations

from .base import ConfigSection


class GenerationSettings(ConfigSection):
    temperature: float = 0.1
    max_tokens: int = 2048
    generation_timeout_seconds: int = 25
    generation_stream_timeout_seconds: int = 25
    generation_latency_budget_seconds: int = 24
    generation_plan_max_tokens: int = 600
    generation_compose_max_tokens: int = 1100
    generation_direct_max_tokens: int = 700
    generation_plan_temperature: float = 0.0
    generation_planner_mode: str = "rule"
    generation_max_retries: int = 1
    generation_request_retries: int = 1
    generation_stream_retries: int = 1
    generation_evidence_max_chars: int = 700
    generation_enable_two_stage: bool = True
    generation_two_stage_complexity_threshold: float = 0.68
    generation_two_stage_relationship_threshold: float = 0.58
    generation_direct_max_evidence_items: int = 2
    generation_two_stage_max_evidence_items: int = 3
    generation_plan_max_evidence_items: int = 2
    generation_max_graph_paths_per_item: int = 1
    generation_max_evidence_units_per_item: int = 4
    generation_include_document_evidence: bool = False
    generation_compose_include_content: bool = False
    generation_fallback_on_timeout: bool = False


__all__ = ["GenerationSettings"]
