"""Shared lexical registry and semantic profile models for query understanding."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Sequence, Tuple

from ..domain.shared.semantic_schema import SEMANTIC_RELATION_TYPES
from ..query_policy import flatten_term_groups, get_query_policy

POLICY = get_query_policy()

GRAPH_ROUTING_STRATEGIES: Tuple[str, ...] = POLICY.graph_routing_strategies
GRAPH_QUERY_TYPES: Tuple[str, ...] = POLICY.graph_query_types
GRAPH_RELATION_TYPES: Tuple[str, ...] = tuple(
    dict.fromkeys([*POLICY.graph_relation_types, *SEMANTIC_RELATION_TYPES])
)

FLAVOR_TERMS: Tuple[str, ...] = POLICY.term_group("flavor_terms")
TEXTURE_EFFECT_TERMS: Tuple[str, ...] = POLICY.term_group("texture_effect_terms")
TECHNIQUE_TERMS: Tuple[str, ...] = POLICY.term_group("technique_terms")
DIET_TERMS: Tuple[str, ...] = POLICY.term_group("diet_terms")
HEALTH_TERMS: Tuple[str, ...] = POLICY.term_group("health_terms")
CUISINE_STYLE_TERMS: Tuple[str, ...] = POLICY.term_group("cuisine_style_terms")
INGREDIENT_CATEGORY_TERMS: Tuple[str, ...] = POLICY.term_group("ingredient_category_terms")
DIFFICULTY_TERMS: Tuple[str, ...] = POLICY.term_group("difficulty_terms")
TIME_MARKERS: Tuple[str, ...] = POLICY.term_group("time_markers")
PATH_MARKERS: Tuple[str, ...] = POLICY.term_group("path_markers")
SUBGRAPH_MARKERS: Tuple[str, ...] = POLICY.term_group("subgraph_markers")
CLUSTERING_MARKERS: Tuple[str, ...] = POLICY.term_group("clustering_markers")
RECOMMENDATION_MARKERS: Tuple[str, ...] = POLICY.term_group("recommendation_markers")
EXPLICIT_RECOMMENDATION_MARKERS: Tuple[str, ...] = POLICY.term_group(
    "explicit_recommendation_markers"
)
AMBIGUOUS_RECOMMENDATION_MARKERS: Tuple[str, ...] = POLICY.term_group(
    "ambiguous_recommendation_markers"
)
FILTERING_MARKERS: Tuple[str, ...] = POLICY.term_group("filtering_markers")
STRUCTURAL_REASONING_MARKERS: Tuple[str, ...] = POLICY.term_group("structural_reasoning_markers")
RELATION_MARKERS: Tuple[str, ...] = POLICY.term_group("relation_markers")
FAST_RULE_MARKERS: Tuple[str, ...] = POLICY.term_group("fast_rule_markers")
CONSTRAINT_MARKERS: Tuple[str, ...] = POLICY.term_group("constraint_markers")
ENTITY_HINTS: Tuple[str, ...] = POLICY.term_group("entity_hints")
ENTITY_PHRASE_MARKERS: Tuple[str, ...] = POLICY.term_group("entity_phrase_markers")
ENTITY_TARGET_MARKERS: Tuple[str, ...] = POLICY.term_group("entity_target_markers")
GRAPH_GENERIC_TERMS: Tuple[str, ...] = POLICY.term_group("graph_generic_terms")
QUERY_STOPWORDS: Tuple[str, ...] = POLICY.term_group("query_stopwords")
GRAPH_SOURCE_PREFIXES: Tuple[str, ...] = POLICY.term_group("graph_source_prefixes")
GRAPH_SOURCE_SUFFIXES: Tuple[str, ...] = POLICY.term_group("graph_source_suffixes")
SEMANTIC_RELATION_HINTS: Dict[str, str] = dict(POLICY.semantic_relation_hints)
RELATION_INDEX_KEYWORDS: Dict[str, Tuple[str, ...]] = dict(POLICY.relation_index_keywords)
RELATION_QUERY_MARKERS: Dict[str, Tuple[str, ...]] = dict(POLICY.relation_query_markers)
DEFAULT_ENTITY_LINKER_PREFERRED_LABELS: Tuple[str, ...] = POLICY.entity_linker_preferred_labels

SEMANTIC_NODE_TERMS: Tuple[str, ...] = flatten_term_groups(
    "flavor_terms",
    "texture_effect_terms",
    "technique_terms",
    "diet_terms",
    "health_terms",
    "cuisine_style_terms",
    "ingredient_category_terms",
    "difficulty_terms",
)


@dataclass(frozen=True)
class QuerySemanticScoreBreakdown:
    relation_hit_count: int = 0
    constraint_hit_count: int = 0
    structural_hit_count: int = 0
    fast_rule_hit_count: int = 0
    length_factor: float = 0.0
    lexical_relationship_intensity: float = 0.0
    relation_hit_intensity_boost: float = 0.0
    lexical_complexity: float = 0.0
    relation_hit_complexity_boost: float = 0.0
    relationship_intensity: float = 0.0
    complexity: float = 0.0

    @classmethod
    def from_dict(cls, data: Dict[str, Any] | None) -> "QuerySemanticScoreBreakdown":
        payload = dict(data or {})
        return cls(
            relation_hit_count=int(payload.get("relation_hit_count", 0) or 0),
            constraint_hit_count=int(payload.get("constraint_hit_count", 0) or 0),
            structural_hit_count=int(payload.get("structural_hit_count", 0) or 0),
            fast_rule_hit_count=int(payload.get("fast_rule_hit_count", 0) or 0),
            length_factor=float(payload.get("length_factor", 0.0) or 0.0),
            lexical_relationship_intensity=float(
                payload.get("lexical_relationship_intensity", 0.0) or 0.0
            ),
            relation_hit_intensity_boost=float(
                payload.get("relation_hit_intensity_boost", 0.0) or 0.0
            ),
            lexical_complexity=float(payload.get("lexical_complexity", 0.0) or 0.0),
            relation_hit_complexity_boost=float(
                payload.get("relation_hit_complexity_boost", 0.0) or 0.0
            ),
            relationship_intensity=float(payload.get("relationship_intensity", 0.0) or 0.0),
            complexity=float(payload.get("complexity", 0.0) or 0.0),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "relation_hit_count": self.relation_hit_count,
            "constraint_hit_count": self.constraint_hit_count,
            "structural_hit_count": self.structural_hit_count,
            "fast_rule_hit_count": self.fast_rule_hit_count,
            "length_factor": self.length_factor,
            "lexical_relationship_intensity": self.lexical_relationship_intensity,
            "relation_hit_intensity_boost": self.relation_hit_intensity_boost,
            "lexical_complexity": self.lexical_complexity,
            "relation_hit_complexity_boost": self.relation_hit_complexity_boost,
            "relationship_intensity": self.relationship_intensity,
            "complexity": self.complexity,
        }


@dataclass(frozen=True)
class QuerySemanticProfile:
    query: str = ""
    query_type: str = "entity_relation"
    source_entities: List[str] = field(default_factory=list)
    target_entities: List[str] = field(default_factory=list)
    relation_types: List[str] = field(default_factory=list)
    entity_keywords: List[str] = field(default_factory=list)
    topic_keywords: List[str] = field(default_factory=list)
    constraints: Dict[str, Any] = field(default_factory=dict)
    complexity: float = 0.5
    relationship_intensity: float = 0.5
    reasoning_required: bool = False
    needs_recipe_recommendation: bool = False
    recommendation_hits: List[str] = field(default_factory=list)
    relation_hits: List[str] = field(default_factory=list)
    constraint_hits: List[str] = field(default_factory=list)
    structural_hits: List[str] = field(default_factory=list)
    fast_rule_hits: List[str] = field(default_factory=list)
    score_breakdown: QuerySemanticScoreBreakdown = field(
        default_factory=QuerySemanticScoreBreakdown
    )

    @classmethod
    def from_dict(cls, data: Dict[str, Any] | None) -> "QuerySemanticProfile":
        payload = dict(data or {})
        score_breakdown = payload.get("score_breakdown") or {}
        return cls(
            query=str(payload.get("query") or ""),
            query_type=str(payload.get("query_type") or "entity_relation"),
            source_entities=dedupe_preserve_order(payload.get("source_entities") or []),
            target_entities=dedupe_preserve_order(payload.get("target_entities") or []),
            relation_types=dedupe_preserve_order(payload.get("relation_types") or []),
            entity_keywords=dedupe_preserve_order(payload.get("entity_keywords") or []),
            topic_keywords=dedupe_preserve_order(payload.get("topic_keywords") or []),
            constraints=dict(payload.get("constraints") or {}),
            complexity=float(payload.get("complexity", 0.5) or 0.5),
            relationship_intensity=float(payload.get("relationship_intensity", 0.5) or 0.5),
            reasoning_required=bool(payload.get("reasoning_required")),
            needs_recipe_recommendation=bool(payload.get("needs_recipe_recommendation")),
            recommendation_hits=dedupe_preserve_order(payload.get("recommendation_hits") or []),
            relation_hits=dedupe_preserve_order(payload.get("relation_hits") or []),
            constraint_hits=dedupe_preserve_order(payload.get("constraint_hits") or []),
            structural_hits=dedupe_preserve_order(payload.get("structural_hits") or []),
            fast_rule_hits=dedupe_preserve_order(payload.get("fast_rule_hits") or []),
            score_breakdown=(
                score_breakdown
                if isinstance(score_breakdown, QuerySemanticScoreBreakdown)
                else QuerySemanticScoreBreakdown.from_dict(score_breakdown)
            ),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "query": self.query,
            "query_type": self.query_type,
            "source_entities": list(self.source_entities),
            "target_entities": list(self.target_entities),
            "relation_types": list(self.relation_types),
            "entity_keywords": list(self.entity_keywords),
            "topic_keywords": list(self.topic_keywords),
            "constraints": dict(self.constraints or {}),
            "complexity": self.complexity,
            "relationship_intensity": self.relationship_intensity,
            "reasoning_required": self.reasoning_required,
            "needs_recipe_recommendation": self.needs_recipe_recommendation,
            "recommendation_hits": list(self.recommendation_hits),
            "relation_hits": list(self.relation_hits),
            "constraint_hits": list(self.constraint_hits),
            "structural_hits": list(self.structural_hits),
            "fast_rule_hits": list(self.fast_rule_hits),
            "score_breakdown": self.score_breakdown.to_dict(),
        }


def default_entity_linker_query_type_priorities() -> Dict[str, List[str]]:
    return {key: list(value) for key, value in POLICY.entity_linker_query_type_priorities.items()}


def default_entity_linker_relation_priorities() -> Dict[str, List[str]]:
    return {key: list(value) for key, value in POLICY.entity_linker_relation_priorities.items()}


def dedupe_preserve_order(values: Iterable[Any]) -> List[str]:
    seen = set()
    result: List[str] = []
    for value in values or []:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def relation_index_terms(
    relation_type: str,
    source_name: str = "",
    target_name: str = "",
) -> List[str]:
    reverse_hints = [
        term
        for term, mapped_relation in SEMANTIC_RELATION_HINTS.items()
        if mapped_relation == relation_type
    ]
    return dedupe_preserve_order(
        [
            relation_type,
            source_name,
            target_name,
            *RELATION_INDEX_KEYWORDS.get(relation_type, ()),
            *reverse_hints,
        ]
    )


def contains_any(text: str, terms: Sequence[str]) -> bool:
    if not text or not terms:
        return False
    return any(term and term in text for term in terms)


def marker_hits(text: str, markers: Sequence[str]) -> List[str]:
    if not text or not markers:
        return []
    return dedupe_preserve_order([marker for marker in markers if marker and marker in text])


def normalize_query_text(query: str) -> str:
    import re

    return re.sub(r"\s+", "", str(query or "").strip())


__all__ = [
    "AMBIGUOUS_RECOMMENDATION_MARKERS",
    "CLUSTERING_MARKERS",
    "CONSTRAINT_MARKERS",
    "CUISINE_STYLE_TERMS",
    "DEFAULT_ENTITY_LINKER_PREFERRED_LABELS",
    "DIET_TERMS",
    "DIFFICULTY_TERMS",
    "ENTITY_HINTS",
    "ENTITY_PHRASE_MARKERS",
    "ENTITY_TARGET_MARKERS",
    "EXPLICIT_RECOMMENDATION_MARKERS",
    "FAST_RULE_MARKERS",
    "FILTERING_MARKERS",
    "FLAVOR_TERMS",
    "GRAPH_GENERIC_TERMS",
    "GRAPH_QUERY_TYPES",
    "GRAPH_RELATION_TYPES",
    "GRAPH_ROUTING_STRATEGIES",
    "GRAPH_SOURCE_PREFIXES",
    "GRAPH_SOURCE_SUFFIXES",
    "HEALTH_TERMS",
    "INGREDIENT_CATEGORY_TERMS",
    "PATH_MARKERS",
    "POLICY",
    "QUERY_STOPWORDS",
    "QuerySemanticProfile",
    "QuerySemanticScoreBreakdown",
    "RECOMMENDATION_MARKERS",
    "RELATION_INDEX_KEYWORDS",
    "RELATION_MARKERS",
    "RELATION_QUERY_MARKERS",
    "SEMANTIC_NODE_TERMS",
    "SEMANTIC_RELATION_HINTS",
    "STRUCTURAL_REASONING_MARKERS",
    "SUBGRAPH_MARKERS",
    "TECHNIQUE_TERMS",
    "TEXTURE_EFFECT_TERMS",
    "TIME_MARKERS",
    "contains_any",
    "dedupe_preserve_order",
    "default_entity_linker_query_type_priorities",
    "default_entity_linker_relation_priorities",
    "marker_hits",
    "normalize_query_text",
    "relation_index_terms",
]
