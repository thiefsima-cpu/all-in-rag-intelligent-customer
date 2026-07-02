"""Typed query policy bundle models."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass


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

    def to_dict(self) -> dict[str, str]:
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
    term_sets: dict[str, tuple[str, ...]]
    regex_rules: dict[str, tuple[str, ...]]

    def term_group(self, name: str) -> tuple[str, ...]:
        return tuple(self.term_sets.get(str(name), ()))

    def regex_group(self, name: str) -> tuple[str, ...]:
        return tuple(self.regex_rules.get(str(name), ()))


@dataclass(frozen=True)
class RelationPolicy:
    graph_routing_strategies: tuple[str, ...]
    graph_query_types: tuple[str, ...]
    graph_relation_types: tuple[str, ...]
    preferred_relation_excluded_types: tuple[str, ...]
    semantic_relation_hints: dict[str, str]
    relation_index_keywords: dict[str, tuple[str, ...]]
    relation_index_suffix_templates: dict[str, str]
    relation_query_markers: dict[str, tuple[str, ...]]
    entity_linker_preferred_labels: tuple[str, ...]
    entity_linker_query_type_priorities: dict[str, tuple[str, ...]]
    entity_linker_relation_priorities: dict[str, tuple[str, ...]]


@dataclass(frozen=True)
class ScoringPolicy:
    structural_relationship_factor: float
    length_norm_chars: int
    weights: dict[str, float]
    boosts: dict[str, float]


@dataclass(frozen=True)
class RoutingPolicy:
    graph_first_query_types: tuple[str, ...]
    multi_hop_graph_first_relation_hits: int
    meaningful_constraint_fields: tuple[str, ...]
    validation_labels: dict[str, str]


@dataclass(frozen=True)
class SemanticRelationKeySpec:
    target_field: str
    key_fields: tuple[str, ...]


@dataclass(frozen=True)
class GraphReasoningPolicy:
    causal_relation_types: tuple[str, ...]
    compositional_relation_types: tuple[str, ...]
    comparison_markers: tuple[str, ...]
    semantic_relation_key_specs: dict[str, SemanticRelationKeySpec]


@dataclass(frozen=True)
class GraphSubQuestionCondition:
    fallback: bool = False
    entities_present: bool | None = None
    relation_types_any: tuple[str, ...] = ()
    constraints_present: tuple[str, ...] = ()
    constraints_present_any: bool = False
    relationship_intensity_at_least: float | None = None
    query_markers_any: tuple[str, ...] = ()


@dataclass(frozen=True)
class GraphSubQuestionPolicy:
    id: str
    template: str
    when: GraphSubQuestionCondition

    def render(
        self,
        *,
        query: str,
        entities: Sequence[str],
        relation_types: Sequence[str],
    ) -> str:
        return self.template.format(
            query=query,
            entities=", ".join(list(entities)[:4]),
            relation_types=", ".join(relation_types),
        )


@dataclass(frozen=True)
class GraphPolicy:
    max_depth: dict[str, int]
    max_nodes: dict[str, int]
    sub_questions: tuple[GraphSubQuestionPolicy, ...]
    reasoning: GraphReasoningPolicy


@dataclass(frozen=True)
class GenerationAnswerTypePolicy:
    markers: tuple[str, ...] = ()


@dataclass(frozen=True)
class GenerationRulePlanPolicy:
    default_outline: tuple[str, ...]
    fallback_outline: tuple[str, ...]
    graph_caution: str
    missing_relation_evidence: str
    sparse_evidence: str
    missing_information_caution: str
    fallback_claim_template: str


@dataclass(frozen=True)
class GenerationDecisionReasonsPolicy:
    two_stage_disabled: str
    no_route_analysis: str
    graph_without_analysis: str
    graph_rag: str
    combined_pressure: str
    high_pressure: str
    simple: str


@dataclass(frozen=True)
class GenerationDecisionPolicy:
    default_answer_type: str
    high_pressure_margin: float
    reasons: GenerationDecisionReasonsPolicy


@dataclass(frozen=True)
class GenerationPolicy:
    answer_types: dict[str, GenerationAnswerTypePolicy]
    relation_explanation_markers: tuple[str, ...]
    rule_plan: GenerationRulePlanPolicy
    decision: GenerationDecisionPolicy
    fallback_answer: dict[str, str]


@dataclass(frozen=True)
class PlannerRuntimeDefaultsPolicy:
    model_name: str = "qwen3.7-plus"
    cache_size: int = 128
    timeout_seconds: int = 20
    fast_rule_planning: bool = True
    llm_temperature: float = 0.0
    llm_max_tokens: int = 1200


@dataclass(frozen=True)
class QuerySemanticRuntimeDefaultsPolicy:
    relation_intensity_reference_ratio: float = 0.5
    complexity_relation_hit_weight: float = 0.14
    complexity_constraint_hit_weight: float = 0.1
    complexity_structural_hit_weight: float = 0.12
    complexity_length_weight: float = 0.28
    complexity_length_norm_chars: int = 140
    reasoning_complexity_threshold: float = 0.7
    reasoning_relationship_threshold: float = 0.4
    high_relationship_routing_threshold: float = 0.7
    relation_hit_intensity_boost_base: float = 0.45
    relation_hit_intensity_boost_step: float = 0.12
    relation_hit_complexity_boost_base: float = 0.55
    relation_hit_complexity_boost_step: float = 0.08
    source_entity_limit: int = 3
    entity_keyword_limit: int = 4
    semantic_profile_entity_keyword_limit: int = 6
    topic_keyword_limit: int = 4
    semantic_profile_topic_keyword_start: int = 4
    semantic_profile_topic_keyword_limit: int = 6
    target_entity_limit: int = 2
    multi_hop_hint_entity_count: int = 2
    multi_hop_hint_relationship_threshold: float = 0.55
    combined_strategy_relationship_threshold: float = 0.4
    combined_strategy_complexity_threshold: float = 0.6
    source_entity_seed_relationship_threshold: float = 0.4
    source_entity_backfill_relationship_threshold: float = 0.55
    rule_fallback_confidence: float = 0.45
    entity_relation_max_depth: int = 1
    path_finding_max_depth: int = 3
    path_finding_high_intensity_max_depth: int = 4
    path_finding_high_intensity_threshold: float = 0.6
    subgraph_max_depth: int = 2
    subgraph_high_intensity_max_depth: int = 3
    subgraph_high_intensity_threshold: float = 0.5
    clustering_max_depth: int = 3
    default_max_depth: int = 2
    default_high_intensity_max_depth: int = 3
    default_high_intensity_threshold: float = 0.7
    entity_relation_max_nodes: int = 20
    path_finding_max_nodes: int = 40
    subgraph_max_nodes: int = 80
    clustering_max_nodes: int = 60
    default_max_nodes: int = 50
    graph_query_max_depth_cap: int = 4
    graph_query_fallback_name_chars: int = 16
    adaptive_multi_hop_subgraph_threshold: float = 0.7
    adaptive_subgraph_multi_hop_threshold: float = 0.45
    adaptive_entity_relation_multi_hop_threshold: float = 0.5
    adaptive_subgraph_max_depth: int = 3
    adaptive_subgraph_max_nodes: int = 100
    adaptive_multi_hop_max_depth: int = 3
    adaptive_multi_hop_max_nodes: int = 50
    adaptive_entity_relation_max_depth: int = 2
    adaptive_entity_relation_max_nodes: int = 40


@dataclass(frozen=True)
class CandidateRuntimeDefaultsPolicy:
    hybrid_default_multiplier: int = 2
    hybrid_default_min_candidates: int = 10
    hybrid_constraint_multiplier: int = 6
    hybrid_constraint_min_candidates: int = 30
    combined_multiplier: int = 6
    combined_min_candidates: int = 30
    graph_supplement_multiplier: int = 2
    graph_supplement_min_candidates: int = 10


@dataclass(frozen=True)
class CandidateSourceRuntimeDefaultsPolicy:
    failure_threshold: int = 1
    recovery_timeout_seconds: float = 30.0
    degradation_strategy: str = "continue"


@dataclass(frozen=True)
class PostProcessRuntimeDefaultsPolicy:
    enable_rerank: bool = True
    rerank_model: str = "qwen3-vl-rerank"
    rerank_base_url: str = ""
    rerank_timeout_seconds: int = 20
    preserve_graph_evidence: bool = True
    graph_preservation_strategies: tuple[str, ...] = ("graph_rag", "combined")


@dataclass(frozen=True)
class RuntimeDefaultsPolicy:
    planner: PlannerRuntimeDefaultsPolicy
    semantics: QuerySemanticRuntimeDefaultsPolicy
    candidates: CandidateRuntimeDefaultsPolicy
    candidate_sources: CandidateSourceRuntimeDefaultsPolicy
    postprocess: PostProcessRuntimeDefaultsPolicy


@dataclass(frozen=True)
class QueryPolicyBundle:
    metadata: PolicyMetadata
    lexicon: LexiconPolicy
    relations: RelationPolicy
    scoring: ScoringPolicy
    routing: RoutingPolicy
    graph: GraphPolicy
    generation: GenerationPolicy
    runtime_defaults: RuntimeDefaultsPolicy
    prompts: PromptTemplates

    def term_group(self, name: str) -> tuple[str, ...]:
        return self.lexicon.term_group(name)

    def regex_group(self, name: str) -> tuple[str, ...]:
        return self.lexicon.regex_group(name)

    @property
    def graph_routing_strategies(self) -> tuple[str, ...]:
        return self.relations.graph_routing_strategies

    @property
    def graph_query_types(self) -> tuple[str, ...]:
        return self.relations.graph_query_types

    @property
    def graph_relation_types(self) -> tuple[str, ...]:
        return self.relations.graph_relation_types

    @property
    def semantic_relation_hints(self) -> dict[str, str]:
        return dict(self.relations.semantic_relation_hints)

    @property
    def relation_index_keywords(self) -> dict[str, tuple[str, ...]]:
        return dict(self.relations.relation_index_keywords)

    @property
    def relation_index_suffix_templates(self) -> dict[str, str]:
        return dict(self.relations.relation_index_suffix_templates)

    @property
    def relation_query_markers(self) -> dict[str, tuple[str, ...]]:
        return dict(self.relations.relation_query_markers)

    @property
    def entity_linker_preferred_labels(self) -> tuple[str, ...]:
        return self.relations.entity_linker_preferred_labels

    @property
    def entity_linker_query_type_priorities(self) -> dict[str, tuple[str, ...]]:
        return dict(self.relations.entity_linker_query_type_priorities)

    @property
    def entity_linker_relation_priorities(self) -> dict[str, tuple[str, ...]]:
        return dict(self.relations.entity_linker_relation_priorities)
