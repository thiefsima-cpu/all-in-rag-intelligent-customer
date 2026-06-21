"""Generation configuration section loader."""

from __future__ import annotations

from typing import Any, Mapping

from ..env import EnvConfigSource
from ..models import GenerationSettings
from .common import mapping_defaults


def load_generation_settings(
    source: EnvConfigSource,
    defaults: Mapping[str, Any] | None = None,
) -> GenerationSettings:
    generation_defaults = mapping_defaults(defaults)
    return GenerationSettings(
        temperature=source.get_float(
            "TEMPERATURE", float(generation_defaults.get("temperature", 0.1))
        ),
        max_tokens=source.get_int("MAX_TOKENS", int(generation_defaults.get("max_tokens", 2048))),
        generation_timeout_seconds=source.get_int(
            "GENERATION_TIMEOUT_SECONDS",
            int(generation_defaults.get("generation_timeout_seconds", 25)),
        ),
        generation_stream_timeout_seconds=source.get_int(
            "GENERATION_STREAM_TIMEOUT_SECONDS",
            int(generation_defaults.get("generation_stream_timeout_seconds", 25)),
        ),
        generation_latency_budget_seconds=source.get_int(
            "GENERATION_LATENCY_BUDGET_SECONDS",
            int(generation_defaults.get("generation_latency_budget_seconds", 24)),
        ),
        generation_plan_max_tokens=source.get_int(
            "GENERATION_PLAN_MAX_TOKENS",
            int(generation_defaults.get("generation_plan_max_tokens", 600)),
        ),
        generation_compose_max_tokens=source.get_int(
            "GENERATION_COMPOSE_MAX_TOKENS",
            int(generation_defaults.get("generation_compose_max_tokens", 1100)),
        ),
        generation_direct_max_tokens=source.get_int(
            "GENERATION_DIRECT_MAX_TOKENS",
            int(generation_defaults.get("generation_direct_max_tokens", 700)),
        ),
        generation_plan_temperature=source.get_float(
            "GENERATION_PLAN_TEMPERATURE",
            float(generation_defaults.get("generation_plan_temperature", 0.0)),
        ),
        generation_planner_mode=source.get_str(
            "GENERATION_PLANNER_MODE",
            str(generation_defaults.get("generation_planner_mode", "rule")),
        ),
        generation_max_retries=source.get_int(
            "GENERATION_MAX_RETRIES",
            int(generation_defaults.get("generation_max_retries", 1)),
        ),
        generation_request_retries=source.get_int(
            "GENERATION_REQUEST_RETRIES",
            int(generation_defaults.get("generation_request_retries", 1)),
        ),
        generation_stream_retries=source.get_int(
            "GENERATION_STREAM_RETRIES",
            int(generation_defaults.get("generation_stream_retries", 1)),
        ),
        generation_evidence_max_chars=source.get_int(
            "GENERATION_EVIDENCE_MAX_CHARS",
            int(generation_defaults.get("generation_evidence_max_chars", 700)),
        ),
        generation_enable_two_stage=source.get_bool(
            "GENERATION_ENABLE_TWO_STAGE",
            bool(generation_defaults.get("generation_enable_two_stage", True)),
        ),
        generation_two_stage_complexity_threshold=source.get_float(
            "GENERATION_TWO_STAGE_COMPLEXITY_THRESHOLD",
            float(generation_defaults.get("generation_two_stage_complexity_threshold", 0.68)),
        ),
        generation_two_stage_relationship_threshold=source.get_float(
            "GENERATION_TWO_STAGE_RELATIONSHIP_THRESHOLD",
            float(generation_defaults.get("generation_two_stage_relationship_threshold", 0.58)),
        ),
        generation_direct_max_evidence_items=source.get_int(
            "GENERATION_DIRECT_MAX_EVIDENCE_ITEMS",
            int(generation_defaults.get("generation_direct_max_evidence_items", 2)),
        ),
        generation_two_stage_max_evidence_items=source.get_int(
            "GENERATION_TWO_STAGE_MAX_EVIDENCE_ITEMS",
            int(generation_defaults.get("generation_two_stage_max_evidence_items", 3)),
        ),
        generation_plan_max_evidence_items=source.get_int(
            "GENERATION_PLAN_MAX_EVIDENCE_ITEMS",
            int(generation_defaults.get("generation_plan_max_evidence_items", 2)),
        ),
        generation_max_graph_paths_per_item=source.get_int(
            "GENERATION_MAX_GRAPH_PATHS_PER_ITEM",
            int(generation_defaults.get("generation_max_graph_paths_per_item", 1)),
        ),
        generation_max_evidence_units_per_item=source.get_int(
            "GENERATION_MAX_EVIDENCE_UNITS_PER_ITEM",
            int(generation_defaults.get("generation_max_evidence_units_per_item", 4)),
        ),
        generation_include_document_evidence=source.get_bool(
            "GENERATION_INCLUDE_DOCUMENT_EVIDENCE",
            bool(generation_defaults.get("generation_include_document_evidence", False)),
        ),
        generation_compose_include_content=source.get_bool(
            "GENERATION_COMPOSE_INCLUDE_CONTENT",
            bool(generation_defaults.get("generation_compose_include_content", False)),
        ),
        generation_fallback_on_timeout=source.get_bool(
            "GENERATION_FALLBACK_ON_TIMEOUT",
            bool(generation_defaults.get("generation_fallback_on_timeout", False)),
        ),
    )


__all__ = ["load_generation_settings"]
