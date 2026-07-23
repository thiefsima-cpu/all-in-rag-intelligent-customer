"""Query planner and semantic runtime settings shared across subsystems."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass
from typing import TypeAlias

from pydantic import BaseModel

from ..kernel.json_types import JsonObject, coerce_json_object


@dataclass
class QueryPlannerRuntimeSettings:
    model_name: str
    cache_size: int
    timeout_seconds: int
    fast_rule_planning: bool
    llm_temperature: float
    llm_max_tokens: int

    def __post_init__(self) -> None:
        self._normalize_unit_values()

    def _normalize_unit_values(self) -> None:
        self.model_name = str(self.model_name)
        self.cache_size = max(0, int(self.cache_size))
        self.timeout_seconds = max(1, int(self.timeout_seconds))
        self.fast_rule_planning = bool(self.fast_rule_planning)
        self.llm_temperature = max(0.0, min(2.0, float(self.llm_temperature)))
        self.llm_max_tokens = max(128, int(self.llm_max_tokens))

    @classmethod
    def from_config(cls, config: Mapping[str, object] | BaseModel) -> "QueryPlannerRuntimeSettings":
        payload = _settings_payload(config)
        models = _section(payload, "models")
        planner = _section(_section(payload, "query_understanding"), "planner")
        return cls(
            model_name=_text(models.get("llm_model")),
            cache_size=_integer(planner.get("cache_size")),
            timeout_seconds=_integer(models.get("llm_timeout_seconds")),
            fast_rule_planning=_boolean(planner.get("fast_rule_planning")),
            llm_temperature=_number(planner.get("llm_temperature")),
            llm_max_tokens=_integer(planner.get("llm_max_tokens")),
        )

    def to_dict(self) -> JsonObject:
        return {
            "model_name": self.model_name,
            "cache_size": self.cache_size,
            "timeout_seconds": self.timeout_seconds,
            "fast_rule_planning": self.fast_rule_planning,
            "llm_temperature": self.llm_temperature,
            "llm_max_tokens": self.llm_max_tokens,
        }


@dataclass
class QuerySemanticRuntimeSettings:
    relation_intensity_reference_ratio: float
    complexity_relation_hit_weight: float
    complexity_constraint_hit_weight: float
    complexity_structural_hit_weight: float
    complexity_length_weight: float
    complexity_length_norm_chars: int
    reasoning_complexity_threshold: float
    reasoning_relationship_threshold: float
    high_relationship_routing_threshold: float
    relation_hit_intensity_boost_base: float
    relation_hit_intensity_boost_step: float
    relation_hit_complexity_boost_base: float
    relation_hit_complexity_boost_step: float
    source_entity_limit: int
    entity_keyword_limit: int
    semantic_profile_entity_keyword_limit: int
    topic_keyword_limit: int
    semantic_profile_topic_keyword_start: int
    semantic_profile_topic_keyword_limit: int
    target_entity_limit: int
    multi_hop_hint_entity_count: int
    multi_hop_hint_relationship_threshold: float
    combined_strategy_relationship_threshold: float
    combined_strategy_complexity_threshold: float
    source_entity_seed_relationship_threshold: float
    source_entity_backfill_relationship_threshold: float
    rule_fallback_confidence: float
    entity_relation_max_depth: int
    path_finding_max_depth: int
    path_finding_high_intensity_max_depth: int
    path_finding_high_intensity_threshold: float
    subgraph_max_depth: int
    subgraph_high_intensity_max_depth: int
    subgraph_high_intensity_threshold: float
    clustering_max_depth: int
    default_max_depth: int
    default_high_intensity_max_depth: int
    default_high_intensity_threshold: float
    entity_relation_max_nodes: int
    path_finding_max_nodes: int
    subgraph_max_nodes: int
    clustering_max_nodes: int
    default_max_nodes: int
    graph_query_max_depth_cap: int
    graph_query_fallback_name_chars: int
    adaptive_multi_hop_subgraph_threshold: float
    adaptive_subgraph_multi_hop_threshold: float
    adaptive_entity_relation_multi_hop_threshold: float
    adaptive_subgraph_max_depth: int
    adaptive_subgraph_max_nodes: int
    adaptive_multi_hop_max_depth: int
    adaptive_multi_hop_max_nodes: int
    adaptive_entity_relation_max_depth: int
    adaptive_entity_relation_max_nodes: int

    def __post_init__(self) -> None:
        self.relation_intensity_reference_ratio = _unit(self.relation_intensity_reference_ratio)
        self.reasoning_complexity_threshold = _unit(self.reasoning_complexity_threshold)
        self.reasoning_relationship_threshold = _unit(self.reasoning_relationship_threshold)
        self.high_relationship_routing_threshold = _unit(self.high_relationship_routing_threshold)
        self.relation_hit_intensity_boost_base = _unit(self.relation_hit_intensity_boost_base)
        self.relation_hit_complexity_boost_base = _unit(self.relation_hit_complexity_boost_base)
        self.multi_hop_hint_relationship_threshold = _unit(
            self.multi_hop_hint_relationship_threshold
        )
        self.combined_strategy_relationship_threshold = _unit(
            self.combined_strategy_relationship_threshold
        )
        self.combined_strategy_complexity_threshold = _unit(
            self.combined_strategy_complexity_threshold
        )
        self.source_entity_seed_relationship_threshold = _unit(
            self.source_entity_seed_relationship_threshold
        )
        self.source_entity_backfill_relationship_threshold = _unit(
            self.source_entity_backfill_relationship_threshold
        )
        self.rule_fallback_confidence = _unit(self.rule_fallback_confidence)
        self.path_finding_high_intensity_threshold = _unit(
            self.path_finding_high_intensity_threshold
        )
        self.subgraph_high_intensity_threshold = _unit(self.subgraph_high_intensity_threshold)
        self.default_high_intensity_threshold = _unit(self.default_high_intensity_threshold)
        self.adaptive_multi_hop_subgraph_threshold = _unit(
            self.adaptive_multi_hop_subgraph_threshold
        )
        self.adaptive_subgraph_multi_hop_threshold = _unit(
            self.adaptive_subgraph_multi_hop_threshold
        )
        self.adaptive_entity_relation_multi_hop_threshold = _unit(
            self.adaptive_entity_relation_multi_hop_threshold
        )

        self._normalize_weight_values()
        self._normalize_minimum_values()

    def _normalize_weight_values(self) -> None:
        self.complexity_relation_hit_weight = _weight(self.complexity_relation_hit_weight)
        self.complexity_constraint_hit_weight = _weight(self.complexity_constraint_hit_weight)
        self.complexity_structural_hit_weight = _weight(self.complexity_structural_hit_weight)
        self.complexity_length_weight = _weight(self.complexity_length_weight)
        self.relation_hit_intensity_boost_step = _weight(self.relation_hit_intensity_boost_step)
        self.relation_hit_complexity_boost_step = _weight(self.relation_hit_complexity_boost_step)

    def _normalize_minimum_values(self) -> None:
        self.complexity_length_norm_chars = _minimum(self.complexity_length_norm_chars, 1)
        self.source_entity_limit = _minimum(self.source_entity_limit, 1)
        self.entity_keyword_limit = _minimum(self.entity_keyword_limit, 1)
        self.semantic_profile_entity_keyword_limit = _minimum(
            self.semantic_profile_entity_keyword_limit, 1
        )
        self.topic_keyword_limit = _minimum(self.topic_keyword_limit, 1)
        self.semantic_profile_topic_keyword_start = _minimum(
            self.semantic_profile_topic_keyword_start, 0
        )
        self.semantic_profile_topic_keyword_limit = _minimum(
            self.semantic_profile_topic_keyword_limit, 1
        )
        self.target_entity_limit = _minimum(self.target_entity_limit, 1)
        self.multi_hop_hint_entity_count = _minimum(self.multi_hop_hint_entity_count, 1)
        self.entity_relation_max_depth = _minimum(self.entity_relation_max_depth, 1)
        self.path_finding_max_depth = _minimum(self.path_finding_max_depth, 1)
        self.path_finding_high_intensity_max_depth = _minimum(
            self.path_finding_high_intensity_max_depth, 1
        )
        self.subgraph_max_depth = _minimum(self.subgraph_max_depth, 1)
        self.subgraph_high_intensity_max_depth = _minimum(self.subgraph_high_intensity_max_depth, 1)
        self.clustering_max_depth = _minimum(self.clustering_max_depth, 1)
        self.default_max_depth = _minimum(self.default_max_depth, 1)
        self.default_high_intensity_max_depth = _minimum(self.default_high_intensity_max_depth, 1)
        self.entity_relation_max_nodes = _minimum(self.entity_relation_max_nodes, 1)
        self.path_finding_max_nodes = _minimum(self.path_finding_max_nodes, 1)
        self.subgraph_max_nodes = _minimum(self.subgraph_max_nodes, 1)
        self.clustering_max_nodes = _minimum(self.clustering_max_nodes, 1)
        self.default_max_nodes = _minimum(self.default_max_nodes, 1)
        self.graph_query_max_depth_cap = _minimum(self.graph_query_max_depth_cap, 1)
        self.graph_query_fallback_name_chars = _minimum(self.graph_query_fallback_name_chars, 1)
        self.adaptive_subgraph_max_depth = _minimum(self.adaptive_subgraph_max_depth, 1)
        self.adaptive_subgraph_max_nodes = _minimum(self.adaptive_subgraph_max_nodes, 1)
        self.adaptive_multi_hop_max_depth = _minimum(self.adaptive_multi_hop_max_depth, 1)
        self.adaptive_multi_hop_max_nodes = _minimum(self.adaptive_multi_hop_max_nodes, 1)
        self.adaptive_entity_relation_max_depth = _minimum(
            self.adaptive_entity_relation_max_depth, 1
        )
        self.adaptive_entity_relation_max_nodes = _minimum(
            self.adaptive_entity_relation_max_nodes, 1
        )

    @classmethod
    def from_config(
        cls, config: Mapping[str, object] | BaseModel
    ) -> "QuerySemanticRuntimeSettings":
        scoring, extraction, routing, traversal, adaptive = _semantic_config_sections(config)
        return QuerySemanticRuntimeSettings(
            *_semantic_runtime_values(scoring, extraction, routing, traversal, adaptive)
        )

    def to_dict(self) -> JsonObject:
        return coerce_json_object(asdict(self))


def _unit(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def _weight(value: float) -> float:
    return max(0.0, min(5.0, float(value)))


def _minimum(value: int, minimum: int) -> int:
    return max(minimum, int(value))


def _settings_payload(config: Mapping[str, object] | BaseModel) -> JsonObject:
    if isinstance(config, BaseModel):
        return coerce_json_object(config.model_dump(mode="python"))
    return coerce_json_object(config)


def _section(payload: Mapping[str, object], key: str) -> Mapping[str, object]:
    value = payload.get(key)
    return value if isinstance(value, Mapping) else {}


def _semantic_config_sections(
    config: Mapping[str, object] | BaseModel,
) -> tuple[
    Mapping[str, object],
    Mapping[str, object],
    Mapping[str, object],
    Mapping[str, object],
    Mapping[str, object],
]:
    payload = _settings_payload(config)
    semantics = _section(_section(payload, "query_understanding"), "semantics")
    return (
        _section(semantics, "scoring"),
        _section(semantics, "extraction"),
        _section(semantics, "routing"),
        _section(semantics, "traversal"),
        _section(semantics, "adaptive_traversal"),
    )


SemanticRuntimeSettingsArgs: TypeAlias = tuple[
    float,
    float,
    float,
    float,
    float,
    int,
    float,
    float,
    float,
    float,
    float,
    float,
    float,
    int,
    int,
    int,
    int,
    int,
    int,
    int,
    int,
    float,
    float,
    float,
    float,
    float,
    float,
    int,
    int,
    int,
    float,
    int,
    int,
    float,
    int,
    int,
    int,
    float,
    int,
    int,
    int,
    int,
    int,
    int,
    int,
    float,
    float,
    float,
    int,
    int,
    int,
    int,
    int,
    int,
]


def _semantic_runtime_values(
    scoring: Mapping[str, object],
    extraction: Mapping[str, object],
    routing: Mapping[str, object],
    traversal: Mapping[str, object],
    adaptive: Mapping[str, object],
) -> SemanticRuntimeSettingsArgs:
    return (
        *_scoring_and_extraction_values(scoring, extraction, routing),
        *_routing_values(routing),
        *_traversal_values(traversal),
        *_adaptive_traversal_values(adaptive),
    )


def _scoring_and_extraction_values(
    scoring: Mapping[str, object],
    extraction: Mapping[str, object],
    routing: Mapping[str, object],
) -> tuple[
    float,
    float,
    float,
    float,
    float,
    int,
    float,
    float,
    float,
    float,
    float,
    float,
    float,
    int,
    int,
    int,
    int,
    int,
    int,
    int,
]:
    return (
        _number(scoring.get("relation_intensity_reference_ratio")),
        _number(scoring.get("complexity_relation_hit_weight")),
        _number(scoring.get("complexity_constraint_hit_weight")),
        _number(scoring.get("complexity_structural_hit_weight")),
        _number(scoring.get("complexity_length_weight")),
        _integer(scoring.get("complexity_length_norm_chars")),
        _number(scoring.get("reasoning_complexity_threshold")),
        _number(scoring.get("reasoning_relationship_threshold")),
        _number(routing.get("high_relationship_routing_threshold")),
        _number(scoring.get("relation_hit_intensity_boost_base")),
        _number(scoring.get("relation_hit_intensity_boost_step")),
        _number(scoring.get("relation_hit_complexity_boost_base")),
        _number(scoring.get("relation_hit_complexity_boost_step")),
        _integer(extraction.get("source_entity_limit")),
        _integer(extraction.get("entity_keyword_limit")),
        _integer(extraction.get("semantic_profile_entity_keyword_limit")),
        _integer(extraction.get("topic_keyword_limit")),
        _integer(extraction.get("semantic_profile_topic_keyword_start")),
        _integer(extraction.get("semantic_profile_topic_keyword_limit")),
        _integer(extraction.get("target_entity_limit")),
    )


def _routing_values(
    routing: Mapping[str, object],
) -> tuple[int, float, float, float, float, float, float]:
    return (
        _integer(routing.get("multi_hop_hint_entity_count")),
        _number(routing.get("multi_hop_hint_relationship_threshold")),
        _number(routing.get("combined_strategy_relationship_threshold")),
        _number(routing.get("combined_strategy_complexity_threshold")),
        _number(routing.get("source_entity_seed_relationship_threshold")),
        _number(routing.get("source_entity_backfill_relationship_threshold")),
        _number(routing.get("rule_fallback_confidence")),
    )


def _traversal_values(
    traversal: Mapping[str, object],
) -> tuple[
    int, int, int, float, int, int, float, int, int, int, float, int, int, int, int, int, int, int
]:
    return (
        _integer(traversal.get("entity_relation_max_depth")),
        _integer(traversal.get("path_finding_max_depth")),
        _integer(traversal.get("path_finding_high_intensity_max_depth")),
        _number(traversal.get("path_finding_high_intensity_threshold")),
        _integer(traversal.get("subgraph_max_depth")),
        _integer(traversal.get("subgraph_high_intensity_max_depth")),
        _number(traversal.get("subgraph_high_intensity_threshold")),
        _integer(traversal.get("clustering_max_depth")),
        _integer(traversal.get("default_max_depth")),
        _integer(traversal.get("default_high_intensity_max_depth")),
        _number(traversal.get("default_high_intensity_threshold")),
        _integer(traversal.get("entity_relation_max_nodes")),
        _integer(traversal.get("path_finding_max_nodes")),
        _integer(traversal.get("subgraph_max_nodes")),
        _integer(traversal.get("clustering_max_nodes")),
        _integer(traversal.get("default_max_nodes")),
        _integer(traversal.get("graph_query_max_depth_cap")),
        _integer(traversal.get("graph_query_fallback_name_chars")),
    )


def _adaptive_traversal_values(
    adaptive: Mapping[str, object],
) -> tuple[float, float, float, int, int, int, int, int, int]:
    return (
        _number(adaptive.get("multi_hop_subgraph_threshold")),
        _number(adaptive.get("subgraph_multi_hop_threshold")),
        _number(adaptive.get("entity_relation_multi_hop_threshold")),
        _integer(adaptive.get("subgraph_max_depth")),
        _integer(adaptive.get("subgraph_max_nodes")),
        _integer(adaptive.get("multi_hop_max_depth")),
        _integer(adaptive.get("multi_hop_max_nodes")),
        _integer(adaptive.get("entity_relation_max_depth")),
        _integer(adaptive.get("entity_relation_max_nodes")),
    )


def _text(value: object) -> str:
    return str(value or "")


def _number(value: object) -> float:
    if isinstance(value, (bool, int, float, str)):
        try:
            return float(value)
        except (TypeError, ValueError):
            return 0.0
    return 0.0


def _integer(value: object) -> int:
    if isinstance(value, (bool, int, float, str)):
        try:
            return int(value)
        except (TypeError, ValueError):
            return 0
    return 0


def _boolean(value: object) -> bool:
    return bool(value)


__all__ = ["QueryPlannerRuntimeSettings", "QuerySemanticRuntimeSettings"]
