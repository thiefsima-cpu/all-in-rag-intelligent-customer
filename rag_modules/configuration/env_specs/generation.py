"""Generation environment override specs."""

from __future__ import annotations

from .base import EnvFieldSpec
from .base import spec as _spec

GENERATION_ENV_FIELD_SPECS: tuple[EnvFieldSpec, ...] = (
    _spec("TEMPERATURE", ("generation", "temperature"), "float"),
    _spec("MAX_TOKENS", ("generation", "max_tokens"), "int"),
    _spec("GENERATION_TIMEOUT_SECONDS", ("generation", "generation_timeout_seconds"), "int"),
    _spec(
        "GENERATION_STREAM_TIMEOUT_SECONDS",
        ("generation", "generation_stream_timeout_seconds"),
        "int",
    ),
    _spec(
        "GENERATION_LATENCY_BUDGET_SECONDS",
        ("generation", "generation_latency_budget_seconds"),
        "int",
    ),
    _spec("GENERATION_PLAN_MAX_TOKENS", ("generation", "generation_plan_max_tokens"), "int"),
    _spec(
        "GENERATION_COMPOSE_MAX_TOKENS",
        ("generation", "generation_compose_max_tokens"),
        "int",
    ),
    _spec("GENERATION_DIRECT_MAX_TOKENS", ("generation", "generation_direct_max_tokens"), "int"),
    _spec(
        "GENERATION_PLAN_TEMPERATURE",
        ("generation", "generation_plan_temperature"),
        "float",
    ),
    _spec("GENERATION_PLANNER_MODE", ("generation", "generation_planner_mode"), "str"),
    _spec("GENERATION_MAX_RETRIES", ("generation", "generation_max_retries"), "int"),
    _spec("GENERATION_REQUEST_RETRIES", ("generation", "generation_request_retries"), "int"),
    _spec("GENERATION_STREAM_RETRIES", ("generation", "generation_stream_retries"), "int"),
    _spec("GENERATION_EVIDENCE_MAX_CHARS", ("generation", "generation_evidence_max_chars"), "int"),
    _spec(
        "GENERATION_ENABLE_TWO_STAGE",
        ("generation", "generation_enable_two_stage"),
        "bool",
    ),
    _spec(
        "GENERATION_TWO_STAGE_COMPLEXITY_THRESHOLD",
        ("generation", "generation_two_stage_complexity_threshold"),
        "float",
    ),
    _spec(
        "GENERATION_TWO_STAGE_RELATIONSHIP_THRESHOLD",
        ("generation", "generation_two_stage_relationship_threshold"),
        "float",
    ),
    _spec(
        "GENERATION_DIRECT_MAX_EVIDENCE_ITEMS",
        ("generation", "generation_direct_max_evidence_items"),
        "int",
    ),
    _spec(
        "GENERATION_TWO_STAGE_MAX_EVIDENCE_ITEMS",
        ("generation", "generation_two_stage_max_evidence_items"),
        "int",
    ),
    _spec(
        "GENERATION_PLAN_MAX_EVIDENCE_ITEMS",
        ("generation", "generation_plan_max_evidence_items"),
        "int",
    ),
    _spec(
        "GENERATION_MAX_GRAPH_PATHS_PER_ITEM",
        ("generation", "generation_max_graph_paths_per_item"),
        "int",
    ),
    _spec(
        "GENERATION_MAX_EVIDENCE_UNITS_PER_ITEM",
        ("generation", "generation_max_evidence_units_per_item"),
        "int",
    ),
    _spec(
        "GENERATION_INCLUDE_DOCUMENT_EVIDENCE",
        ("generation", "generation_include_document_evidence"),
        "bool",
    ),
    _spec(
        "GENERATION_COMPOSE_INCLUDE_CONTENT",
        ("generation", "generation_compose_include_content"),
        "bool",
    ),
    _spec(
        "GENERATION_FALLBACK_ON_TIMEOUT",
        ("generation", "generation_fallback_on_timeout"),
        "bool",
    ),
)


__all__ = ["GENERATION_ENV_FIELD_SPECS"]
