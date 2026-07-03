"""Shared lexical registry and helper functions for query understanding."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Dict, Iterable, Iterator, List, Mapping, Sequence, Tuple

from ..domain.shared.semantic_schema import SEMANTIC_RELATION_TYPES
from ..query_policy import get_query_policy
from ..query_policy.models import QueryPolicyBundle


@dataclass(frozen=True)
class QueryUnderstandingRegistry:
    """Policy-derived lexical and relation registry for one runtime."""

    policy: QueryPolicyBundle
    graph_routing_strategies: Tuple[str, ...]
    graph_query_types: Tuple[str, ...]
    graph_relation_types: Tuple[str, ...]
    flavor_terms: Tuple[str, ...]
    texture_effect_terms: Tuple[str, ...]
    technique_terms: Tuple[str, ...]
    diet_terms: Tuple[str, ...]
    health_terms: Tuple[str, ...]
    cuisine_style_terms: Tuple[str, ...]
    ingredient_category_terms: Tuple[str, ...]
    difficulty_terms: Tuple[str, ...]
    time_markers: Tuple[str, ...]
    path_markers: Tuple[str, ...]
    subgraph_markers: Tuple[str, ...]
    clustering_markers: Tuple[str, ...]
    recommendation_markers: Tuple[str, ...]
    explicit_recommendation_markers: Tuple[str, ...]
    ambiguous_recommendation_markers: Tuple[str, ...]
    filtering_markers: Tuple[str, ...]
    structural_reasoning_markers: Tuple[str, ...]
    relation_markers: Tuple[str, ...]
    fast_rule_markers: Tuple[str, ...]
    constraint_markers: Tuple[str, ...]
    entity_hints: Tuple[str, ...]
    entity_phrase_markers: Tuple[str, ...]
    entity_target_markers: Tuple[str, ...]
    graph_generic_terms: Tuple[str, ...]
    query_stopwords: Tuple[str, ...]
    graph_source_prefixes: Tuple[str, ...]
    graph_source_suffixes: Tuple[str, ...]
    semantic_relation_hints: Dict[str, str]
    relation_index_keywords: Dict[str, Tuple[str, ...]]
    relation_query_markers: Dict[str, Tuple[str, ...]]
    default_entity_linker_preferred_labels: Tuple[str, ...]
    semantic_node_terms: Tuple[str, ...]

    @classmethod
    def from_policy_bundle(cls, policy: QueryPolicyBundle) -> "QueryUnderstandingRegistry":
        semantic_node_terms = _flatten_policy_term_groups(
            policy,
            "flavor_terms",
            "texture_effect_terms",
            "technique_terms",
            "diet_terms",
            "health_terms",
            "cuisine_style_terms",
            "ingredient_category_terms",
            "difficulty_terms",
        )
        return cls(
            policy=policy,
            graph_routing_strategies=policy.relations.graph_routing_strategies,
            graph_query_types=policy.relations.graph_query_types,
            graph_relation_types=tuple(
                dict.fromkeys([*policy.relations.graph_relation_types, *SEMANTIC_RELATION_TYPES])
            ),
            flavor_terms=policy.lexicon.term_group("flavor_terms"),
            texture_effect_terms=policy.lexicon.term_group("texture_effect_terms"),
            technique_terms=policy.lexicon.term_group("technique_terms"),
            diet_terms=policy.lexicon.term_group("diet_terms"),
            health_terms=policy.lexicon.term_group("health_terms"),
            cuisine_style_terms=policy.lexicon.term_group("cuisine_style_terms"),
            ingredient_category_terms=policy.lexicon.term_group("ingredient_category_terms"),
            difficulty_terms=policy.lexicon.term_group("difficulty_terms"),
            time_markers=policy.lexicon.term_group("time_markers"),
            path_markers=policy.lexicon.term_group("path_markers"),
            subgraph_markers=policy.lexicon.term_group("subgraph_markers"),
            clustering_markers=policy.lexicon.term_group("clustering_markers"),
            recommendation_markers=policy.lexicon.term_group("recommendation_markers"),
            explicit_recommendation_markers=policy.lexicon.term_group(
                "explicit_recommendation_markers"
            ),
            ambiguous_recommendation_markers=policy.lexicon.term_group(
                "ambiguous_recommendation_markers"
            ),
            filtering_markers=policy.lexicon.term_group("filtering_markers"),
            structural_reasoning_markers=policy.lexicon.term_group("structural_reasoning_markers"),
            relation_markers=policy.lexicon.term_group("relation_markers"),
            fast_rule_markers=policy.lexicon.term_group("fast_rule_markers"),
            constraint_markers=policy.lexicon.term_group("constraint_markers"),
            entity_hints=policy.lexicon.term_group("entity_hints"),
            entity_phrase_markers=policy.lexicon.term_group("entity_phrase_markers"),
            entity_target_markers=policy.lexicon.term_group("entity_target_markers"),
            graph_generic_terms=policy.lexicon.term_group("graph_generic_terms"),
            query_stopwords=policy.lexicon.term_group("query_stopwords"),
            graph_source_prefixes=policy.lexicon.term_group("graph_source_prefixes"),
            graph_source_suffixes=policy.lexicon.term_group("graph_source_suffixes"),
            semantic_relation_hints=dict(policy.relations.semantic_relation_hints),
            relation_index_keywords=dict(policy.relations.relation_index_keywords),
            relation_query_markers=dict(policy.relations.relation_query_markers),
            default_entity_linker_preferred_labels=(
                policy.relations.entity_linker_preferred_labels
            ),
            semantic_node_terms=semantic_node_terms,
        )

    def default_entity_linker_query_type_priorities(self) -> Dict[str, List[str]]:
        return {
            key: list(value)
            for key, value in self.policy.relations.entity_linker_query_type_priorities.items()
        }

    def default_entity_linker_relation_priorities(self) -> Dict[str, List[str]]:
        return {
            key: list(value)
            for key, value in self.policy.relations.entity_linker_relation_priorities.items()
        }

    def relation_index_terms(
        self,
        relation_type: str,
        source_name: str = "",
        target_name: str = "",
    ) -> List[str]:
        reverse_hints = [
            term
            for term, mapped_relation in self.semantic_relation_hints.items()
            if mapped_relation == relation_type
        ]
        return dedupe_preserve_order(
            [
                relation_type,
                source_name,
                target_name,
                *self.relation_index_keywords.get(relation_type, ()),
                *reverse_hints,
            ]
        )


def _flatten_policy_term_groups(policy: QueryPolicyBundle, *names: str) -> Tuple[str, ...]:
    merged: list[str] = []
    for name in names:
        merged.extend(policy.lexicon.term_group(name))
    return tuple(dedupe_preserve_order(merged))


@lru_cache(maxsize=1)
def default_query_registry() -> QueryUnderstandingRegistry:
    return QueryUnderstandingRegistry.from_policy_bundle(get_query_policy())


def query_registry(
    policy_bundle: QueryPolicyBundle | None = None,
) -> QueryUnderstandingRegistry:
    if policy_bundle is None:
        return default_query_registry()
    return QueryUnderstandingRegistry.from_policy_bundle(policy_bundle)


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


def default_entity_linker_query_type_priorities() -> Dict[str, List[str]]:
    return default_query_registry().default_entity_linker_query_type_priorities()


def default_entity_linker_relation_priorities() -> Dict[str, List[str]]:
    return default_query_registry().default_entity_linker_relation_priorities()


def relation_index_terms(
    relation_type: str,
    source_name: str = "",
    target_name: str = "",
) -> List[str]:
    return default_query_registry().relation_index_terms(
        relation_type,
        source_name=source_name,
        target_name=target_name,
    )


class _LazyPolicyBundle:
    @property
    def metadata(self):
        return default_query_registry().policy.metadata

    @property
    def lexicon(self):
        return default_query_registry().policy.lexicon

    @property
    def relations(self):
        return default_query_registry().policy.relations

    @property
    def scoring(self):
        return default_query_registry().policy.scoring

    @property
    def routing(self):
        return default_query_registry().policy.routing

    @property
    def graph(self):
        return default_query_registry().policy.graph

    @property
    def generation(self):
        return default_query_registry().policy.generation

    @property
    def runtime_defaults(self):
        return default_query_registry().policy.runtime_defaults

    @property
    def prompts(self):
        return default_query_registry().policy.prompts

    def term_group(self, name: str) -> tuple[str, ...]:
        return default_query_registry().policy.term_group(name)

    def regex_group(self, name: str) -> tuple[str, ...]:
        return default_query_registry().policy.regex_group(name)


class _LazyRegistryTuple(Sequence[str]):
    def __init__(self, registry_attribute: str) -> None:
        self.registry_attribute = registry_attribute

    def _value(self) -> Tuple[str, ...]:
        return tuple(getattr(default_query_registry(), self.registry_attribute))

    def __iter__(self) -> Iterator[str]:
        return iter(self._value())

    def __len__(self) -> int:
        return len(self._value())

    def __getitem__(self, index):
        return self._value()[index]

    def __contains__(self, item: object) -> bool:
        return item in self._value()

    def __bool__(self) -> bool:
        return bool(self._value())

    def __eq__(self, other: object) -> bool:
        return self._value() == other

    def __repr__(self) -> str:
        return repr(self._value())


class _LazyRegistryDict(Mapping[str, object]):
    def __init__(self, registry_attribute: str) -> None:
        self.registry_attribute = registry_attribute

    def _value(self) -> Dict[str, object]:
        return dict(getattr(default_query_registry(), self.registry_attribute))

    def __iter__(self) -> Iterator[str]:
        return iter(self._value())

    def __len__(self) -> int:
        return len(self._value())

    def __getitem__(self, key: str) -> object:
        return self._value()[key]

    def __contains__(self, item: object) -> bool:
        return item in self._value()

    def __eq__(self, other: object) -> bool:
        return self._value() == other

    def __repr__(self) -> str:
        return repr(self._value())


_LEGACY_REGISTRY_ATTRIBUTES: Mapping[str, str] = {
    "GRAPH_ROUTING_STRATEGIES": "graph_routing_strategies",
    "GRAPH_QUERY_TYPES": "graph_query_types",
    "GRAPH_RELATION_TYPES": "graph_relation_types",
    "FLAVOR_TERMS": "flavor_terms",
    "TEXTURE_EFFECT_TERMS": "texture_effect_terms",
    "TECHNIQUE_TERMS": "technique_terms",
    "DIET_TERMS": "diet_terms",
    "HEALTH_TERMS": "health_terms",
    "CUISINE_STYLE_TERMS": "cuisine_style_terms",
    "INGREDIENT_CATEGORY_TERMS": "ingredient_category_terms",
    "DIFFICULTY_TERMS": "difficulty_terms",
    "TIME_MARKERS": "time_markers",
    "PATH_MARKERS": "path_markers",
    "SUBGRAPH_MARKERS": "subgraph_markers",
    "CLUSTERING_MARKERS": "clustering_markers",
    "RECOMMENDATION_MARKERS": "recommendation_markers",
    "EXPLICIT_RECOMMENDATION_MARKERS": "explicit_recommendation_markers",
    "AMBIGUOUS_RECOMMENDATION_MARKERS": "ambiguous_recommendation_markers",
    "FILTERING_MARKERS": "filtering_markers",
    "STRUCTURAL_REASONING_MARKERS": "structural_reasoning_markers",
    "RELATION_MARKERS": "relation_markers",
    "FAST_RULE_MARKERS": "fast_rule_markers",
    "CONSTRAINT_MARKERS": "constraint_markers",
    "ENTITY_HINTS": "entity_hints",
    "ENTITY_PHRASE_MARKERS": "entity_phrase_markers",
    "ENTITY_TARGET_MARKERS": "entity_target_markers",
    "GRAPH_GENERIC_TERMS": "graph_generic_terms",
    "QUERY_STOPWORDS": "query_stopwords",
    "GRAPH_SOURCE_PREFIXES": "graph_source_prefixes",
    "GRAPH_SOURCE_SUFFIXES": "graph_source_suffixes",
    "SEMANTIC_RELATION_HINTS": "semantic_relation_hints",
    "RELATION_INDEX_KEYWORDS": "relation_index_keywords",
    "RELATION_QUERY_MARKERS": "relation_query_markers",
    "DEFAULT_ENTITY_LINKER_PREFERRED_LABELS": "default_entity_linker_preferred_labels",
    "SEMANTIC_NODE_TERMS": "semantic_node_terms",
}


POLICY = _LazyPolicyBundle()
GRAPH_ROUTING_STRATEGIES = _LazyRegistryTuple("graph_routing_strategies")
GRAPH_QUERY_TYPES = _LazyRegistryTuple("graph_query_types")
GRAPH_RELATION_TYPES = _LazyRegistryTuple("graph_relation_types")
FLAVOR_TERMS = _LazyRegistryTuple("flavor_terms")
TEXTURE_EFFECT_TERMS = _LazyRegistryTuple("texture_effect_terms")
TECHNIQUE_TERMS = _LazyRegistryTuple("technique_terms")
DIET_TERMS = _LazyRegistryTuple("diet_terms")
HEALTH_TERMS = _LazyRegistryTuple("health_terms")
CUISINE_STYLE_TERMS = _LazyRegistryTuple("cuisine_style_terms")
INGREDIENT_CATEGORY_TERMS = _LazyRegistryTuple("ingredient_category_terms")
DIFFICULTY_TERMS = _LazyRegistryTuple("difficulty_terms")
TIME_MARKERS = _LazyRegistryTuple("time_markers")
PATH_MARKERS = _LazyRegistryTuple("path_markers")
SUBGRAPH_MARKERS = _LazyRegistryTuple("subgraph_markers")
CLUSTERING_MARKERS = _LazyRegistryTuple("clustering_markers")
RECOMMENDATION_MARKERS = _LazyRegistryTuple("recommendation_markers")
EXPLICIT_RECOMMENDATION_MARKERS = _LazyRegistryTuple("explicit_recommendation_markers")
AMBIGUOUS_RECOMMENDATION_MARKERS = _LazyRegistryTuple("ambiguous_recommendation_markers")
FILTERING_MARKERS = _LazyRegistryTuple("filtering_markers")
STRUCTURAL_REASONING_MARKERS = _LazyRegistryTuple("structural_reasoning_markers")
RELATION_MARKERS = _LazyRegistryTuple("relation_markers")
FAST_RULE_MARKERS = _LazyRegistryTuple("fast_rule_markers")
CONSTRAINT_MARKERS = _LazyRegistryTuple("constraint_markers")
ENTITY_HINTS = _LazyRegistryTuple("entity_hints")
ENTITY_PHRASE_MARKERS = _LazyRegistryTuple("entity_phrase_markers")
ENTITY_TARGET_MARKERS = _LazyRegistryTuple("entity_target_markers")
GRAPH_GENERIC_TERMS = _LazyRegistryTuple("graph_generic_terms")
QUERY_STOPWORDS = _LazyRegistryTuple("query_stopwords")
GRAPH_SOURCE_PREFIXES = _LazyRegistryTuple("graph_source_prefixes")
GRAPH_SOURCE_SUFFIXES = _LazyRegistryTuple("graph_source_suffixes")
SEMANTIC_RELATION_HINTS = _LazyRegistryDict("semantic_relation_hints")
RELATION_INDEX_KEYWORDS = _LazyRegistryDict("relation_index_keywords")
RELATION_QUERY_MARKERS = _LazyRegistryDict("relation_query_markers")
DEFAULT_ENTITY_LINKER_PREFERRED_LABELS = _LazyRegistryTuple(
    "default_entity_linker_preferred_labels"
)
SEMANTIC_NODE_TERMS = _LazyRegistryTuple("semantic_node_terms")


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
    "QueryUnderstandingRegistry",
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
    "default_query_registry",
    "marker_hits",
    "normalize_query_text",
    "query_registry",
    "relation_index_terms",
]
