"""Typed query policy bundle models."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Tuple


class PolicyLoadError(RuntimeError):
    """Raised when a query policy bundle cannot be loaded or validated."""

    def __init__(
        self,
        message: str,
        *,
        bundle_path: str | None = None,
        field_path: str | None = None,
    ) -> None:
        details = []
        if bundle_path:
            details.append(f"bundle_path={bundle_path}")
        if field_path:
            details.append(f"field_path={field_path}")
        suffix = f" ({', '.join(details)})" if details else ""
        super().__init__(f"{message}{suffix}")
        self.bundle_path = bundle_path
        self.field_path = field_path


@dataclass(frozen=True)
class PolicyMetadata:
    schema_version: str
    policy_version: str
    prompt_version: str
    policy_hash: str
    prompt_hash: str
    bundle_name: str

    def to_dict(self) -> Dict[str, str]:
        return {
            "schema_version": self.schema_version,
            "policy_version": self.policy_version,
            "prompt_version": self.prompt_version,
            "policy_hash": self.policy_hash,
            "prompt_hash": self.prompt_hash,
            "bundle_name": self.bundle_name,
        }


@dataclass(frozen=True)
class PromptTemplates:
    query_planner: str
    answer_plan: str
    answer_compose: str
    answer_direct: str


@dataclass(frozen=True)
class LexiconPolicy:
    term_sets: Dict[str, Tuple[str, ...]]
    regex_rules: Dict[str, Tuple[str, ...]]

    def term_group(self, name: str) -> Tuple[str, ...]:
        return tuple(self.term_sets.get(str(name), ()))

    def regex_group(self, name: str) -> Tuple[str, ...]:
        return tuple(self.regex_rules.get(str(name), ()))


@dataclass(frozen=True)
class RelationPolicy:
    graph_routing_strategies: Tuple[str, ...]
    graph_query_types: Tuple[str, ...]
    graph_relation_types: Tuple[str, ...]
    preferred_relation_excluded_types: Tuple[str, ...]
    semantic_relation_hints: Dict[str, str]
    relation_index_keywords: Dict[str, Tuple[str, ...]]
    relation_index_suffix_templates: Dict[str, str]
    relation_query_markers: Dict[str, Tuple[str, ...]]
    entity_linker_preferred_labels: Tuple[str, ...]
    entity_linker_query_type_priorities: Dict[str, Tuple[str, ...]]
    entity_linker_relation_priorities: Dict[str, Tuple[str, ...]]


@dataclass(frozen=True)
class ScoringPolicy:
    structural_relationship_factor: float
    length_norm_chars: int
    weights: Dict[str, float]
    boosts: Dict[str, float]


@dataclass(frozen=True)
class RoutingPolicy:
    graph_first_query_types: Tuple[str, ...]
    multi_hop_graph_first_relation_hits: int
    meaningful_constraint_fields: Tuple[str, ...]
    validation_labels: Dict[str, str]


@dataclass(frozen=True)
class SemanticRelationKeySpec:
    target_field: str
    key_fields: Tuple[str, ...]


@dataclass(frozen=True)
class GraphReasoningPolicy:
    causal_relation_types: Tuple[str, ...]
    compositional_relation_types: Tuple[str, ...]
    comparison_markers: Tuple[str, ...]
    semantic_relation_key_specs: Dict[str, SemanticRelationKeySpec]


@dataclass(frozen=True)
class GraphPolicy:
    max_depth: Dict[str, int]
    max_nodes: Dict[str, int]
    sub_questions: Tuple[Dict[str, Any], ...]
    reasoning: GraphReasoningPolicy


@dataclass(frozen=True)
class GenerationPolicy:
    answer_types: Dict[str, Dict[str, Any]]
    relation_explanation_markers: Tuple[str, ...]
    rule_plan: Dict[str, Any]
    decision: Dict[str, Any]
    fallback_answer: Dict[str, str]


@dataclass(frozen=True)
class QueryPolicyBundle:
    metadata: PolicyMetadata
    lexicon: LexiconPolicy
    relations: RelationPolicy
    scoring: ScoringPolicy
    routing: RoutingPolicy
    graph: GraphPolicy
    generation: GenerationPolicy
    runtime_defaults: Dict[str, Dict[str, Any]]
    prompts: PromptTemplates

    def runtime_section(self, name: str) -> Dict[str, Any]:
        return dict(self.runtime_defaults.get(str(name), {}))

    def term_group(self, name: str) -> Tuple[str, ...]:
        return self.lexicon.term_group(name)

    def regex_group(self, name: str) -> Tuple[str, ...]:
        return self.lexicon.regex_group(name)

    @property
    def graph_routing_strategies(self) -> Tuple[str, ...]:
        return self.relations.graph_routing_strategies

    @property
    def graph_query_types(self) -> Tuple[str, ...]:
        return self.relations.graph_query_types

    @property
    def graph_relation_types(self) -> Tuple[str, ...]:
        return self.relations.graph_relation_types

    @property
    def semantic_relation_hints(self) -> Dict[str, str]:
        return dict(self.relations.semantic_relation_hints)

    @property
    def relation_index_keywords(self) -> Dict[str, Tuple[str, ...]]:
        return dict(self.relations.relation_index_keywords)

    @property
    def relation_index_suffix_templates(self) -> Dict[str, str]:
        return dict(self.relations.relation_index_suffix_templates)

    @property
    def relation_query_markers(self) -> Dict[str, Tuple[str, ...]]:
        return dict(self.relations.relation_query_markers)

    @property
    def entity_linker_preferred_labels(self) -> Tuple[str, ...]:
        return self.relations.entity_linker_preferred_labels

    @property
    def entity_linker_query_type_priorities(self) -> Dict[str, Tuple[str, ...]]:
        return dict(self.relations.entity_linker_query_type_priorities)

    @property
    def entity_linker_relation_priorities(self) -> Dict[str, Tuple[str, ...]]:
        return dict(self.relations.entity_linker_relation_priorities)
