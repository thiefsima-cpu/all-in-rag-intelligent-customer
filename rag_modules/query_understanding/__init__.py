"""Structured query-understanding package."""

from __future__ import annotations

from importlib import import_module

_LAZY_EXPORTS = {
    "QueryPlanner": ".planning",
    "build_query_semantic_score_breakdown": ".scoring",
    "clean_entity_phrase": ".features",
    "contains_any": ".registry",
    "dedupe_preserve_order": ".registry",
    "default_entity_linker_query_type_priorities": ".registry",
    "default_entity_linker_relation_priorities": ".registry",
    "estimate_query_complexity": ".scoring",
    "estimate_relationship_intensity": ".scoring",
    "extract_entity_candidates": ".features",
    "extract_excluded_terms": ".features",
    "extract_minutes": ".features",
    "extract_query_tokens": ".features",
    "fallback_entity_phrases": ".features",
    "fallback_keywords": ".features",
    "has_filtering_intent": ".features",
    "has_recommendation_intent": ".features",
    "infer_graph_max_depth": ".graph_intent",
    "infer_graph_max_nodes": ".graph_intent",
    "infer_graph_query_type": ".features",
    "infer_query_constraints": ".features",
    "infer_query_semantic_profile": ".graph_intent",
    "infer_relation_types": ".features",
    "marker_hits": ".registry",
    "normalize_graph_sources": ".features",
    "normalize_query_text": ".registry",
    "query_registry": ".registry",
    "relation_index_terms": ".registry",
    "should_use_fast_rule_plan": ".scoring",
    "split_graph_entities": ".graph_intent",
}

_REGISTRY_EXPORTS = {
    "AMBIGUOUS_RECOMMENDATION_MARKERS",
    "CLUSTERING_MARKERS",
    "CONSTRAINT_MARKERS",
    "CUISINE_STYLE_TERMS",
    "DEFAULT_ENTITY_LINKER_PREFERRED_LABELS",
    "DIET_TERMS",
    "DIFFICULTY_TERMS",
    "ENTITY_HINTS",
    "ENTITY_PHRASE_MARKERS",
    "FAST_RULE_MARKERS",
    "FILTERING_MARKERS",
    "FLAVOR_TERMS",
    "GRAPH_GENERIC_TERMS",
    "GRAPH_QUERY_TYPES",
    "GRAPH_RELATION_TYPES",
    "GRAPH_ROUTING_STRATEGIES",
    "HEALTH_TERMS",
    "INGREDIENT_CATEGORY_TERMS",
    "PATH_MARKERS",
    "QUERY_STOPWORDS",
    "QueryUnderstandingRegistry",
    "RECOMMENDATION_MARKERS",
    "RELATION_INDEX_KEYWORDS",
    "RELATION_MARKERS",
    "SEMANTIC_NODE_TERMS",
    "SEMANTIC_RELATION_HINTS",
    "STRUCTURAL_REASONING_MARKERS",
    "SUBGRAPH_MARKERS",
    "TECHNIQUE_TERMS",
    "TEXTURE_EFFECT_TERMS",
    "TIME_MARKERS",
}


def __getattr__(name: str) -> object:
    if name in _REGISTRY_EXPORTS:
        return getattr(import_module(".registry", __name__), name)
    module_name = _LAZY_EXPORTS.get(name)
    if module_name is not None:
        return getattr(import_module(module_name, __name__), name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = sorted([*_LAZY_EXPORTS, *_REGISTRY_EXPORTS])
